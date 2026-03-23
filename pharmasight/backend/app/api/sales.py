"""
Sales API routes (KRA Compliant)
"""
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from fastapi import Query
from fastapi.responses import Response
from app.dependencies import get_tenant_db, get_tenant_or_default, get_tenant_optional, get_current_user, require_document_belongs_to_user_company
from app.services.document_pdf_generator import build_sales_invoice_pdf
from app.services.tenant_storage_service import download_file, get_signed_url
from app.models import (
    SalesInvoice, SalesInvoiceItem, InventoryLedger,
    Item, InvoicePayment, UserBranchRole, UserRole,
    CreditNote, CreditNoteItem,
)
from app.models.company import Company, Branch
from app.models.tenant import Tenant
from app.models.user import User
from app.models.permission import Permission, RolePermission
from app.schemas.sale import (
    SalesInvoiceCreate, SalesInvoiceResponse,
    SalesInvoiceItemCreate, SalesInvoiceItemUpdate, SalesInvoiceUpdate,
    BatchSalesInvoiceRequest,
    InvoicePaymentCreate, InvoicePaymentResponse,
    CreditNoteCreate, CreditNoteResponse,
)
from app.services.inventory_service import InventoryService
from app.services.pricing_service import PricingService
from app.services.document_service import DocumentService
from app.services.order_book_service import OrderBookService
from app.services.item_units_helper import get_unit_display_short, get_unit_multiplier_from_item
from app.services.snapshot_service import SnapshotService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.pricing_config_service import validate_line_price, is_line_price_at_promo
from app.utils.vat import vat_rate_to_percent

router = APIRouter()

# Log when draft snapshot COGS (qty×mult×unit_cost_used) would differ from batched ledger by
# more than this fraction of line revenue (before overwriting unit_cost_used at batch).
SNAPSHOT_VS_LEDGER_WARN_THRESHOLD = Decimal("0.01")  # 1% of line_total_exclusive


def _total_cost_from_allocations(allocations: list) -> Decimal:
    """Sum qty×unit_cost across FEFO allocations (matches posted SALE ledger total_cost)."""
    total = Decimal("0")
    for a in allocations or []:
        qty = Decimal(str(a.get("quantity", 0)))
        uc = Decimal(str(a.get("unit_cost", 0)))
        total += qty * uc
    return total


def _resolve_date_range(
    preset: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Resolve a reporting date range (inclusive). Defaults to today."""
    today = date.today()
    p = (preset or "").strip().lower()

    if p in ("", "custom"):
        sd = start_date or today
        ed = end_date or sd
    elif p in ("today",):
        sd = today
        ed = today
    elif p in ("yesterday",):
        y = today - timedelta(days=1)
        sd = y
        ed = y
    elif p in ("this_week", "week", "current_week"):
        # Monday..Sunday
        sd = today - timedelta(days=today.weekday())
        ed = sd + timedelta(days=6)
    elif p in ("last_week", "previous_week"):
        end_of_last_week = (today - timedelta(days=today.weekday() + 1))
        sd = end_of_last_week - timedelta(days=6)
        ed = end_of_last_week
    elif p in ("this_month", "month", "current_month"):
        sd = today.replace(day=1)
        next_month = (sd.replace(day=28) + timedelta(days=4)).replace(day=1)
        ed = next_month - timedelta(days=1)
    elif p in ("last_month", "previous_month"):
        first_this_month = today.replace(day=1)
        last_of_last_month = first_this_month - timedelta(days=1)
        sd = last_of_last_month.replace(day=1)
        ed = last_of_last_month
    elif p in ("this_year", "year", "current_year"):
        sd = today.replace(month=1, day=1)
        ed = today.replace(month=12, day=31)
    elif p in ("last_year", "previous_year"):
        sd = today.replace(year=today.year - 1, month=1, day=1)
        ed = today.replace(year=today.year - 1, month=12, day=31)
    else:
        # Unknown preset: treat as custom
        sd = start_date or today
        ed = end_date or sd

    if sd > ed:
        sd, ed = ed, sd
    return sd, ed


def _user_has_sell_below_min_margin(db: Session, user_id: UUID, branch_id: UUID) -> bool:
    """True if user has permission sales.sell_below_min_margin for this branch (via their role)."""
    perm = db.query(Permission).filter(Permission.name == "sales.sell_below_min_margin").first()
    if not perm:
        return False
    ubr = (
        db.query(UserBranchRole)
        .join(UserRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user_id, UserBranchRole.branch_id == branch_id)
        .first()
    )
    if not ubr:
        return False
    rp = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_id == ubr.role_id,
            RolePermission.permission_id == perm.id,
            RolePermission.branch_id.is_(None),
        )
        .first()
    )
    return rp is not None


@router.post("/invoice", response_model=SalesInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_sales_invoice(
    invoice: SalesInvoiceCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create a sales invoice as DRAFT
    
    Saves the invoice as DRAFT. Stock is NOT reduced until invoice is batched.
    Only DRAFT invoices can be edited or deleted.
    
    If payment_mode is 'credit', customer_name and customer_phone are required.
    """
    # Validate credit payment mode requirements
    if invoice.payment_mode == 'credit':
        if not invoice.customer_name or not invoice.customer_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Customer name is required when payment mode is 'credit'"
            )
        if not invoice.customer_phone or not invoice.customer_phone.strip():
            raise HTTPException(
                status_code=400,
                detail="Customer phone number is required when payment mode is 'credit'"
            )
        # Basic phone validation (should contain digits)
        import re
        phone_digits = re.sub(r'\D', '', invoice.customer_phone)
        if len(phone_digits) < 9:
            raise HTTPException(
                status_code=400,
                detail="Customer phone number must be a valid phone number (at least 9 digits)"
            )
    
    # Generate invoice number
    invoice_no = DocumentService.get_sales_invoice_number(
        db, invoice.company_id, invoice.branch_id
    )
    
    # Enforce one line per item per invoice: reject duplicate item_id in request
    item_ids = [it.item_id for it in invoice.items]
    if len(item_ids) != len(set(item_ids)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate item in request. Each item can only appear once per invoice."
        )
    items_to_save = invoice.items

    # Calculate totals
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    
    # Process each item
    invoice_items = []
    
    # Check if customer_phone column exists (for backward compatibility)
    from sqlalchemy import inspect
    inspector = inspect(SalesInvoice)
    has_customer_phone = 'customer_phone' in [col.name for col in inspector.columns]
    
    for item_data in items_to_save:
        # Get item
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        if not getattr(item, "setup_complete", True):
            raise HTTPException(
                status_code=400,
                detail=f"Item '{item.name}' is not ready for transactions. Complete item setup (pack size, units) in Items before adding to a sale."
            )
        
        # Copy VAT classification from item (Kenya: percentage e.g. 16; normalize if stored as 0.16)
        item_vat_rate = Decimal(str(vat_rate_to_percent(item.vat_rate)))
        
        # Check availability (but don't allocate yet - that happens on batch)
        is_available, available, required = InventoryService.check_stock_availability(
            db, item_data.item_id, invoice.branch_id,
            float(item_data.quantity), item_data.unit_name
        )
        if not is_available:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {item.name}. Available: {available}, Required: {required}"
            )
        
        # Get recommended price if not provided
        # Use appropriate tier based on sales_type (wholesale / retail / supplier; supplier falls back to wholesale if not set)
        sales_type = getattr(invoice, 'sales_type', 'RETAIL') or 'RETAIL'
        if sales_type == 'WHOLESALE':
            pricing_tier = 'wholesale'
        elif sales_type == 'SUPPLIER':
            pricing_tier = 'supplier'
        else:
            pricing_tier = 'retail'
        
        unit_price = item_data.unit_price_exclusive
        unit_cost_used = None
        
        if not unit_price:
            price_info = PricingService.calculate_recommended_price(
                db, item_data.item_id, invoice.branch_id,
                invoice.company_id, item_data.unit_name, tier=pricing_tier
            )
            # Supplier tier: if no supplier price/unit, fall back to wholesale
            if not price_info and pricing_tier == 'supplier':
                price_info = PricingService.calculate_recommended_price(
                    db, item_data.item_id, invoice.branch_id,
                    invoice.company_id, item_data.unit_name, tier='wholesale'
                )
            if price_info:
                unit_price = price_info["recommended_unit_price"]
                unit_cost_used = price_info["unit_cost_used"]
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Price not available for {item.name}"
                )
        else:
            # Get cost for margin calculation and min-margin check
            cost_info = PricingService.get_item_cost(
                db, item_data.item_id, invoice.branch_id
            )
            if cost_info:
                # unit_cost_used = cost per retail/base unit (from CanonicalPricingService)
                unit_cost_used = cost_info
            # Price validation (floor + margin + promo)
            if unit_cost_used and float(unit_cost_used) > 0:
                mult = get_unit_multiplier_from_item(item, item_data.unit_name)
                if mult is not None and mult > 0:
                    cost_per_sale_unit = unit_cost_used * mult
                    unit_price_val = Decimal(str(unit_price))
                    if cost_per_sale_unit > 0:
                        user_has_override = _user_has_sell_below_min_margin(db, invoice.created_by, invoice.branch_id)
                        is_promo = is_line_price_at_promo(
                            db, item_data.item_id, item_data.unit_name or "", unit_price_val
                        )
                        validation = validate_line_price(
                            db,
                            invoice.company_id,
                            item_data.item_id,
                            unit_price_val,
                            cost_per_sale_unit,
                            user_has_override,
                            branch_id=invoice.branch_id,
                            is_promo_price=is_promo,
                        )
                        if not validation.get("allowed"):
                            raise HTTPException(
                                status_code=400,
                                detail=validation.get("message", "Price validation failed.")
                            )
        
        # Calculate line totals
        line_total_exclusive = Decimal(str(unit_price)) * item_data.quantity
        discount_amount = item_data.discount_amount or (line_total_exclusive * item_data.discount_percent / Decimal("100"))
        line_total_exclusive -= discount_amount
        line_vat = line_total_exclusive * item_vat_rate / Decimal("100")
        line_total_inclusive = line_total_exclusive + line_vat
        
        # Create invoice item with cached item details
        invoice_item = SalesInvoiceItem(
            sales_invoice_id=None,  # Will be set after invoice creation
            item_id=item_data.item_id,
            batch_id=None,  # Will be set when batched
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_price_exclusive=unit_price,
            discount_percent=item_data.discount_percent,
            discount_amount=discount_amount,
            vat_rate=item_vat_rate,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive,
            unit_cost_used=unit_cost_used,
            item_name=item.name,  # Cache item name
            item_code=item.sku or ''  # Cache item code
        )
        invoice_items.append(invoice_item)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
    
    # Apply invoice-level discount
    total_exclusive -= invoice.discount_amount
    total_inclusive = total_exclusive + total_vat
    
    # Calculate average VAT rate for invoice header
    invoice_vat_rate = (total_vat / total_exclusive * Decimal("100")) if total_exclusive > 0 else Decimal("0")
    
    # Create invoice as DRAFT
    # Check if customer_phone column exists in the model
    invoice_data = {
        'company_id': invoice.company_id,
        'branch_id': invoice.branch_id,
        'invoice_no': invoice_no,
        'invoice_date': invoice.invoice_date,
        'customer_name': invoice.customer_name,
        'customer_pin': invoice.customer_pin,
        'payment_mode': invoice.payment_mode,
        'payment_status': invoice.payment_status or "UNPAID",
        'sales_type': getattr(invoice, 'sales_type', 'RETAIL') or 'RETAIL',
        'status': invoice.status or "DRAFT",  # Save as DRAFT
        'total_exclusive': total_exclusive,
        'vat_rate': invoice_vat_rate,
        'vat_amount': total_vat,
        'discount_amount': invoice.discount_amount,
        'total_inclusive': total_inclusive,
        'created_by': invoice.created_by
    }
    
    # Only set customer_phone if the column exists (backward compatibility)
    if hasattr(SalesInvoice, 'customer_phone') and hasattr(invoice, 'customer_phone'):
        invoice_data['customer_phone'] = invoice.customer_phone
    
    db_invoice = SalesInvoice(**invoice_data)
    db.add(db_invoice)
    db.flush()
    
    # Link items to invoice
    for item in invoice_items:
        item.sales_invoice_id = db_invoice.id
        db.add(item)
    
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.get("/invoice/{invoice_id}/pdf")
def get_sales_invoice_pdf(
    invoice_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Optional[Tenant] = Depends(get_tenant_optional),
    db: Session = Depends(get_tenant_db),
):
    """Generate and return sales invoice as PDF (Download PDF). On-demand only.
    Logo on right, company on left; footer: prepared by, printed by, served by, till/paybill from branch. No status."""
    from sqlalchemy.orm import selectinload
    user = current_user_and_db[0]
    invoice = db.query(SalesInvoice).options(
        selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item)
    ).filter(SalesInvoice.id == invoice_id).first()
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)
    company = db.query(Company).filter(Company.id == invoice.company_id).first()
    branch = db.query(Branch).filter(Branch.id == invoice.branch_id).first()
    items_data = []
    for oi in invoice.items:
        item_name = oi.item.name if oi.item else (getattr(oi, "item_name", None) or "—")
        items_data.append({
            "item_name": item_name,
            "quantity": float(oi.quantity),
            "unit_name": oi.unit_name or "",
            "unit_price_exclusive": float(oi.unit_price_exclusive or 0),
            "line_total_exclusive": float(oi.line_total_exclusive or 0),
            "line_total_inclusive": float(oi.line_total_inclusive or 0),
        })
    company_logo_bytes = None
    if company and getattr(company, "logo_url", None) and str(company.logo_url or "").startswith("tenant-assets/") and tenant is not None:
        company_logo_bytes = download_file(company.logo_url, tenant=tenant)
    till_number = getattr(branch, "till_number", None) if branch else None
    paybill = getattr(branch, "paybill", None) if branch else None
    prepared_by = None
    served_by = None
    creator = db.query(User).filter(User.id == invoice.created_by).first()
    if creator:
        prepared_by = getattr(creator, "full_name", None) or getattr(creator, "username", None) or str(invoice.created_by)
        served_by = prepared_by
    try:
        pdf_bytes = build_sales_invoice_pdf(
            company_name=company.name if company else "—",
            company_address=getattr(company, "address", None) if company else None,
            company_phone=getattr(company, "phone", None) if company else None,
            company_pin=getattr(company, "pin", None) if company else None,
            company_logo_bytes=company_logo_bytes,
            branch_name=branch.name if branch else None,
            branch_address=getattr(branch, "address", None) if branch else None,
            invoice_no=invoice.invoice_no,
            invoice_date=invoice.invoice_date,
            customer_name=invoice.customer_name,
            customer_phone=getattr(invoice, "customer_phone", None),
            payment_mode=getattr(invoice, "payment_mode", None),
            items=items_data,
            total_exclusive=invoice.total_exclusive or Decimal("0"),
            vat_amount=invoice.vat_amount or Decimal("0"),
            total_inclusive=invoice.total_inclusive or Decimal("0"),
            notes=getattr(invoice, "notes", None),
            till_number=till_number,
            paybill=paybill,
            prepared_by=prepared_by,
            printed_by=None,
            served_by=served_by,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate sales invoice PDF: {str(e)}")
    filename = f"sales-invoice-{invoice.invoice_no or invoice_id}.pdf".replace(" ", "-")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _get_sales_invoice_response(
    invoice_id: UUID,
    db: Session,
    user: User,
    *,
    request: Optional[Request] = None,
    tenant: Optional[Tenant] = None,
):
    """Build sales invoice response (load, enrich, return). Optional request for timings; optional tenant for logo URL."""
    import time as _time
    t0 = _time.perf_counter()
    if request is not None:
        request.state.timings = {}
    from sqlalchemy.orm import selectinload
    invoice = db.query(SalesInvoice).options(
        selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item)
    ).filter(SalesInvoice.id == invoice_id).first()
    if request is not None:
        request.state.timings["LoadMs"] = round((_time.perf_counter() - t0) * 1000, 1)
    t1 = _time.perf_counter()
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)
    if request is not None:
        request.state.timings["CompanyCheckMs"] = round((_time.perf_counter() - t1) * 1000, 1)
    t2 = _time.perf_counter()
    # Handle backward compatibility - set defaults for missing fields
    if not hasattr(invoice, 'status') or invoice.status is None:
        if hasattr(invoice, 'payment_status') and invoice.payment_status == 'PAID':
            invoice.status = 'PAID'
        elif invoice.items and len(invoice.items) > 0:
            invoice.status = 'BATCHED'
        else:
            invoice.status = 'DRAFT'
    
    if not hasattr(invoice, 'batched'):
        invoice.batched = invoice.status in ['BATCHED', 'PAID']
    if not hasattr(invoice, 'cashier_approved'):
        invoice.cashier_approved = invoice.status == 'PAID'
    
    # Use cached item_name/item_code if available; set unit_display_short (P/W/S) for print
    from app.models.inventory import InventoryLedger
    for invoice_item in invoice.items:
        if not hasattr(invoice_item, 'item_name') or not invoice_item.item_name:
            if invoice_item.item:
                invoice_item.item_name = invoice_item.item.name or ''
        if not hasattr(invoice_item, 'item_code') or not invoice_item.item_code:
            if invoice_item.item:
                invoice_item.item_code = invoice_item.item.sku or ''
        if invoice_item.item:
            invoice_item.unit_display_short = get_unit_display_short(
                invoice_item.item, invoice_item.unit_name or ''
            )
            # Base-unit cost for margin: batched/paid lines use ledger-reconciled unit_cost_used
            # (per retail); drafts use live FEFO cost from pricing service.
            if getattr(invoice, "status", None) in ("BATCHED", "PAID") and getattr(
                invoice_item, "unit_cost_used", None
            ) is not None and float(invoice_item.unit_cost_used or 0) > 0:
                invoice_item.unit_cost_base = Decimal(str(invoice_item.unit_cost_used))
            else:
                try:
                    invoice_item.unit_cost_base = PricingService.get_item_cost(
                        db, invoice_item.item_id, invoice.branch_id
                    )
                except Exception:
                    invoice_item.unit_cost_base = None
            if getattr(invoice_item, "unit_cost_base", None) is not None and float(invoice_item.unit_cost_base) > 0:
                mult = get_unit_multiplier_from_item(invoice_item.item, invoice_item.unit_name or "")
                if mult is not None and mult > 0:
                    cost_per_sale_unit = float(invoice_item.unit_cost_base) * float(mult)
                    price = float(invoice_item.unit_price_exclusive or 0)
                    if price > 0:
                        invoice_item.margin_percent = (Decimal(str(price)) - Decimal(str(cost_per_sale_unit))) / Decimal(str(price)) * Decimal("100")
    if request is not None:
        request.state.timings["CostEnrichMs"] = round((_time.perf_counter() - t2) * 1000, 1)
    t3 = _time.perf_counter()
    for invoice_item in invoice.items:
        # Batch/expiry for receipt/PDF (from ledger when batched); build full batch_allocations for multi-batch FEFO
        sale_ledgers = db.query(InventoryLedger).filter(
            InventoryLedger.reference_type == "sales_invoice",
            InventoryLedger.reference_id == invoice.id,
            InventoryLedger.item_id == invoice_item.item_id,
            InventoryLedger.transaction_type == "SALE",
            InventoryLedger.quantity_delta < 0,
        ).order_by(InventoryLedger.created_at.asc()).all()
        if sale_ledgers:
            invoice_item.batch_allocations = [
                {
                    "batch_number": getattr(led, "batch_number", None),
                    "expiry_date": led.expiry_date.isoformat() if getattr(led, "expiry_date", None) else None,
                    "quantity": abs(float(led.quantity_delta)),
                }
                for led in sale_ledgers
            ]
            first_ledger = sale_ledgers[0]
            invoice_item.batch_number = getattr(first_ledger, "batch_number", None)
            invoice_item.expiry_date = (
                first_ledger.expiry_date.isoformat() if getattr(first_ledger, "expiry_date", None) else None
            )
        else:
            invoice_item.batch_allocations = None
            if getattr(invoice_item, "batch_id", None):
                ledger = db.query(InventoryLedger).filter(InventoryLedger.id == invoice_item.batch_id).first()
                if ledger:
                    invoice_item.batch_number = ledger.batch_number
                    invoice_item.expiry_date = (
                        ledger.expiry_date.isoformat() if getattr(ledger, "expiry_date", None) else None
                    )
                else:
                    invoice_item.batch_number = None
                    invoice_item.expiry_date = None
            else:
                invoice_item.batch_number = None
                invoice_item.expiry_date = None

    if request is not None:
        request.state.timings["LedgerMs"] = round((_time.perf_counter() - t3) * 1000, 1)
    t4 = _time.perf_counter()
    # Print letterhead: company, branch, user, logo URL for print (all documents)
    company = db.query(Company).filter(Company.id == invoice.company_id).first()
    if company:
        invoice.company_name = company.name
        invoice.company_address = getattr(company, "address", None) or ""
        logo_path = getattr(company, "logo_url", None)
        if logo_path and str(logo_path).strip():
            if str(logo_path).startswith("tenant-assets/") and tenant is not None:
                invoice.logo_url = get_signed_url(logo_path, tenant=tenant)
            elif str(logo_path).startswith("http://") or str(logo_path).startswith("https://"):
                invoice.logo_url = str(logo_path).strip()
    branch = db.query(Branch).filter(Branch.id == invoice.branch_id).first()
    if branch:
        invoice.branch_name = branch.name
        invoice.branch_address = getattr(branch, "address", None) or ""
        invoice.branch_phone = getattr(branch, "phone", None) or ""
    creator = db.query(User).filter(User.id == invoice.created_by).first()
    if creator:
        invoice.created_by_username = creator.username or getattr(creator, "full_name", None) or ""

    if request is not None:
        request.state.timings["BuildMs"] = round((_time.perf_counter() - t4) * 1000, 1)
        request.state.timings["TotalMs"] = round((_time.perf_counter() - t0) * 1000, 1)
    return invoice


@router.get("/invoice/{invoice_id}", response_model=SalesInvoiceResponse)
def get_sales_invoice(
    invoice_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Optional[Tenant] = Depends(get_tenant_optional),
    db: Session = Depends(get_tenant_db),
):
    """Get sales invoice by ID with full item details. Works without tenant (no tenant-assets logo URL)."""
    user = current_user_and_db[0]
    return _get_sales_invoice_response(invoice_id, db, user, request=request, tenant=tenant)


@router.post("/invoice/{invoice_id}/items", response_model=SalesInvoiceResponse)
def add_sales_invoice_item(
    invoice_id: UUID,
    item_data: SalesInvoiceItemCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Optional[Tenant] = Depends(get_tenant_optional),
    db: Session = Depends(get_tenant_db),
):
    """
    Add one line item to an existing DRAFT invoice. Auto-save.
    Returns 400 "Item already exists in this invoice" if that item is already on the invoice.
    O(1) w.r.t. line count; single load with joinedload/selectinload.
    """
    from sqlalchemy.orm import selectinload, joinedload
    from sqlalchemy.exc import IntegrityError

    t0 = time.perf_counter()
    request.state.timings = {}
    user = current_user_and_db[0]
    invoice = (
        db.query(SalesInvoice)
        .options(
            joinedload(SalesInvoice.company),
            joinedload(SalesInvoice.branch),
            joinedload(SalesInvoice.creator),
            selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item),
        )
        .filter(SalesInvoice.id == invoice_id)
        .first()
    )
    request.state.timings["LoadMs"] = round((time.perf_counter() - t0) * 1000, 1)
    t1 = time.perf_counter()
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)
    request.state.timings["CompanyCheckMs"] = round((time.perf_counter() - t1) * 1000, 1)
    t2 = time.perf_counter()
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot add items to invoice with status {invoice.status}. Only DRAFT invoices can be edited."
        )
    # Reject if this item already exists on the invoice (one line per item per invoice)
    for line in invoice.items:
        if line.item_id == item_data.item_id:
            raise HTTPException(
                status_code=400,
                detail="Item already exists in this invoice. Edit the existing line or remove it first."
            )

    item = db.query(Item).filter(Item.id == item_data.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
    if not getattr(item, "setup_complete", True):
        raise HTTPException(
            status_code=400,
            detail=f"Item '{item.name}' is not ready for transactions. Complete item setup (pack size, units) in Items before adding to a sale."
        )

    item_vat_rate = Decimal(str(vat_rate_to_percent(item.vat_rate)))
    is_available, available, required = InventoryService.check_stock_availability(
        db, item_data.item_id, invoice.branch_id,
        float(item_data.quantity), item_data.unit_name
    )
    if not is_available:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock for {item.name}. Available: {available}, Required: {required}"
        )

    sales_type = getattr(invoice, 'sales_type', 'RETAIL') or 'RETAIL'
    pricing_tier = 'wholesale' if sales_type == 'WHOLESALE' else ('supplier' if sales_type == 'SUPPLIER' else 'retail')
    unit_price = item_data.unit_price_exclusive
    unit_cost_used = None
    if not unit_price:
        price_info = PricingService.calculate_recommended_price(
            db, item_data.item_id, invoice.branch_id,
            invoice.company_id, item_data.unit_name, tier=pricing_tier
        )
        if not price_info and pricing_tier == 'supplier':
            price_info = PricingService.calculate_recommended_price(
                db, item_data.item_id, invoice.branch_id,
                invoice.company_id, item_data.unit_name, tier='wholesale'
            )
        if price_info:
            unit_price = price_info["recommended_unit_price"]
            unit_cost_used = price_info["unit_cost_used"]
        else:
            raise HTTPException(status_code=400, detail=f"Price not available for {item.name}")
    else:
        cost_info = PricingService.get_item_cost(db, item_data.item_id, invoice.branch_id)
        if cost_info:
            unit_cost_used = cost_info
        # Price validation (floor + margin + promo)
        if unit_cost_used and float(unit_cost_used) > 0:
            mult = get_unit_multiplier_from_item(item, item_data.unit_name)
            if mult is not None and mult > 0:
                cost_per_sale_unit = unit_cost_used * mult
                unit_price_val = Decimal(str(unit_price))
                if cost_per_sale_unit > 0:
                    user_has_override = _user_has_sell_below_min_margin(db, invoice.created_by, invoice.branch_id)
                    is_promo = is_line_price_at_promo(
                        db, item_data.item_id, item_data.unit_name or "", unit_price_val
                    )
                    validation = validate_line_price(
                        db,
                        invoice.company_id,
                        item_data.item_id,
                        unit_price_val,
                        cost_per_sale_unit,
                        user_has_override,
                        branch_id=invoice.branch_id,
                        is_promo_price=is_promo,
                    )
                    if not validation.get("allowed"):
                        raise HTTPException(
                            status_code=400,
                            detail=validation.get("message", "Price validation failed.")
                        )

    line_total_exclusive = Decimal(str(unit_price)) * item_data.quantity
    discount_amount = item_data.discount_amount or (line_total_exclusive * item_data.discount_percent / Decimal("100"))
    line_total_exclusive -= discount_amount
    line_vat = line_total_exclusive * item_vat_rate / Decimal("100")
    line_total_inclusive = line_total_exclusive + line_vat

    new_line = SalesInvoiceItem(
        sales_invoice_id=invoice_id,
        item_id=item_data.item_id,
        batch_id=None,
        unit_name=item_data.unit_name,
        quantity=item_data.quantity,
        unit_price_exclusive=unit_price,
        discount_percent=item_data.discount_percent,
        discount_amount=discount_amount,
        vat_rate=item_vat_rate,
        vat_amount=line_vat,
        line_total_exclusive=line_total_exclusive,
        line_total_inclusive=line_total_inclusive,
        unit_cost_used=unit_cost_used,
        item_name=item.name,
        item_code=item.sku or "",
    )
    db.add(new_line)
    db.flush()

    # Recalculate invoice totals
    total_exclusive = invoice.total_exclusive + line_total_exclusive
    total_vat = invoice.vat_amount + line_vat
    total_inclusive = total_exclusive + total_vat
    invoice.total_exclusive = total_exclusive
    invoice.vat_amount = total_vat
    invoice.total_inclusive = total_inclusive
    if total_exclusive > 0:
        invoice.vat_rate = (total_vat / total_exclusive * Decimal("100"))

    request.state.timings["InsertMs"] = round((time.perf_counter() - t2) * 1000, 1)
    t3 = time.perf_counter()

    try:
        # Build response: use already-loaded inv_item.item (selectinload) for existing lines; single `item` for the new line. O(1).
        for inv_item in invoice.items:
            it = inv_item.item if inv_item.item_id != item_data.item_id else item
            if it:
                inv_item.item = it
                if not getattr(inv_item, "item_name", None):
                    inv_item.item_name = it.name or ""
                if not getattr(inv_item, "item_code", None):
                    inv_item.item_code = it.sku or ""
                inv_item.unit_display_short = get_unit_display_short(it, inv_item.unit_name or "")
            if inv_item.item_id == item_data.item_id:
                # Carry cost/margin from client when provided (item search + user price); margin validated at batch
                if getattr(item_data, "unit_cost_base", None) is not None:
                    inv_item.unit_cost_base = Decimal(str(item_data.unit_cost_base))
                    # unit_cost_used stored as cost per retail (same as unit_cost_base) for COGS consistency
                    if it:
                        inv_item.unit_cost_used = inv_item.unit_cost_base
                        mult = get_unit_multiplier_from_item(it, inv_item.unit_name or "")
                    if getattr(item_data, "margin_percent", None) is not None:
                        inv_item.margin_percent = Decimal(str(item_data.margin_percent))
                    elif it:
                        mult = get_unit_multiplier_from_item(it, inv_item.unit_name or "")
                        if mult is not None and mult > 0:
                            cost_per_sale_unit = float(inv_item.unit_cost_base) * float(mult)
                            price = float(inv_item.unit_price_exclusive or 0)
                            if price > 0:
                                inv_item.margin_percent = (Decimal(str(price)) - Decimal(str(cost_per_sale_unit))) / Decimal(str(price)) * Decimal("100")
                else:
                    try:
                        inv_item.unit_cost_base = PricingService.get_item_cost_from_snapshot(db, inv_item.item_id, invoice.branch_id, invoice.company_id)
                        if inv_item.unit_cost_base is None:
                            inv_item.unit_cost_base = PricingService.get_item_cost(db, inv_item.item_id, invoice.branch_id, use_fefo=True)
                    except Exception:
                        inv_item.unit_cost_base = None
                if getattr(inv_item, "unit_cost_base", None) is not None and float(inv_item.unit_cost_base) > 0 and it:
                    mult = get_unit_multiplier_from_item(it, inv_item.unit_name or "")
                    if mult is not None and mult > 0:
                        cost_per_sale_unit = float(inv_item.unit_cost_base) * float(mult)
                        price = float(inv_item.unit_price_exclusive or 0)
                        if price > 0:
                            inv_item.margin_percent = (Decimal(str(price)) - Decimal(str(cost_per_sale_unit))) / Decimal(str(price)) * Decimal("100")
            inv_item.batch_allocations = None
            inv_item.batch_number = None
            inv_item.expiry_date = None
        request.state.timings["CostMs"] = round((time.perf_counter() - t3) * 1000, 1)
        t4 = time.perf_counter()
        if not getattr(invoice, "status", None):
            invoice.status = "DRAFT"
        if not hasattr(invoice, "batched"):
            invoice.batched = invoice.status in ["BATCHED", "PAID"]
        if not hasattr(invoice, "cashier_approved"):
            invoice.cashier_approved = invoice.status == "PAID"
        # Use eagerly loaded company, branch, creator (no extra queries)
        if invoice.company:
            invoice.company_name = invoice.company.name
            invoice.company_address = getattr(invoice.company, "address", None) or ""
            logo_path = getattr(invoice.company, "logo_url", None)
            if logo_path and str(logo_path).strip():
                if str(logo_path).startswith("tenant-assets/") and tenant is not None:
                    invoice.logo_url = get_signed_url(logo_path, tenant=tenant)
                elif str(logo_path).startswith("http://") or str(logo_path).startswith("https://"):
                    invoice.logo_url = str(logo_path).strip()
        if invoice.branch:
            invoice.branch_name = invoice.branch.name
            invoice.branch_address = getattr(invoice.branch, "address", None) or ""
            invoice.branch_phone = getattr(invoice.branch, "phone", None) or ""
        if invoice.creator:
            invoice.created_by_username = invoice.creator.username or getattr(invoice.creator, "full_name", None) or ""

        request.state.timings["BuildMs"] = round((time.perf_counter() - t4) * 1000, 1)
        request.state.timings["TotalMs"] = round((time.perf_counter() - t0) * 1000, 1)
        t5 = time.perf_counter()
        db.commit()
        request.state.timings["CommitMs"] = round((time.perf_counter() - t5) * 1000, 1)
        return invoice
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Item already exists in this invoice. Edit the existing line or remove it first."
        )


@router.delete("/invoice/{invoice_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_invoice_item(
    invoice_id: UUID,
    item_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Remove one line item from a DRAFT invoice. Only DRAFT invoices can be edited.
    """
    from sqlalchemy.orm import selectinload
    invoice = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items))
        .filter(SalesInvoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot remove items from invoice with status {invoice.status}. Only DRAFT invoices can be edited.",
        )
    line = next((i for i in invoice.items if i.item_id == item_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Item not found on this invoice")
    # Subtract this line's totals from invoice before deleting
    invoice.total_exclusive -= line.line_total_exclusive
    invoice.vat_amount -= line.vat_amount
    invoice.total_inclusive -= line.line_total_inclusive
    if invoice.total_exclusive and invoice.total_exclusive > 0:
        invoice.vat_rate = (invoice.vat_amount / invoice.total_exclusive * Decimal("100"))
    else:
        invoice.vat_rate = Decimal("0")
    db.delete(line)
    db.commit()
    return None


@router.patch("/invoice/{invoice_id}/items/{item_id}", response_model=SalesInvoiceResponse)
def update_sales_invoice_item(
    invoice_id: UUID,
    item_id: UUID,
    payload: SalesInvoiceItemUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Update one line item on a DRAFT invoice (quantity, unit, price, discount).
    Recalculates line and invoice totals. Only DRAFT invoices can be edited.
    """
    from sqlalchemy.orm import selectinload

    invoice = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items))
        .filter(SalesInvoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit items on invoice with status {invoice.status}. Only DRAFT invoices can be edited.",
        )
    line = next((i for i in invoice.items if i.item_id == item_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Item not found on this invoice")

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Apply updates (only non-None fields)
    if payload.quantity is not None:
        line.quantity = payload.quantity
    if payload.unit_name is not None:
        line.unit_name = payload.unit_name
    if payload.unit_price_exclusive is not None:
        line.unit_price_exclusive = payload.unit_price_exclusive
    if payload.discount_percent is not None:
        line.discount_percent = payload.discount_percent
    if payload.discount_amount is not None:
        line.discount_amount = payload.discount_amount

    # Stock check when quantity or unit changed
    qty = float(line.quantity)
    unit = line.unit_name or ""
    is_available, available, required = InventoryService.check_stock_availability(
        db, item_id, invoice.branch_id, qty, unit
    )
    if not is_available:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock for {item.name}. Available: {available}, Required: {required}"
        )

    # Recalculate line totals
    item_vat_rate = line.vat_rate
    line_total_exclusive = (line.unit_price_exclusive or Decimal("0")) * (line.quantity or Decimal("0"))
    disc = line.discount_amount or (line_total_exclusive * (line.discount_percent or 0) / Decimal("100"))
    line_total_exclusive -= disc
    line_vat = line_total_exclusive * item_vat_rate / Decimal("100")
    line_total_inclusive = line_total_exclusive + line_vat
    line.line_total_exclusive = line_total_exclusive
    line.vat_amount = line_vat
    line.line_total_inclusive = line_total_inclusive

    # Recalculate invoice totals from all lines
    total_exclusive = sum(l.line_total_exclusive for l in invoice.items)
    total_vat = sum(l.vat_amount for l in invoice.items)
    total_inclusive = total_exclusive + total_vat
    invoice.total_exclusive = total_exclusive
    invoice.vat_amount = total_vat
    invoice.total_inclusive = total_inclusive
    if total_exclusive > 0:
        invoice.vat_rate = total_vat / total_exclusive * Decimal("100")
    else:
        invoice.vat_rate = Decimal("0")

    db.commit()
    db.refresh(invoice)
    user = current_user_and_db[0]
    return _get_sales_invoice_response(invoice_id, db, user)


@router.get("/branch/{branch_id}/today-summary", response_model=dict)
def get_branch_today_summary(
    branch_id: UUID,
    user_id: Optional[UUID] = Query(None, description="Filter by user (batched_by) for per-user sales today"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get total sales for today for the branch. If user_id is provided, only sales batched by that user today."""
    today = date.today()
    q = db.query(
        func.coalesce(func.sum(SalesInvoice.total_inclusive), 0).label("total_inclusive"),
        func.coalesce(func.sum(SalesInvoice.total_exclusive), 0).label("total_exclusive"),
    ).filter(
        SalesInvoice.branch_id == branch_id,
        SalesInvoice.status.in_(["BATCHED", "PAID"]),
        func.date(func.coalesce(SalesInvoice.batched_at, SalesInvoice.created_at)) == today,
    )
    if user_id is not None:
        q = q.filter(SalesInvoice.batched_by == user_id)

    row = q.first()
    total_inclusive = row.total_inclusive if row else Decimal("0")
    total_exclusive = row.total_exclusive if row else Decimal("0")
    return {
        "total_inclusive": str(total_inclusive),
        "total_exclusive": str(total_exclusive),
    }


def _compute_cogs_from_invoice_lines(
    db: Session,
    branch_id: UUID,
    sd: date,
    ed: date,
    by_date: bool = False,
) -> tuple:
    """
    Compute COGS for gross profit.

    Primary: sum of InventoryLedger.total_cost for SALE rows created when invoices were
    batched (reference_type=sales_invoice). This is the *actual* cost removed from stock
    across all FEFO layers — not stock valuation / last-cost-for-display, and not the
    snapshot on sales_invoice_items.unit_cost_used (which is only the first batch's cost).

    Fallback (legacy / missing ledger): sum per line
        quantity (sale unit) × multiplier_to_retail × unit_cost_used (per retail/base)
    when unit_cost_used is set on the line.

    Returns (total_cogs, cogs_by_day_dict or None).
    """
    from sqlalchemy.orm import selectinload

    sales_date_key = func.date(func.coalesce(SalesInvoice.batched_at, SalesInvoice.created_at))

    # --- Ledger COGS: actual batching cost (multi-batch correct) ---
    ledger_total_raw = (
        db.query(func.coalesce(func.sum(InventoryLedger.total_cost), 0))
        .join(SalesInvoice, SalesInvoice.id == InventoryLedger.reference_id)
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.transaction_type == "SALE",
            InventoryLedger.reference_type == "sales_invoice",
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            sales_date_key.between(sd, ed),
        )
        .scalar()
    )
    ledger_total = Decimal(str(ledger_total_raw or 0))

    ledger_cogs_by_day = None
    if by_date:
        ledger_rows = (
            db.query(
                sales_date_key.label("d"),
                func.coalesce(func.sum(InventoryLedger.total_cost), 0).label("cogs"),
            )
            .join(SalesInvoice, SalesInvoice.id == InventoryLedger.reference_id)
            .filter(
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.transaction_type == "SALE",
                InventoryLedger.reference_type == "sales_invoice",
                SalesInvoice.branch_id == branch_id,
                SalesInvoice.status.in_(["BATCHED", "PAID"]),
                sales_date_key.between(sd, ed),
            )
            .group_by(sales_date_key)
            .all()
        )
        ledger_cogs_by_day = {r.d: (r.cogs or Decimal("0")) for r in (ledger_rows or [])}

    invoices = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
        .filter(
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            sales_date_key.between(sd, ed),
        )
        .all()
    )
    invoice_cogs = Decimal("0")
    invoice_cogs_by_day = {} if by_date else None

    for inv in invoices:
        inv_date = inv.batched_at or inv.created_at
        if inv_date is None:
            d = sd
        elif hasattr(inv_date, "date") and callable(getattr(inv_date, "date")):
            d = inv_date.date()
        elif isinstance(inv_date, date):
            d = inv_date
        else:
            from datetime import datetime as dt
            d = dt.fromisoformat(str(inv_date)[:10]).date() if inv_date else sd
        inv_line_cogs = Decimal("0")
        for line in inv.items or []:
            if not line.unit_cost_used or float(line.unit_cost_used) <= 0:
                continue
            item = line.item
            if not item:
                item = db.query(Item).filter(Item.id == line.item_id).first()
            if not item:
                continue
            
            # ARCHITECTURE: unit_cost_used is ALWAYS stored as cost per retail/base unit (ledger/snapshot).
            # COGS = quantity sold (in retail units) × cost per retail unit.
            # pack_size is not used for cost; it only affects quantity conversion (sale unit → retail).
            mult_to_retail = get_unit_multiplier_from_item(item, line.unit_name or "")
            if mult_to_retail is None or mult_to_retail <= 0:
                continue

            qty_retail = Decimal(str(line.quantity)) * mult_to_retail
            cost_per_retail = Decimal(str(line.unit_cost_used))
            line_cogs = qty_retail * cost_per_retail
            inv_line_cogs += line_cogs
        
        invoice_cogs += inv_line_cogs
        if by_date and inv_line_cogs > 0:
            invoice_cogs_by_day[d] = invoice_cogs_by_day.get(d, Decimal("0")) + inv_line_cogs

    # Prefer batched SALE ledger totals (multi-batch FEFO accurate). Invoice-line math uses
    # unit_cost_used from the first batch only and can over- or under-state COGS vs actual layers.
    if ledger_total > 0:
        return ledger_total, ledger_cogs_by_day if by_date else None
    return invoice_cogs, invoice_cogs_by_day


@router.get("/branch/{branch_id}/gross-profit", response_model=dict)
def get_branch_gross_profit(
    branch_id: UUID,
    preset: Optional[str] = Query(None, description="today | yesterday | this_week | last_week | this_month | last_month | this_year | last_year"),
    start_date: Optional[date] = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
    include_breakdown: bool = Query(False, description="If true, include per-day breakdown for the date range"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Gross profit summary for a branch and date range.

    Net sales = Sales (exclusive) − Credit notes (customer returns) in date range.
    COGS = sum of SALE ledger total_cost for batched invoices in range (actual FEFO cost);
           if no ledger rows (legacy), falls back to invoice-line qty × unit_cost_used.
           Then subtract SALE_RETURN ledger total_cost linked to credit notes in range.
    Gross profit = Net sales − COGS.
    """
    sd, ed = _resolve_date_range(preset, start_date, end_date)

    sales_date_key = func.date(func.coalesce(SalesInvoice.batched_at, SalesInvoice.created_at))
    base_sales = (
        db.query(
            func.coalesce(func.sum(SalesInvoice.total_exclusive), 0).label("sales_exclusive"),
            func.count(SalesInvoice.id).label("invoice_count"),
        )
        .filter(
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            sales_date_key.between(sd, ed),
        )
        .first()
    )
    sales_exclusive = (base_sales.sales_exclusive if base_sales else Decimal("0")) or Decimal("0")
    invoice_count = int(getattr(base_sales, "invoice_count", 0) or 0)

    # Net sales: subtract credit notes (customer returns) in date range
    credit_notes_sum = (
        db.query(func.coalesce(func.sum(CreditNote.total_exclusive), 0).label("cn_total"))
        .filter(
            CreditNote.branch_id == branch_id,
            CreditNote.credit_note_date >= sd,
            CreditNote.credit_note_date <= ed,
        )
        .scalar()
    )
    credit_notes_total = Decimal(str(credit_notes_sum or 0))
    net_sales_exclusive = sales_exclusive - credit_notes_total

    # COGS from invoice lines (cost of quantity SOLD)
    cogs, cogs_by_day = _compute_cogs_from_invoice_lines(
        db, branch_id, sd, ed, by_date=include_breakdown
    )

    # Subtract SALE_RETURN cost (customer returns reduce COGS)
    cn_ids_subq = (
        db.query(CreditNote.id)
        .filter(
            CreditNote.branch_id == branch_id,
            CreditNote.credit_note_date >= sd,
            CreditNote.credit_note_date <= ed,
        )
    )
    return_cogs_result = (
        db.query(func.coalesce(func.sum(InventoryLedger.total_cost), 0).label("return_cogs"))
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.transaction_type == "SALE_RETURN",
            InventoryLedger.reference_type == "credit_note",
            InventoryLedger.reference_id.in_(cn_ids_subq),
        )
        .scalar()
    )
    return_cogs = Decimal(str(return_cogs_result or 0))
    cogs = cogs - return_cogs

    if include_breakdown and return_cogs > 0:
        return_cogs_rows = (
            db.query(
                func.date(InventoryLedger.created_at).label("d"),
                func.coalesce(func.sum(InventoryLedger.total_cost), 0).label("rc"),
            )
            .filter(
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.transaction_type == "SALE_RETURN",
                InventoryLedger.reference_type == "credit_note",
                InventoryLedger.reference_id.in_(cn_ids_subq),
            )
            .group_by(func.date(InventoryLedger.created_at))
            .all()
        )
        return_cogs_by_day = {r.d: (r.rc or Decimal("0")) for r in (return_cogs_rows or [])}
        if cogs_by_day:
            for d in list(cogs_by_day.keys()):
                cogs_by_day[d] = cogs_by_day[d] - return_cogs_by_day.get(d, Decimal("0"))

    gross_profit = net_sales_exclusive - cogs
    margin_percent = (gross_profit / net_sales_exclusive * Decimal("100")) if net_sales_exclusive and net_sales_exclusive > 0 else Decimal("0")

    out = {
        "start_date": sd.isoformat(),
        "end_date": ed.isoformat(),
        "sales_exclusive": str(sales_exclusive),
        "credit_notes_exclusive": str(credit_notes_total),
        "net_sales_exclusive": str(net_sales_exclusive),
        "cogs": str(cogs),
        "gross_profit": str(gross_profit),
        "margin_percent": str(margin_percent),
        "invoice_count": invoice_count,
    }

    if not include_breakdown:
        return out

    # Per-day breakdown: sales, credit notes, net sales, cogs, gross profit
    sales_rows = (
        db.query(
            sales_date_key.label("d"),
            func.coalesce(func.sum(SalesInvoice.total_exclusive), 0).label("sales_exclusive"),
        )
        .filter(
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            sales_date_key.between(sd, ed),
        )
        .group_by(sales_date_key)
        .order_by(sales_date_key.asc())
        .all()
    )
    sales_by_day = {r.d: (r.sales_exclusive or Decimal("0")) for r in (sales_rows or [])}

    cn_rows = (
        db.query(
            CreditNote.credit_note_date.label("d"),
            func.coalesce(func.sum(CreditNote.total_exclusive), 0).label("cn_total"),
        )
        .filter(
            CreditNote.branch_id == branch_id,
            CreditNote.credit_note_date >= sd,
            CreditNote.credit_note_date <= ed,
        )
        .group_by(CreditNote.credit_note_date)
        .all()
    )
    credit_notes_by_day = {r.d: (r.cn_total or Decimal("0")) for r in (cn_rows or [])}
    cogs_by_day = cogs_by_day or {}

    breakdown = []
    dcur = sd
    while dcur <= ed:
        s = sales_by_day.get(dcur, Decimal("0"))
        cn = credit_notes_by_day.get(dcur, Decimal("0"))
        net_s = s - cn
        c = cogs_by_day.get(dcur, Decimal("0"))
        gp = net_s - c
        mp = (gp / net_s * Decimal("100")) if net_s and net_s > 0 else Decimal("0")
        breakdown.append(
            {
                "date": dcur.isoformat(),
                "sales_exclusive": str(s),
                "credit_notes_exclusive": str(cn),
                "net_sales_exclusive": str(net_s),
                "cogs": str(c),
                "gross_profit": str(gp),
                "margin_percent": str(mp),
            }
        )
        dcur = dcur + timedelta(days=1)

    out["breakdown"] = breakdown
    return out


@router.get("/branch/{branch_id}/invoices", response_model=List[SalesInvoiceResponse])
def get_branch_invoices(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    date_from: Optional[date] = Query(None, description="Filter from this date (for returns: use with date_to)"),
    date_to: Optional[date] = Query(None, description="Filter to this date"),
    invoice_no: Optional[str] = Query(None, description="Exact invoice number lookup (targeted search)"),
    limit: int = Query(50, ge=1, le=100, description="Max results (default 50 for return flow)"),
):
    """
    Get invoices for a branch with scoped queries only (no full-history load).
    - No params: returns today's invoices only (limit 50).
    - invoice_no: targeted lookup by number (optional date_from/date_to); limit 1.
    - date_from/date_to: filter by invoice_date; limit applied.
    """
    from sqlalchemy.orm import selectinload

    query = db.query(SalesInvoice).options(
        selectinload(SalesInvoice.items)
    ).filter(SalesInvoice.branch_id == branch_id)

    if invoice_no is not None and str(invoice_no).strip():
        # Targeted search by document number
        query = query.filter(SalesInvoice.invoice_no == str(invoice_no).strip())
        if date_from is not None:
            query = query.filter(SalesInvoice.invoice_date >= date_from)
        if date_to is not None:
            query = query.filter(SalesInvoice.invoice_date <= date_to)
        query = query.order_by(SalesInvoice.created_at.desc()).limit(1)
    else:
        # Date-scoped list (default: today only)
        if date_from is not None:
            query = query.filter(SalesInvoice.invoice_date >= date_from)
        if date_to is not None:
            query = query.filter(SalesInvoice.invoice_date <= date_to)
        if date_from is None and date_to is None:
            # Default: today's documents only
            today = date.today()
            query = query.filter(
                func.date(SalesInvoice.created_at) == today
            )
        query = query.order_by(
            SalesInvoice.invoice_date.desc(),
            SalesInvoice.created_at.desc(),
            SalesInvoice.invoice_no.desc(),
        ).limit(limit)

    try:
        invoices = query.all()
    except Exception as e:
        error_str = str(e)
        # Check if it's a missing column error
        if 'column' in error_str.lower() and ('does not exist' in error_str.lower() or 'unknown' in error_str.lower() or 'undefinedcolumn' in error_str.lower()):
            missing_column = None
            # Try to extract column name from error
            if 'customer_phone' in error_str:
                missing_column = 'customer_phone'
            elif 'status' in error_str:
                missing_column = 'status'
            elif 'batched' in error_str:
                missing_column = 'batched'
            
            detail_msg = f"Database migration required. Please run: database/add_sales_invoice_status_and_payments.sql. "
            if missing_column:
                detail_msg += f"The sales_invoices table is missing the '{missing_column}' column. "
            else:
                detail_msg += "The sales_invoices table is missing new columns. "
            detail_msg += f"Error: {error_str}"
            
            raise HTTPException(
                status_code=500,
                detail=detail_msg
            )
        # Re-raise other errors
        raise
    
    # Handle backward compatibility - set defaults for missing fields
    for invoice in invoices:
        # If status is None, infer from payment_status
        status = getattr(invoice, 'status', None)
        if status is None:
            payment_status = getattr(invoice, 'payment_status', 'PAID')
            if payment_status == 'PAID':
                invoice.status = 'PAID'
            elif hasattr(invoice, 'items') and invoice.items and len(invoice.items) > 0:
                invoice.status = 'BATCHED'
            else:
                invoice.status = 'DRAFT'
        
        # Set defaults for other new fields if None
        if getattr(invoice, 'batched', None) is None:
            invoice.batched = invoice.status in ['BATCHED', 'PAID']
        if getattr(invoice, 'cashier_approved', None) is None:
            invoice.cashier_approved = invoice.status == 'PAID'
    
    return invoices


# ---------- Credit Notes (Customer Returns) ----------

@router.post("/credit-notes", response_model=CreditNoteResponse, status_code=status.HTTP_201_CREATED)
def create_credit_note(
    body: CreditNoteCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create a credit note (customer return) against a batched/paid invoice.
    Validates return_qty <= sold_qty - already_returned_qty per line.
    Creates SALE_RETURN ledger entries with original batch and cost; updates snapshot in one transaction.
    """
    from sqlalchemy.orm import selectinload

    user = current_user_and_db[0]

    # Lock invoice and load relations
    invoice = (
        db.query(SalesInvoice)
        .options(
            selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item),
            selectinload(SalesInvoice.credit_notes).selectinload(CreditNote.items),
        )
        .filter(SalesInvoice.id == body.original_invoice_id)
        .with_for_update()
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Original invoice not found")
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)
    if invoice.company_id != body.company_id or invoice.branch_id != body.branch_id:
        raise HTTPException(status_code=400, detail="Invoice must belong to the same company and branch")
    if invoice.status not in ("BATCHED", "PAID"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create return for invoice with status {invoice.status}. Invoice must be BATCHED or PAID.",
        )

    # Build map: original_sale_item_id -> (sale line, sold_qty_base, already_returned_base)
    sale_line_by_id = {str(line.id): line for line in invoice.items}
    already_returned_base = {}
    for cn in invoice.credit_notes or []:
        for cn_item in cn.items or []:
            if cn_item.original_sale_item_id:
                key = str(cn_item.original_sale_item_id)
                if key not in already_returned_base:
                    already_returned_base[key] = Decimal("0")
                orig_line = sale_line_by_id.get(key)
                mult = get_unit_multiplier_from_item(orig_line.item, cn_item.unit_name or "") if orig_line and orig_line.item else Decimal("1")
                if mult is None:
                    mult = Decimal("1")
                already_returned_base[key] += (Decimal(str(cn_item.quantity_returned)) * Decimal(str(mult)))

    for line in invoice.items:
        key = str(line.id)
        if key not in already_returned_base:
            already_returned_base[key] = Decimal("0")
        mult = get_unit_multiplier_from_item(line.item, line.unit_name or "")
        if mult is None:
            mult = Decimal("1")
        sale_qty_base = Decimal(str(line.quantity)) * Decimal(str(mult))
        line._sale_qty_base = sale_qty_base
        line._already_returned_base = already_returned_base[key]

    # Validate each request line and resolve original line
    invoice_item_by_id = {str(it.id): it for it in invoice.items}
    for req_item in body.items:
        if not req_item.original_sale_item_id:
            raise HTTPException(status_code=400, detail="Each credit note line must have original_sale_item_id")
        orig = invoice_item_by_id.get(str(req_item.original_sale_item_id))
        if not orig:
            raise HTTPException(status_code=400, detail=f"Original sale item {req_item.original_sale_item_id} not found on invoice")
        if orig.item_id != req_item.item_id:
            raise HTTPException(status_code=400, detail="item_id must match the original invoice line")
        mult = get_unit_multiplier_from_item(orig.item, req_item.unit_name or orig.unit_name or "")
        if mult is None:
            mult = Decimal("1")
        return_qty_base = Decimal(str(req_item.quantity_returned)) * Decimal(str(mult))
        allowed = getattr(orig, "_sale_qty_base", Decimal("0")) - getattr(orig, "_already_returned_base", Decimal("0"))
        if return_qty_base <= 0:
            raise HTTPException(status_code=400, detail=f"quantity_returned must be positive for item {req_item.item_id}")
        if return_qty_base > allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Return quantity exceeds remaining quantity for item (sold minus already returned). Item id: {req_item.item_id}",
            )

    credit_note_no = DocumentService.get_credit_note_number(db, body.company_id, body.branch_id)
    vat_rate_pct = Decimal("16")
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")

    credit_note = CreditNote(
        company_id=body.company_id,
        branch_id=body.branch_id,
        credit_note_no=credit_note_no,
        original_invoice_id=body.original_invoice_id,
        credit_note_date=body.credit_note_date,
        reason=body.reason,
        created_by=body.created_by,
    )
    db.add(credit_note)
    db.flush()

    ledger_entries = []
    for req_item in body.items:
        orig = invoice_item_by_id[str(req_item.original_sale_item_id)]
        mult = get_unit_multiplier_from_item(orig.item, req_item.unit_name or orig.unit_name or "")
        if mult is None:
            mult = Decimal("1")
        return_qty_base = Decimal(str(req_item.quantity_returned)) * Decimal(str(mult))
        unit_cost = orig.unit_cost_used if orig.unit_cost_used is not None else Decimal("0")
        # Derive the effective unit price EXCLUSIVE from the original invoice line net amount
        # (line_total_exclusive already includes item-level discount), then convert to the
        # requested unit. This prevents "packet returns priced like retail" issues when
        # the frontend unit_price doesn't match the unit conversion rules.
        orig_unit_name = orig.unit_name or ""
        req_unit_name = req_item.unit_name or orig_unit_name
        orig_mult = get_unit_multiplier_from_item(orig.item, orig_unit_name)
        req_mult = get_unit_multiplier_from_item(orig.item, req_unit_name)

        effective_unit_price_exclusive = None
        try:
            orig_qty = Decimal(str(orig.quantity or 0))
            orig_line_total_excl = Decimal(str(orig.line_total_exclusive or 0))
            if orig_qty > 0 and orig_mult is not None and req_mult is not None and orig_mult > 0:
                # orig_effective_unit_excl is per orig unit; convert -> base (retail) -> req unit
                orig_effective_unit_excl = orig_line_total_excl / orig_qty
                base_unit_price_excl = orig_effective_unit_excl / orig_mult
                effective_unit_price_exclusive = base_unit_price_excl * req_mult
        except Exception:
            effective_unit_price_exclusive = None

        if effective_unit_price_exclusive is None:
            effective_unit_price_exclusive = Decimal(str(req_item.unit_price_exclusive or 0))

        line_excl = effective_unit_price_exclusive * Decimal(str(req_item.quantity_returned))
        line_vat = line_excl * vat_rate_pct / Decimal("100")
        line_inc = line_excl + line_vat
        total_exclusive += line_excl
        total_vat += line_vat

        batch_number = None
        expiry_date = None
        if orig.batch_id:
            led = db.query(InventoryLedger).filter(InventoryLedger.id == orig.batch_id).first()
            if led:
                batch_number = led.batch_number
                expiry_date = led.expiry_date

        cn_item = CreditNoteItem(
            credit_note_id=credit_note.id,
            item_id=req_item.item_id,
            original_sale_item_id=orig.id,
            batch_id=orig.batch_id,
            unit_name=req_item.unit_name,
            quantity_returned=req_item.quantity_returned,
            unit_price_exclusive=effective_unit_price_exclusive,
            vat_rate=vat_rate_pct,
            vat_amount=line_vat,
            line_total_exclusive=line_excl,
            line_total_inclusive=line_inc,
        )
        db.add(cn_item)
        db.flush()

        ledger_entry = InventoryLedger(
            company_id=credit_note.company_id,
            branch_id=credit_note.branch_id,
            item_id=req_item.item_id,
            batch_number=batch_number,
            expiry_date=expiry_date,
            transaction_type="SALE_RETURN",
            reference_type="credit_note",
            reference_id=credit_note.id,
            document_number=credit_note_no,
            quantity_delta=return_qty_base,
            unit_cost=unit_cost,
            total_cost=unit_cost * return_qty_base,
            created_by=body.created_by,
        )
        ledger_entries.append(ledger_entry)

    credit_note.total_exclusive = total_exclusive
    credit_note.vat_rate = vat_rate_pct
    credit_note.vat_amount = total_vat
    credit_note.total_inclusive = total_exclusive + total_vat
    db.flush()

    for entry in ledger_entries:
        db.add(entry)
    db.flush()
    for entry in ledger_entries:
        SnapshotService.upsert_inventory_balance(
            db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta,
            document_number=getattr(entry, "document_number", None) or credit_note_no,
        )
    for entry in ledger_entries:
        SnapshotRefreshService.schedule_snapshot_refresh(db, entry.company_id, entry.branch_id, item_id=entry.item_id)

    try:
        db.commit()
        db.refresh(credit_note)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Credit note creation failed: {str(e)}")

    return credit_note


@router.get("/branch/{branch_id}/credit-notes", response_model=List[CreditNoteResponse])
def get_branch_credit_notes(
    branch_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List credit notes for a branch with optional date filter."""
    from sqlalchemy.orm import selectinload

    user = current_user_and_db[0]
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    require_document_belongs_to_user_company(db, user, branch, "Branch", request)
    q = (
        db.query(CreditNote)
        .options(selectinload(CreditNote.items))
        .filter(CreditNote.branch_id == branch_id)
    )
    if date_from is not None:
        q = q.filter(CreditNote.credit_note_date >= date_from)
    if date_to is not None:
        q = q.filter(CreditNote.credit_note_date <= date_to)
    q = q.order_by(CreditNote.credit_note_date.desc(), CreditNote.created_at.desc())
    notes = q.offset(offset).limit(limit).all()
    return notes


@router.put("/invoice/{invoice_id}", response_model=SalesInvoiceResponse)
def update_sales_invoice(
    invoice_id: UUID,
    invoice_update: SalesInvoiceUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Update sales invoice (only if status is DRAFT)
    
    Only DRAFT invoices can be updated. BATCHED invoices cannot be updated.
    """
    db_invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not db_invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if db_invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update invoice with status {db_invoice.status}. Only DRAFT invoices can be updated."
        )
    
    # Determine final payment_mode (use update value if provided, otherwise keep existing)
    final_payment_mode = invoice_update.payment_mode if invoice_update.payment_mode is not None else db_invoice.payment_mode
    
    # Validate credit payment mode requirements
    if final_payment_mode == 'credit':
        # Check if customer_name and customer_phone are provided
        customer_name = invoice_update.customer_name if invoice_update.customer_name is not None else db_invoice.customer_name
        customer_phone = invoice_update.customer_phone if invoice_update.customer_phone is not None else db_invoice.customer_phone
        
        if not customer_name or not customer_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Customer name is required when payment mode is 'credit'"
            )
        if not customer_phone or not customer_phone.strip():
            raise HTTPException(
                status_code=400,
                detail="Customer phone number is required when payment mode is 'credit'"
            )
        # Basic phone validation
        import re
        phone_digits = re.sub(r'\D', '', customer_phone)
        if len(phone_digits) < 9:
            raise HTTPException(
                status_code=400,
                detail="Customer phone number must be a valid phone number (at least 9 digits)"
            )
    
    # Update allowed fields
    if invoice_update.customer_name is not None:
        db_invoice.customer_name = invoice_update.customer_name
    if invoice_update.customer_pin is not None:
        db_invoice.customer_pin = invoice_update.customer_pin
    # Only update customer_phone if column exists (backward compatibility)
    if hasattr(SalesInvoice, 'customer_phone') and invoice_update.customer_phone is not None:
        db_invoice.customer_phone = invoice_update.customer_phone
    if invoice_update.payment_mode is not None:
        db_invoice.payment_mode = invoice_update.payment_mode
    if invoice_update.payment_status is not None:
        db_invoice.payment_status = invoice_update.payment_status
    
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.post("/invoice/{invoice_id}/batch", response_model=SalesInvoiceResponse)
def batch_sales_invoice(
    invoice_id: UUID,
    batched_by: UUID,
    request: Request,
    body: Optional[BatchSalesInvoiceRequest] = None,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Batch Sales Invoice - Reduce Stock from Inventory

    Single transaction with row-level lock on the invoice to prevent double-batch and race conditions.
    If body.items is provided, draft line items are updated to match (quantity, unit_name, unit_price, etc.)
    so the batched invoice matches the frontend. Then validates stock, deducts stock, sets BATCHED, and commits.
    """
    from sqlalchemy.orm import selectinload
    from datetime import datetime

    user = current_user_and_db[0]
    # Lock invoice row for update so concurrent batch requests for same invoice are serialized; eager-load items.item to avoid N+1
    invoice = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
        .filter(SalesInvoice.id == invoice_id)
        .with_for_update()
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)

    if invoice.status == "BATCHED":
        raise HTTPException(
            status_code=400,
            detail="Invoice is already batched. Stock has already been reduced from inventory."
        )

    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot batch invoice with status {invoice.status}. Only DRAFT invoices can be batched."
        )

    if not invoice.items or len(invoice.items) == 0:
        raise HTTPException(
            status_code=400,
            detail="Invoice has no line items. Add items before batching."
        )

    # If frontend sent current items, update each draft line to match (quantity, unit, price, discount)
    if body and body.items and len(body.items) > 0:
        payload_by_item = {str(it.item_id): it for it in body.items}
        total_exclusive = Decimal("0")
        total_vat = Decimal("0")
        for line in invoice.items:
            payload = payload_by_item.get(str(line.item_id))
            if not payload:
                total_exclusive += line.line_total_exclusive
                total_vat += line.vat_amount
                continue
            item = line.item
            if not item:
                total_exclusive += line.line_total_exclusive
                total_vat += line.vat_amount
                continue
            line.quantity = payload.quantity
            line.unit_name = payload.unit_name
            line.unit_price_exclusive = payload.unit_price_exclusive or Decimal("0")
            line.discount_percent = payload.discount_percent or Decimal("0")
            line.discount_amount = payload.discount_amount or Decimal("0")
            # Model B: margin at batch is validated after allocation using allocated batch cost only (see below)
            line_vat_rate = Decimal(str(vat_rate_to_percent(item.vat_rate)))
            line.line_total_exclusive = (
                line.unit_price_exclusive * line.quantity
                - (line.unit_price_exclusive * line.quantity * line.discount_percent / Decimal("100"))
                - line.discount_amount
            )
            line.vat_rate = line_vat_rate
            line.vat_amount = line.line_total_exclusive * line_vat_rate / Decimal("100")
            line.line_total_inclusive = line.line_total_exclusive + line.vat_amount
            total_exclusive += line.line_total_exclusive
            total_vat += line.vat_amount
        invoice.total_exclusive = total_exclusive
        invoice.vat_amount = total_vat
        invoice.total_inclusive = total_exclusive + total_vat
        if total_exclusive and total_exclusive > 0:
            invoice.vat_rate = total_vat / total_exclusive * Decimal("100")
        else:
            invoice.vat_rate = Decimal("0")
        db.flush()

    # Process each item and reduce stock based on FEFO allocation (all in same transaction)
    ledger_entries = []

    try:
        for invoice_item in invoice.items:
            item = invoice_item.item
            if not item:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item {invoice_item.item_id} not found. Cannot batch."
                )

            quantity_base = InventoryService.convert_to_base_units(
                db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
            )

            is_available, available, required = InventoryService.check_stock_availability(
                db, invoice_item.item_id, invoice.branch_id,
                float(invoice_item.quantity), invoice_item.unit_name
            )
            if not is_available:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for {invoice_item.item_name or item.name}. Available: {available}, Required: {required}"
                )

            allocations = InventoryService.allocate_stock_fefo(
                db, invoice_item.item_id, invoice.branch_id,
                quantity_base, invoice_item.unit_name
            )

            qty_base_dec = Decimal(str(quantity_base))
            total_line_ledger_cost = _total_cost_from_allocations(allocations)

            # Model B: post-allocation margin and floor price validation (blended cost across FEFO layers)
            if allocations and qty_base_dec > 0:
                cost_per_base_unit = total_line_ledger_cost / qty_base_dec
                mult = get_unit_multiplier_from_item(item, invoice_item.unit_name)
                if mult is not None and mult > 0:
                    cost_per_sale_unit = cost_per_base_unit * mult
                    unit_price_val = invoice_item.unit_price_exclusive or Decimal("0")
                    if cost_per_sale_unit > 0:
                        user_has_override = _user_has_sell_below_min_margin(db, batched_by, invoice.branch_id)
                        is_promo = is_line_price_at_promo(
                            db, invoice_item.item_id, invoice_item.unit_name or "", unit_price_val
                        )
                        validation = validate_line_price(
                            db,
                            invoice.company_id,
                            invoice_item.item_id,
                            unit_price_val,
                            cost_per_sale_unit,
                            user_has_override,
                            branch_id=invoice.branch_id,
                            is_promo_price=is_promo,
                        )
                        if not validation.get("allowed"):
                            raise HTTPException(
                                status_code=400,
                                detail=validation.get("message", "Price validation failed.")
                            )

                # Snapshot: per retail/base unit so qty×mult×unit_cost_used == sum(SALE ledger total_cost)
                old_uc = invoice_item.unit_cost_used
                if old_uc is not None and float(old_uc) > 0:
                    snap_cogs = qty_base_dec * Decimal(str(old_uc))
                    line_rev = invoice_item.line_total_exclusive or Decimal("0")
                    diff = abs(snap_cogs - total_line_ledger_cost)
                    if line_rev > 0 and diff > (SNAPSHOT_VS_LEDGER_WARN_THRESHOLD * line_rev):
                        logging.getLogger(__name__).warning(
                            "Sales line snapshot COGS vs ledger (pre-reconcile): invoice=%s item=%s "
                            "snap_cogs=%s ledger_cogs=%s line_total_excl=%s",
                            invoice.invoice_no,
                            invoice_item.item_id,
                            snap_cogs,
                            total_line_ledger_cost,
                            line_rev,
                        )
                invoice_item.unit_cost_used = cost_per_base_unit
                invoice_item.batch_id = allocations[0]["ledger_entry_id"]

            for allocation in allocations:
                qty = Decimal(str(allocation["quantity"]))
                uc = Decimal(str(allocation["unit_cost"]))
                ledger_entry = InventoryLedger(
                    company_id=invoice.company_id,
                    branch_id=invoice.branch_id,
                    item_id=invoice_item.item_id,
                    batch_number=allocation["batch_number"],
                    expiry_date=allocation["expiry_date"],
                    transaction_type="SALE",
                    reference_type="sales_invoice",
                    reference_id=invoice.id,
                    document_number=invoice.invoice_no,
                    quantity_delta=-qty,
                    unit_cost=uc,
                    total_cost=uc * qty,
                    created_by=batched_by
                )
                ledger_entries.append(ledger_entry)

        invoice.batched = True
        invoice.batched_by = batched_by
        invoice.batched_at = datetime.utcnow()

        # For cash invoices, mark as PAID automatically during batching
        if getattr(invoice, "payment_mode", "").lower() == "cash":
            invoice.payment_status = "PAID"
            invoice.status = "PAID"
            invoice.cashier_approved = True
            invoice.approved_by = batched_by
            invoice.approved_at = datetime.now(timezone.utc)
        else:
            invoice.status = "BATCHED"

        for entry in ledger_entries:
            db.add(entry)

        db.flush()
        for entry in ledger_entries:
            SnapshotService.upsert_inventory_balance(
                db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta,
                document_number=getattr(entry, "document_number", None) or invoice.invoice_no,
            )
        for inv_item in invoice.items:
            SnapshotService.upsert_search_snapshot_last_sale(
                db, invoice.company_id, invoice.branch_id, inv_item.item_id, invoice.invoice_date
            )
        for entry in ledger_entries:
            SnapshotRefreshService.schedule_snapshot_refresh(db, entry.company_id, entry.branch_id, item_id=entry.item_id)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Batch failed: {str(e)}"
        )

    db.refresh(invoice)

    try:
        order_book_entries = OrderBookService.process_sale_for_order_book(
            db=db,
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            invoice_id=invoice.id,
            user_id=batched_by
        )
        if order_book_entries:
            logging.getLogger(__name__).info("Auto-added %s items to order book from invoice %s", len(order_book_entries), invoice_id)
    except Exception as e:
        logging.getLogger(__name__).warning("Order book auto-add failed for invoice %s: %s", invoice_id, e)

    return invoice


@router.delete("/invoice/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_invoice(
    invoice_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Delete sales invoice (only if status is DRAFT)
    
    Only DRAFT invoices can be deleted. BATCHED invoices cannot be deleted.
    """
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete invoice with status {invoice.status}. Only DRAFT invoices can be deleted."
        )
    
    db.delete(invoice)
    db.commit()
    return None


# =====================================================
# SPLIT PAYMENT ENDPOINTS
# =====================================================

@router.post("/invoice/{invoice_id}/payments", response_model=InvoicePaymentResponse, status_code=status.HTTP_201_CREATED)
def add_invoice_payment(
    invoice_id: UUID,
    payment: InvoicePaymentCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Add a split payment to a sales invoice.
    Lock on invoice ensures consistent totals; duplicate identical payment within 5s rejected.
    """
    invoice = (
        db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).with_for_update().first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status not in ["BATCHED", "PAID"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot add payment to invoice with status {invoice.status}. Invoice must be BATCHED."
        )
    existing_payments = db.query(func.sum(InvoicePayment.amount)).filter(
        InvoicePayment.invoice_id == invoice_id
    ).scalar() or Decimal("0")
    total_paid = existing_payments + payment.amount
    if total_paid > invoice.total_inclusive:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount exceeds invoice total. Invoice: {invoice.total_inclusive}, Total paid: {total_paid}"
        )
    # Reject duplicate identical payment within same request window (e.g. double submit)
    duplicate_window = datetime.now(timezone.utc) - timedelta(seconds=5)
    recent_same = (
        db.query(InvoicePayment)
        .filter(
            InvoicePayment.invoice_id == invoice_id,
            InvoicePayment.amount == payment.amount,
            InvoicePayment.payment_mode == payment.payment_mode,
            InvoicePayment.created_at >= duplicate_window,
        )
        .first()
    )
    if recent_same:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An identical payment was just recorded. If this was a duplicate request, ignore.",
        )
    # Create payment
    db_payment = InvoicePayment(
        invoice_id=invoice_id,
        payment_mode=payment.payment_mode,
        amount=payment.amount,
        payment_reference=payment.payment_reference,
        paid_by=payment.paid_by
    )
    db.add(db_payment)
    
    # Update invoice payment status
    if total_paid >= invoice.total_inclusive:
        invoice.payment_status = "PAID"
        invoice.status = "PAID"
        invoice.cashier_approved = True
        invoice.approved_by = payment.paid_by
        invoice.approved_at = datetime.now(timezone.utc)
    elif total_paid > 0:
        invoice.payment_status = "PARTIAL"
    
    db.commit()
    db.refresh(db_payment)
    return db_payment


@router.get("/invoice/{invoice_id}/payments", response_model=List[InvoicePaymentResponse])
def get_invoice_payments(
    invoice_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get all payments for a sales invoice"""
    payments = db.query(InvoicePayment).filter(
        InvoicePayment.invoice_id == invoice_id
    ).order_by(InvoicePayment.created_at).all()
    return payments


@router.delete("/invoice/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice_payment(
    payment_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Delete a payment from an invoice
    
    Only allowed if invoice is still BATCHED (not yet PAID)
    """
    payment = db.query(InvoicePayment).filter(InvoicePayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == payment.invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status == "PAID":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete payment from PAID invoice. Invoice must be BATCHED."
        )
    
    db.delete(payment)
    
    # Recalculate payment status
    remaining_payments = db.query(func.sum(InvoicePayment.amount)).filter(
        InvoicePayment.invoice_id == invoice.id
    ).scalar() or Decimal("0")
    
    if remaining_payments <= 0:
        invoice.payment_status = "UNPAID"
    elif remaining_payments < invoice.total_inclusive:
        invoice.payment_status = "PARTIAL"
    
    db.commit()
    return None


# =====================================================
# CONVERT SALES INVOICE TO QUOTATION
# =====================================================

@router.post("/invoice/{invoice_id}/convert-to-quotation", response_model=dict, status_code=status.HTTP_201_CREATED)
def convert_sales_invoice_to_quotation(
    invoice_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Convert a DRAFT sales invoice to a quotation
    
    This will:
    1. Create a quotation with the same items and details
    2. Delete the sales invoice (since it's DRAFT, it can be deleted)
    3. Return the new quotation ID
    """
    from sqlalchemy.orm import selectinload
    from app.models import Quotation, QuotationItem
    
    # Get invoice
    invoice = db.query(SalesInvoice).options(
        selectinload(SalesInvoice.items)
    ).filter(SalesInvoice.id == invoice_id).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot convert invoice with status {invoice.status}. Only DRAFT invoices can be converted to quotations."
        )
    
    if not invoice.items or len(invoice.items) == 0:
        raise HTTPException(
            status_code=400,
            detail="Invoice has no items. Cannot convert to quotation."
        )
    
    # Generate quotation number
    quotation_no = DocumentService.get_quotation_number(
        db, invoice.company_id, invoice.branch_id
    )
    
    # Create quotation with same details
    quotation = Quotation(
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        quotation_no=quotation_no,
        quotation_date=invoice.invoice_date,
        customer_name=invoice.customer_name,
        customer_pin=invoice.customer_pin,
        reference=None,  # Can be set later
        notes=None,  # Can be set later
        status="draft",
        total_exclusive=invoice.total_exclusive,
        vat_rate=invoice.vat_rate,
        vat_amount=invoice.vat_amount,
        discount_amount=invoice.discount_amount,
        total_inclusive=invoice.total_inclusive,
        valid_until=None,  # Can be set later
        created_by=invoice.created_by
    )
    db.add(quotation)
    db.flush()
    
    # Create quotation items from invoice items
    quotation_items = []
    for invoice_item in invoice.items:
        quotation_item = QuotationItem(
            quotation_id=quotation.id,
            item_id=invoice_item.item_id,
            unit_name=invoice_item.unit_name,
            quantity=invoice_item.quantity,
            unit_price_exclusive=invoice_item.unit_price_exclusive,
            discount_percent=invoice_item.discount_percent,
            discount_amount=invoice_item.discount_amount,
            vat_rate=invoice_item.vat_rate,
            vat_amount=invoice_item.vat_amount,
            line_total_exclusive=invoice_item.line_total_exclusive,
            line_total_inclusive=invoice_item.line_total_inclusive
        )
        quotation_items.append(quotation_item)
        db.add(quotation_item)
    
    # Delete the sales invoice (it's DRAFT, so safe to delete)
    db.delete(invoice)
    
    db.commit()
    db.refresh(quotation)
    
    return {
        "message": "Sales invoice converted to quotation successfully",
        "quotation_id": str(quotation.id),
        "quotation_no": quotation.quotation_no
    }

