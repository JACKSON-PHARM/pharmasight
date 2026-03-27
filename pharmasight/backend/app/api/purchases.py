"""
Purchases API routes (GRN and Supplier Invoices)
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload
from typing import Any, List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime, timezone, timedelta
from app.dependencies import get_tenant_db, get_current_user, get_tenant_optional, get_tenant_or_default, require_document_belongs_to_user_company
from app.database_master import get_master_db
from app.models.tenant import Tenant
from app.models.settings import CompanySetting
from app.models import (
    GRN, GRNItem, SupplierInvoice, SupplierInvoiceItem,
    PurchaseOrder, PurchaseOrderItem,
    DailyOrderBook,
    InventoryLedger, Item, Supplier, Branch, User, Company,
    SupplierPayment, SupplierPaymentAllocation,
)
from app.services.item_units_helper import get_unit_multiplier_from_item
from app.schemas.purchase import (
    GRNCreate, GRNResponse,
    SupplierInvoiceCreate, SupplierInvoiceResponse,
    SupplierInvoicePaymentAllocationInfo,
    SupplierInvoiceItemCreate, SupplierInvoiceItemUpdate,
    PurchaseOrderCreate, PurchaseOrderResponse,
    PurchaseOrderItemCreate,
    BatchSupplierInvoiceBody,
)
from app.services.inventory_service import InventoryService
from app.services.document_service import DocumentService
from app.services.snapshot_service import SnapshotService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.order_book_service import OrderBookService
from app.services.supplier_ledger_service import SupplierLedgerService
from app.services.supplier_invoice_payment_service import (
    sync_supplier_invoice_paid_from_allocations,
    prepare_supplier_invoice_for_response,
)
from app.services.pricing_config_service import (
    check_stock_adjustment_requires_confirmation,
    is_cost_outlier_vs_weighted_average,
)
from app.services.stock_validation_service import (
    get_stock_validation_config,
    validate_stock_entry_with_config,
    StockValidationError,
)
from app.services.document_pdf_generator import build_po_pdf
from app.services.tenant_storage_service import (
    upload_po_pdf,
    get_signed_url,
    get_signed_url_with_path_tenant,
    download_file,
    download_file_with_path_tenant,
    tenant_id_from_stored_path,
)
from app.utils.vat import vat_rate_to_percent
from fastapi.responses import Response
from app.services.document_pdf_generator import build_grn_pdf, build_supplier_invoice_pdf
from app.services.canonical_pricing import CanonicalPricingService
from app.config import settings
import json
import sqlalchemy.exc
import httpx

router = APIRouter()


def _legacy_path_tenant_fallback_enabled() -> bool:
    return bool(getattr(settings, "ENABLE_LEGACY_PATH_TENANT_FALLBACK", False))


def _parse_expiry_date(expiry) -> Optional[date]:
    """Parse expiry from batch (date, datetime, or ISO string)."""
    if expiry is None:
        return None
    if isinstance(expiry, date):
        return expiry if not isinstance(expiry, datetime) else expiry.date()
    if isinstance(expiry, datetime):
        return expiry.date()
    if isinstance(expiry, str) and expiry.strip():
        try:
            return datetime.fromisoformat(expiry.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            pass
    return None


def _validate_batches_central(
    item_name: str,
    item,
    batches: List,
    config,
    override: bool = False,
    from_dict: bool = True,
) -> None:
    """
    Validate each batch with central StockValidationService. Raises HTTPException on expired or invalid.
    Keeps existing _require_batch_and_expiry_for_track_expiry_item for presence; this adds expiry/short-expiry checks.
    """
    if not getattr(item, "track_expiry", False):
        return
    require_batch = bool(getattr(config, "require_batch_tracking", True))
    require_expiry = bool(getattr(config, "require_expiry_tracking", True))
    if not require_batch and not require_expiry:
        return
    for batch in batches:
        if from_dict:
            bn = batch.get("batch_number") or None
            if bn is not None and not str(bn).strip():
                bn = None
            ed = _parse_expiry_date(batch.get("expiry_date"))
        else:
            bn = (getattr(batch, "batch_number", None) or "").strip() or None
            ed = getattr(batch, "expiry_date", None)
            if ed is not None and isinstance(ed, datetime):
                ed = ed.date()
        try:
            result = validate_stock_entry_with_config(
                config,
                batch_number=bn,
                expiry_date=ed,
                track_expiry=True,
                require_batch=require_batch,
                require_expiry=require_expiry,
                override=override,
            )
        except StockValidationError as e:
            raise HTTPException(
                status_code=400,
                detail=e.result.message if e.result else str(e),
            )
        if not result.valid:
            if getattr(result, "short_expiry", False):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "SHORT_EXPIRY_OVERRIDE_REQUIRED",
                        "message": result.message or "Batch/expiry validation failed.",
                        "days_remaining": getattr(result, "days_remaining", None),
                        "min_expiry_days": getattr(config, "min_expiry_days", None),
                    },
                )
            raise HTTPException(status_code=400, detail=result.message or "Batch/expiry validation failed.")


def _require_batch_and_expiry_for_track_expiry_item(
    item_name: str,
    batches: Optional[List],
    *,
    from_dict: bool = False,
    require_batch: bool = True,
    require_expiry: bool = True,
) -> None:
    """
    If item has track_expiry, batches must be present, non-empty, and each batch
    must have batch_number and/or expiry_date based on company settings. Raises HTTPException 400 otherwise.
    from_dict: if True, each batch is a dict with keys batch_number, expiry_date.
    """
    if not require_batch and not require_expiry:
        return
    if not batches or len(batches) == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Item '{item_name}' has Track Expiry enabled. You must use 'Manage Batches' and enter "
                "at least one batch with the required tracking fields before saving."
            ),
        )
    for i, batch in enumerate(batches):
        if from_dict:
            batch_num = batch.get("batch_number") if isinstance(batch.get("batch_number"), str) else None
            expiry = batch.get("expiry_date")
        else:
            batch_num = getattr(batch, "batch_number", None)
            expiry = getattr(batch, "expiry_date", None)
        if require_batch and not (batch_num and str(batch_num).strip()):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Item '{item_name}' has Track Expiry enabled. Batch number is required for every batch "
                    "(use Manage Batches and fill Batch Number)."
                ),
            )
        if require_expiry and not expiry:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Item '{item_name}' has Track Expiry enabled. Expiry date is required for every batch "
                    "(use Manage Batches and fill Expiry Date)."
                ),
            )


@router.post("/grn", response_model=GRNResponse, status_code=status.HTTP_201_CREATED)
def create_grn(
    grn: GRNCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create GRN (Goods Received Note)
    
    This updates inventory ledger with stock and cost.
    VAT is handled separately in Purchase Invoice.
    """
    # Generate GRN number
    grn_no = DocumentService.get_grn_number(
        db, grn.company_id, grn.branch_id
    )
    
    # Preload items and config once (no N+1)
    grn_item_ids = [item_data.item_id for item_data in grn.items]
    grn_items_preloaded = db.query(Item).filter(Item.id.in_(grn_item_ids), Item.company_id == grn.company_id).all()
    grn_items_map = {item.id: item for item in grn_items_preloaded}
    grn_stock_config = get_stock_validation_config(db, grn.company_id)
    
    total_cost = Decimal("0")
    grn_items = []
    ledger_entries = []
    
    for item_data in grn.items:
        # Get item from preloaded map
        item = grn_items_map.get(item_data.item_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        if not getattr(item, "setup_complete", True):
            raise HTTPException(
                status_code=400,
                detail=f"Item '{item.name}' is not ready for transactions. Complete item setup (pack size, units) in Items before adding to a GRN."
            )
        
        # Unit multiplier from item columns (items table is source of truth)
        multiplier = get_unit_multiplier_from_item(item, item_data.unit_name)
        if multiplier is None:
            raise HTTPException(status_code=404, detail=f"Unit '{item_data.unit_name}' not found for item {item_data.item_id}")
        
        # Central validation when track_expiry: require batch/expiry and reject expired/short (per config)
        if getattr(item, "track_expiry", False):
            if item_data.batches and len(item_data.batches) > 0:
                _validate_batches_central(
                    item.name or str(item_data.item_id), item, item_data.batches,
                    grn_stock_config, override=False, from_dict=False,
                )
            else:
                # Legacy single batch: validate (batch_number, expiry_date) if provided; else validation will require them
                legacy_batch = [{"batch_number": item_data.batch_number or "", "expiry_date": item_data.expiry_date}]
                _validate_batches_central(
                    item.name or str(item_data.item_id), item, legacy_batch,
                    grn_stock_config, override=False, from_dict=True,
                )
        
        # Handle batch distribution: if batches array is provided, use it; otherwise use legacy single batch
        if item_data.batches and len(item_data.batches) > 0:
            # Multiple batches per item
            total_batch_quantity = sum(batch.quantity for batch in item_data.batches)
            if abs(total_batch_quantity - item_data.quantity) > Decimal("0.01"):  # Allow small rounding differences
                raise HTTPException(
                    status_code=400,
                    detail=f"Sum of batch quantities ({total_batch_quantity}) must equal item quantity ({item_data.quantity})"
                )
            
            # Calculate weighted average cost for validation
            weighted_cost = sum(batch.quantity * batch.unit_cost for batch in item_data.batches) / total_batch_quantity
            cost_variance = abs(weighted_cost - item_data.unit_cost) / item_data.unit_cost if item_data.unit_cost > 0 else 0
            if cost_variance > Decimal("0.01"):  # 1% variance allowed
                raise HTTPException(
                    status_code=400,
                    detail=f"Weighted average batch cost ({weighted_cost}) differs significantly from item unit cost ({item_data.unit_cost})"
                )
            
            # Create GRN item (with first batch info for legacy compatibility)
            first_batch = item_data.batches[0]
            grn_item = GRNItem(
                grn_id=None,
                item_id=item_data.item_id,
                unit_name=item_data.unit_name,
                quantity=item_data.quantity,
                unit_cost=item_data.unit_cost,
                batch_number=first_batch.batch_number,  # Legacy field
                expiry_date=first_batch.expiry_date,  # Legacy field
                total_cost=sum(batch.quantity * batch.unit_cost for batch in item_data.batches)
            )
            grn_items.append(grn_item)
            total_cost += grn_item.total_cost
            
            # Create ledger entries for each batch
            for batch_idx, batch in enumerate(item_data.batches):
                quantity_base = int(float(batch.quantity) * float(multiplier))
                unit_cost_base = Decimal(str(batch.unit_cost)) / multiplier
                
                ledger_entry = InventoryLedger(
                    company_id=grn.company_id,
                    branch_id=grn.branch_id,
                    item_id=item_data.item_id,
                    batch_number=batch.batch_number,
                    expiry_date=batch.expiry_date,
                    transaction_type="PURCHASE",
                    reference_type="grn",
                    document_number=grn_no,
                    quantity_delta=quantity_base,
                    unit_cost=unit_cost_base,
                    total_cost=unit_cost_base * quantity_base,
                    batch_cost=unit_cost_base,  # Store batch-specific cost
                    remaining_quantity=quantity_base,  # Initialize remaining quantity
                    is_batch_tracked=True,
                    split_sequence=batch_idx,  # 0 for first batch, 1, 2, 3... for subsequent
                    created_by=grn.created_by
                )
                ledger_entries.append(ledger_entry)
        else:
            # Legacy: single batch (backward compatibility)
            quantity_base = InventoryService.convert_to_base_units(
                db, item_data.item_id, float(item_data.quantity), item_data.unit_name
            )
            
            unit_cost_base = Decimal(str(item_data.unit_cost)) / multiplier
            
            total_item_cost = Decimal(str(item_data.unit_cost)) * item_data.quantity
            total_cost += total_item_cost
            
            # Create GRN item
            grn_item = GRNItem(
                grn_id=None,
                item_id=item_data.item_id,
                unit_name=item_data.unit_name,
                quantity=item_data.quantity,
                unit_cost=item_data.unit_cost,
                batch_number=item_data.batch_number,
                expiry_date=item_data.expiry_date,
                total_cost=total_item_cost
            )
            grn_items.append(grn_item)
            
            # Create ledger entry (positive for purchase)
            ledger_entry = InventoryLedger(
                company_id=grn.company_id,
                branch_id=grn.branch_id,
                item_id=item_data.item_id,
                batch_number=item_data.batch_number,
                expiry_date=item_data.expiry_date,
                transaction_type="PURCHASE",
                reference_type="grn",
                document_number=grn_no,
                quantity_delta=quantity_base,
                unit_cost=unit_cost_base,
                total_cost=unit_cost_base * quantity_base,
                batch_cost=unit_cost_base,
                remaining_quantity=quantity_base,
                is_batch_tracked=bool(item_data.batch_number),  # Track if batch number provided
                created_by=grn.created_by
            )
            ledger_entries.append(ledger_entry)
    # Reject duplicate POST within same request window (e.g. double submit)
    window = datetime.now(timezone.utc) - timedelta(seconds=2)
    recent_same = (
        db.query(GRN)
        .filter(
            GRN.company_id == grn.company_id,
            GRN.branch_id == grn.branch_id,
            GRN.supplier_id == grn.supplier_id,
            GRN.date_received == grn.date_received,
            GRN.total_cost >= total_cost - Decimal("0.01"),
            GRN.total_cost <= total_cost + Decimal("0.01"),
            GRN.created_at >= window,
        )
        .first()
    )
    if recent_same:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A GRN with the same details was just created. If this was a duplicate request, ignore.",
        )
    # Create GRN
    db_grn = GRN(
        company_id=grn.company_id,
        branch_id=grn.branch_id,
        supplier_id=grn.supplier_id,
        grn_no=grn_no,
        date_received=grn.date_received,
        total_cost=total_cost,
        notes=grn.notes,
        created_by=grn.created_by
    )
    db.add(db_grn)
    db.flush()
    
    # Link items to GRN
    for item in grn_items:
        item.grn_id = db_grn.id
        db.add(item)
    
    # Add ledger entries
    for entry in ledger_entries:
        entry.reference_id = db_grn.id
        db.add(entry)

    db.flush()

    # Update snapshots in same transaction
    for entry in ledger_entries:
        SnapshotService.upsert_inventory_balance(
            db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta,
            document_number=getattr(entry, "document_number", None) or grn_no,
        )
        SnapshotService.upsert_purchase_snapshot(
            db, entry.company_id, entry.branch_id, entry.item_id,
            entry.unit_cost, getattr(entry, "created_at", None) or datetime.now(timezone.utc),
            db_grn.supplier_id
        )
        SnapshotRefreshService.schedule_snapshot_refresh(db, entry.company_id, entry.branch_id, item_id=entry.item_id)

    # Order book lifecycle: mark ORDERED entries as received and archive to history (CLOSED)
    grn_item_ids = list({e.item_id for e in ledger_entries})
    OrderBookService.mark_items_received(
        db, db_grn.company_id, db_grn.branch_id, grn_item_ids,
        received_at=datetime.now(timezone.utc),
    )

    db.commit()
    db.refresh(db_grn)
    return db_grn


@router.get("/grn/{grn_id}/pdf")
def get_grn_pdf(
    grn_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Generate and return GRN as PDF (Download PDF). On-demand only."""
    grn = db.query(GRN).options(
        selectinload(GRN.items).selectinload(GRNItem.item)
    ).filter(GRN.id == grn_id).first()
    if not grn:
        raise HTTPException(status_code=404, detail="GRN not found")
    company = db.query(Company).filter(Company.id == grn.company_id).first()
    branch = db.query(Branch).filter(Branch.id == grn.branch_id).first()
    supplier_name = grn.supplier.name if grn.supplier else "—"
    items_data = []
    for oi in grn.items:
        item_name = oi.item.name if oi.item else "—"
        items_data.append({
            "item_name": item_name,
            "quantity": float(oi.quantity),
            "unit_name": oi.unit_name or "",
            "unit_cost": float(oi.unit_cost or 0),
            "total_cost": float(oi.total_cost or 0),
        })
    try:
        pdf_bytes = build_grn_pdf(
            company_name=company.name if company else "—",
            company_address=getattr(company, "address", None) if company else None,
            company_phone=getattr(company, "phone", None) if company else None,
            company_pin=getattr(company, "pin", None) if company else None,
            branch_name=branch.name if branch else None,
            branch_address=getattr(branch, "address", None) if branch else None,
            grn_no=grn.grn_no,
            date_received=grn.date_received,
            supplier_name=supplier_name,
            items=items_data,
            total_cost=grn.total_cost or Decimal("0"),
            notes=grn.notes,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate GRN PDF: {str(e)}")
    filename = f"grn-{grn.grn_no or grn_id}.pdf".replace(" ", "-")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/grn/{grn_id}", response_model=GRNResponse)
def get_grn(
    grn_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get GRN by ID"""
    # Eagerly load items relationship to avoid lazy loading issues
    grn = db.query(GRN).options(
        selectinload(GRN.items)
    ).filter(GRN.id == grn_id).first()
    if not grn:
        raise HTTPException(status_code=404, detail="GRN not found")
    return grn


@router.post("/invoice", response_model=SupplierInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_supplier_invoice(
    invoice: SupplierInvoiceCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create Supplier Invoice (DRAFT - No Stock Added Yet)
    
    Saves the invoice as DRAFT. Stock is NOT added until invoice is batched.
    Use the /invoice/{id}/batch endpoint to add stock to inventory.
    System document number is ALWAYS auto-generated.
    Supplier's invoice number (external) is stored in reference field.
    """
    user = current_user_and_db[0]

    # Enforce per-supplier requirement for external supplier invoice number when configured.
    supplier = (
        db.query(Supplier)
        .filter(
            Supplier.id == invoice.supplier_id,
            Supplier.company_id == invoice.company_id,
        )
        .first()
    )
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if getattr(supplier, "requires_supplier_invoice_number", False):
        if not (invoice.supplier_invoice_number and str(invoice.supplier_invoice_number).strip()):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Supplier invoice number is required for this supplier.",
            )
    # ALWAYS auto-generate system document number (internal document number)
    invoice_number = DocumentService.get_supplier_invoice_number(
        db, invoice.company_id, invoice.branch_id
    )

    # Preload all items in one query (no N+1)
    item_ids = [item_data.item_id for item_data in invoice.items]
    items_preloaded = db.query(Item).filter(Item.id.in_(item_ids), Item.company_id == invoice.company_id).all()
    items_map = {item.id: item for item in items_preloaded}
    stock_validation_config = get_stock_validation_config(db, invoice.company_id)

    # Resolve unit cost per line: default to last purchase (per base * multiplier) when 0 or missing; same as item adjustment
    resolved_unit_costs = []
    need_confirm_list = []
    for item_data in invoice.items:
        item = items_map.get(item_data.item_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        multiplier = get_unit_multiplier_from_item(item, item_data.unit_name)
        if multiplier is None:
            raise HTTPException(status_code=404, detail=f"Unit '{item_data.unit_name}' not found for item {item_data.item_id}")
        uc = item_data.unit_cost_exclusive
        if uc is None or (uc is not None and float(uc) <= 0):
            last_base = CanonicalPricingService.get_last_purchase_cost(
                db, item_data.item_id, invoice.branch_id, invoice.company_id
            )
            if last_base is not None and float(last_base) > 0:
                uc = last_base * Decimal(str(multiplier))
            else:
                uc = Decimal("0")
        else:
            uc = Decimal(str(uc))
        resolved_unit_costs.append(uc)
        unit_cost_base = uc / Decimal(str(multiplier))
        # Floor price / margin confirmation (same rules as stock adjustment)
        check = check_stock_adjustment_requires_confirmation(
            db, item_data.item_id, invoice.company_id, unit_cost_base
        )
        if check.get("requires_confirmation"):
            need_confirm_list.append({
                "item_id": str(item_data.item_id),
                "item_name": getattr(item, "name", None) or str(item_data.item_id),
                "unit_cost_base": float(unit_cost_base),
                "floor_price": check.get("floor_price"),
                "margin_below_standard": check.get("margin_below_standard", False),
            })
        # Cost outlier (same as stock adjustment)
        outlier = is_cost_outlier_vs_weighted_average(
            db, invoice.company_id, invoice.branch_id, item_data.item_id, unit_cost_base
        )
        if outlier.get("is_outlier"):
            from app.dependencies import _user_has_permission
            has_override = _user_has_permission(db, user.id, "inventory.cost_override")
            if not has_override:
                baseline = outlier.get("baseline_cost")
                deviation = outlier.get("deviation_pct")
                threshold = outlier.get("threshold_pct")
                item_name = getattr(item, "name", None) or str(item_data.item_id)
                detail_msg = (
                    f"Unit cost {unit_cost_base} for item '{item_name}' deviates "
                    f"{deviation:.1f}% from branch weighted average {baseline}. Manager override required."
                )
                if threshold is not None:
                    detail_msg += f" (Threshold {threshold:.1f}%.)"
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "COST_OUTLIER_OVERRIDE_REQUIRED", "message": detail_msg},
                )
    if need_confirm_list:
        confirm_map = {}
        if invoice.confirmations:
            for c in invoice.confirmations:
                k = (str(c.item_id), round(float(c.unit_cost_base), 4))
                confirm_map[k] = float(c.unit_cost_base)
        missing = []
        for nc in need_confirm_list:
            k = (nc["item_id"], round(nc["unit_cost_base"], 4))
            if k not in confirm_map:
                missing.append(nc)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PRICE_CONFIRMATION_REQUIRED",
                    "message": "Some items have a floor price or margin below standard. Re-enter the unit cost for each to confirm.",
                    "items": missing,
                },
            )

    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    invoice_items = []
    # NO ledger entries here - stock is added when batching

    for idx, item_data in enumerate(invoice.items):
        # Get item from preloaded map
        item = items_map.get(item_data.item_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        multiplier = get_unit_multiplier_from_item(item, item_data.unit_name)
        if multiplier is None:
            raise HTTPException(status_code=404, detail=f"Unit '{item_data.unit_name}' not found for item {item_data.item_id}")

        unit_cost_exclusive = resolved_unit_costs[idx] if idx < len(resolved_unit_costs) else item_data.unit_cost_exclusive
        
        # Enforce tracking fields for items with Track Expiry enabled (company-level toggles decide what is required)
        if getattr(item, "track_expiry", False):
            _require_batch_and_expiry_for_track_expiry_item(
                item.name or str(item_data.item_id),
                item_data.batches,
                from_dict=False,
                require_batch=bool(getattr(stock_validation_config, "require_batch_tracking", True)),
                require_expiry=bool(getattr(stock_validation_config, "require_expiry_tracking", True)),
            )
            # Central validation: expired reject. Short-expiry only enforced at batch time (allow draft save).
            if item_data.batches:
                _validate_batches_central(
                    item.name or str(item_data.item_id),
                    item,
                    item_data.batches,
                    stock_validation_config,
                    override=True,
                    from_dict=False,
                )
        
        # Accounting model:
        # - Keep original/gross unit cost in `unit_cost_exclusive` for inventory valuation and `last_unit_cost`.
        # - Apply discount only to *payable* totals (line totals / supplier ledger) by calculating net cost here.
        disc_pct = Decimal(str(getattr(item_data, "discount_percent", 0) or 0))
        disc_pct = max(Decimal("0"), min(Decimal("100"), disc_pct))
        net_unit_cost_exclusive = unit_cost_exclusive * (Decimal("100") - disc_pct) / Decimal("100")

        # Calculate line totals (VAT) — normalize vat_rate (e.g. 0.16 -> 16%); use item master VAT if request sent 0
        line_total_exclusive = net_unit_cost_exclusive * item_data.quantity
        vat_rate_pct = Decimal(str(vat_rate_to_percent(item_data.vat_rate)))
        if vat_rate_pct == 0 and getattr(item, "vat_rate", None) is not None:
            vat_rate_pct = Decimal(str(vat_rate_to_percent(item.vat_rate)))
        line_vat = line_total_exclusive * vat_rate_pct / Decimal("100")
        line_total_inclusive = line_total_exclusive + line_vat
        
        # Store batch data as JSON for later batching
        batch_data_json = None
        if item_data.batches and len(item_data.batches) > 0:
            import json
            batch_data_json = json.dumps([{
                "batch_number": batch.batch_number or "",
                "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
                "quantity": float(batch.quantity),
                "unit_cost": float(batch.unit_cost)
            } for batch in item_data.batches])
        
        invoice_item = SupplierInvoiceItem(
            purchase_invoice_id=None,  # Will be set after invoice creation (keep column name for backward compatibility)
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_cost_exclusive=unit_cost_exclusive,
            vat_rate=vat_rate_pct,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive,
            batch_data=batch_data_json  # Store batch data for later
        )
        invoice_items.append(invoice_item)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
        
        # NOTE: Stock is NOT added here. It's added when invoice is batched via /invoice/{id}/batch
    
    total_inclusive = total_exclusive + total_vat
    # amount_paid is derived only from supplier_payment_allocations (none on draft create)
    balance = total_inclusive

    # Default payment due date from supplier terms when not set on the document (aging / overdue use this).
    resolved_due_date = invoice.due_date
    if resolved_due_date is None and invoice.invoice_date is not None:
        term_days = supplier.default_payment_terms_days or supplier.credit_terms or 0
        resolved_due_date = invoice.invoice_date + timedelta(days=int(term_days))

    # Create supplier invoice (DRAFT status - no stock added yet)
    db_invoice = SupplierInvoice(
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        supplier_id=invoice.supplier_id,
        invoice_number=invoice_number,  # System-generated document number (always auto-generated)
        pin_number=None,  # Deprecated field
        reference=invoice.supplier_invoice_number or invoice.reference,  # Store supplier's invoice number (external) in reference
        invoice_date=invoice.invoice_date,
        due_date=resolved_due_date,
        internal_reference=invoice.internal_reference,
        linked_grn_id=invoice.linked_grn_id,
        total_exclusive=total_exclusive,
        vat_rate=invoice.vat_rate,
        vat_amount=total_vat,
        total_inclusive=total_inclusive,
        status=invoice.status or "DRAFT",  # Save as DRAFT
        payment_status="UNPAID",
        amount_paid=Decimal("0"),
        balance=balance,
        created_by=invoice.created_by
    )
    db.add(db_invoice)
    try:
        db.flush()
    except sqlalchemy.exc.IntegrityError as e:
        err_msg = str(e.orig) if e.orig else str(e)
        if "purchase_invoices_company_id_invoice_number_key" in err_msg or "UniqueViolation" in err_msg:
            # Roll back the failed insert and surface a clear, client-visible error.
            # Retrying with the same session without rollback would raise PendingRollbackError.
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A supplier invoice with this document number already exists. "
                       "Please refresh the page and try again."
            )
        else:
            raise

    # Link items (store batch data in items for later batching)
    for item in invoice_items:
        item.purchase_invoice_id = db_invoice.id
        db.add(item)

    sync_supplier_invoice_paid_from_allocations(db, db_invoice)
    # NOTE: NO stock ledger entries here - stock is added when batching

    db.commit()
    db.refresh(db_invoice)
    prepare_supplier_invoice_for_response(db, db_invoice)
    return db_invoice


@router.get("/invoice", response_model=List[SupplierInvoiceResponse])
def list_supplier_invoices(
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID"),
    supplier_id: Optional[UUID] = Query(None, description="Supplier ID"),
    date_from: Optional[date] = Query(None, description="Filter invoices from this date"),
    date_to: Optional[date] = Query(None, description="Filter invoices to this date"),
    invoice_number: Optional[str] = Query(None, description="Exact invoice number lookup (targeted search for returns)"),
    search: Optional[str] = Query(
        None,
        description="Contains match on system invoice no., supplier ref, or internal ref (use instead of loading all invoices)",
    ),
    item_id: Optional[UUID] = Query(None, description="Only invoices that include this line item"),
    limit: Optional[int] = Query(100, ge=1, le=500, description="Max results (default 100; use 50 for return flow)"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    List supplier invoices with filtering. Always applies limit to avoid full-history load.
    For return/credit-note flow: pass date_from=date_to=today and limit=50, or invoice_number for targeted lookup.
    Use `search` and/or `item_id` to narrow results without scanning the full supplier history.
    """
    query = db.query(SupplierInvoice).filter(SupplierInvoice.company_id == company_id)

    if branch_id:
        query = query.filter(SupplierInvoice.branch_id == branch_id)

    if supplier_id:
        query = query.filter(SupplierInvoice.supplier_id == supplier_id)

    if search is not None and str(search).strip():
        term = f"%{str(search).strip()}%"
        query = query.filter(
            or_(
                SupplierInvoice.invoice_number.ilike(term),
                SupplierInvoice.reference.ilike(term),
                SupplierInvoice.internal_reference.ilike(term),
            )
        )

    if item_id is not None:
        inv_ids_sq = (
            db.query(SupplierInvoiceItem.purchase_invoice_id)
            .filter(SupplierInvoiceItem.item_id == item_id)
            .distinct()
            .subquery()
        )
        query = query.filter(SupplierInvoice.id.in_(inv_ids_sq))

    if invoice_number is not None and str(invoice_number).strip():
        query = query.filter(SupplierInvoice.invoice_number == str(invoice_number).strip())
        if date_from:
            query = query.filter(SupplierInvoice.invoice_date >= date_from)
        if date_to:
            query = query.filter(SupplierInvoice.invoice_date <= date_to)
        query = query.order_by(SupplierInvoice.invoice_date.desc(), SupplierInvoice.created_at.desc()).limit(1)
    else:
        if date_from:
            query = query.filter(SupplierInvoice.invoice_date >= date_from)
        if date_to:
            query = query.filter(SupplierInvoice.invoice_date <= date_to)
        query = query.order_by(SupplierInvoice.invoice_date.desc(), SupplierInvoice.created_at.desc()).limit(limit or 100)

    # Eagerly load items relationship to avoid lazy loading issues
    invoices = query.options(
        selectinload(SupplierInvoice.items)
    ).all()
    
    # Load supplier and branch names, and ensure all invoices have document numbers
    for invoice in invoices:
        if invoice.supplier:
            invoice.supplier_name = invoice.supplier.name
        if invoice.branch:
            invoice.branch_name = invoice.branch.name
        # Load created_by user name
        created_by_user = db.query(User).filter(User.id == invoice.created_by).first()
        if created_by_user:
            invoice.created_by_name = created_by_user.full_name or created_by_user.email
        # Never mutate invoice_number to a display placeholder here — prepare_* flushes and would
        # persist duplicate "—" values, violating purchase_invoices_company_id_invoice_number_key.
        prepare_supplier_invoice_for_response(db, invoice)

    return invoices


@router.get("/invoice/{invoice_id}/pdf")
def get_supplier_invoice_pdf(
    invoice_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Optional[Tenant] = Depends(get_tenant_optional),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """Generate and return supplier invoice as PDF (Download PDF). On-demand only. Logo from company-assets or tenant-assets."""
    user = current_user_and_db[0]
    invoice = db.query(SupplierInvoice).options(
        selectinload(SupplierInvoice.items).selectinload(SupplierInvoiceItem.item)
    ).filter(SupplierInvoice.id == invoice_id).first()
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)
    prepare_supplier_invoice_for_response(db, invoice)
    company = db.query(Company).filter(Company.id == invoice.company_id).first()
    branch = db.query(Branch).filter(Branch.id == invoice.branch_id).first()
    supplier_name = invoice.supplier.name if invoice.supplier else "—"
    items_data = []
    for oi in invoice.items:
        item_name = oi.item.name if oi.item else "—"
        items_data.append({
            "item_name": item_name,
            "quantity": float(oi.quantity),
            "unit_name": oi.unit_name or "",
            "unit_price_exclusive": float(oi.unit_cost_exclusive or 0),
            "line_total_exclusive": float(oi.line_total_exclusive or 0),
            "line_total_inclusive": float(oi.line_total_inclusive or 0),
        })
    logo_path = getattr(company, "logo_url", None) if company else None
    company_logo_bytes = _resolve_asset_bytes(logo_path, tenant, master_db)
    try:
        pdf_bytes = build_supplier_invoice_pdf(
            company_name=company.name if company else "—",
            company_address=getattr(company, "address", None) if company else None,
            company_phone=getattr(company, "phone", None) if company else None,
            company_pin=getattr(company, "pin", None) if company else None,
            company_logo_bytes=company_logo_bytes,
            branch_name=branch.name if branch else None,
            branch_address=getattr(branch, "address", None) if branch else None,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            supplier_name=supplier_name,
            reference=invoice.reference,
            status=invoice.status,
            items=items_data,
            total_exclusive=invoice.total_exclusive or Decimal("0"),
            vat_amount=invoice.vat_amount or Decimal("0"),
            total_inclusive=invoice.total_inclusive or Decimal("0"),
            notes=invoice.reference,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate supplier invoice PDF: {str(e)}")
    filename = f"supplier-invoice-{invoice.invoice_number or invoice_id}.pdf".replace(" ", "-")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/invoice/{invoice_id}", response_model=SupplierInvoiceResponse)
def get_supplier_invoice(
    invoice_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get supplier invoice by ID with full item details (DRAFT or BATCHED; both can be viewed)."""
    user = current_user_and_db[0]
    # Load invoice with items and item relationships (similar to get_purchase_order)
    invoice = db.query(SupplierInvoice).options(
        selectinload(SupplierInvoice.items).selectinload(SupplierInvoiceItem.item)
    ).filter(SupplierInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)
    prepare_supplier_invoice_for_response(db, invoice)
    # Load supplier and branch names
    if invoice.supplier:
        invoice.supplier_name = invoice.supplier.name
    if invoice.branch:
        invoice.branch_name = invoice.branch.name
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == invoice.created_by).first()
    if created_by_user:
        invoice.created_by_name = created_by_user.full_name or created_by_user.email
    
    # Enhance items with full item details (similar to purchase order response)
    for invoice_item in invoice.items:
        if invoice_item.item:
            # Add item details to invoice_item object (will be serialized by response model)
            invoice_item.item_code = invoice_item.item.sku or ''
            invoice_item.item_name = invoice_item.item.name or ''
            invoice_item.item_category = invoice_item.item.category or ''
            invoice_item.base_unit = (getattr(invoice_item.item, "retail_unit", None) or invoice_item.item.base_unit or "").strip() or ""
            # If line has no VAT set (0 or None), use item master's VAT so UI shows correct rate from item settings
            if (invoice_item.vat_rate is None or float(invoice_item.vat_rate) == 0) and getattr(invoice_item.item, "vat_rate", None) is not None:
                pct = vat_rate_to_percent(invoice_item.item.vat_rate)
                invoice_item.vat_rate = Decimal(str(pct))
        else:
            # Item was deleted from catalog; provide fallback so UI doesn't break and frontend won't retry fetch
            invoice_item.item_code = getattr(invoice_item, "item_code", None) or ""
            invoice_item.item_name = getattr(invoice_item, "item_name", None) or "[Item no longer available]"
            invoice_item.item_category = getattr(invoice_item, "item_category", None) or ""
            invoice_item.base_unit = getattr(invoice_item, "base_unit", None) or "piece"
        # batch_data is already stored in the database and will be included in response

    # Payments recorded via Supplier Payments (multi-invoice payments share one reference on supplier_payment)
    alloc_rows = (
        db.query(SupplierPaymentAllocation, SupplierPayment)
        .join(SupplierPayment, SupplierPaymentAllocation.supplier_payment_id == SupplierPayment.id)
        .filter(SupplierPaymentAllocation.supplier_invoice_id == invoice_id)
        .order_by(SupplierPayment.payment_date.desc(), SupplierPayment.created_at.desc())
        .all()
    )
    invoice.payment_allocations = [
        SupplierInvoicePaymentAllocationInfo(
            supplier_payment_id=p.id,
            payment_date=p.payment_date,
            method=p.method,
            reference=p.reference,
            payment_total_amount=p.amount,
            allocated_amount=a.allocated_amount,
        )
        for a, p in alloc_rows
    ]

    return invoice


def _supplier_invoice_item_to_totals(db, invoice_id: UUID, item_data: SupplierInvoiceItemCreate):
    """Build SupplierInvoiceItem and return (invoice_item, line_total_exclusive, line_vat, item). Default unit to wholesale (pack) when missing."""
    item = db.query(Item).filter(Item.id == item_data.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
    if not getattr(item, "setup_complete", True):
        raise HTTPException(
            status_code=400,
            detail=f"Item '{item.name}' is not ready for transactions. Complete item setup (pack size, units) in Items before adding to a purchase."
        )
    unit_name_raw = (item_data.unit_name or "").strip()
    if not unit_name_raw:
        unit_name_raw = (item.wholesale_unit or item.retail_unit or "piece").strip() or "piece"
    effective_unit_name = unit_name_raw
    multiplier = get_unit_multiplier_from_item(item, effective_unit_name)
    if multiplier is None:
        raise HTTPException(status_code=404, detail=f"Unit '{effective_unit_name}' not found for item {item.name}")
    # For track_expiry items, require tracking fields based on company settings
    if getattr(item, "track_expiry", False):
        cfg = get_stock_validation_config(db, item.company_id)
        _require_batch_and_expiry_for_track_expiry_item(
            item.name or str(item_data.item_id),
            item_data.batches,
            from_dict=False,
            require_batch=bool(getattr(cfg, "require_batch_tracking", True)),
            require_expiry=bool(getattr(cfg, "require_expiry_tracking", True)),
        )
    # Accounting model:
    # - Keep original/gross unit cost in `unit_cost_exclusive` for inventory valuation and `last_unit_cost`.
    # - Apply discount only to *payable* totals by calculating net unit cost for line totals.
    disc_pct = Decimal(str(getattr(item_data, "discount_percent", 0) or 0))
    disc_pct = max(Decimal("0"), min(Decimal("100"), disc_pct))
    net_unit_cost_exclusive = item_data.unit_cost_exclusive * (Decimal("100") - disc_pct) / Decimal("100")

    line_total_exclusive = net_unit_cost_exclusive * item_data.quantity
    vat_rate_pct = Decimal(str(vat_rate_to_percent(item_data.vat_rate)))
    if vat_rate_pct == 0 and getattr(item, "vat_rate", None) is not None:
        vat_rate_pct = Decimal(str(vat_rate_to_percent(item.vat_rate)))
    line_vat = line_total_exclusive * vat_rate_pct / Decimal("100")
    line_total_inclusive = line_total_exclusive + line_vat
    batch_data_json = None
    if item_data.batches and len(item_data.batches) > 0:
        batch_data_json = json.dumps([{
            "batch_number": b.batch_number or "",
            "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
            "quantity": float(b.quantity),
            "unit_cost": float(b.unit_cost)
        } for b in item_data.batches])
    invoice_item = SupplierInvoiceItem(
        purchase_invoice_id=invoice_id,
        item_id=item_data.item_id,
        unit_name=effective_unit_name,
        quantity=item_data.quantity,
        unit_cost_exclusive=item_data.unit_cost_exclusive,
        vat_rate=vat_rate_pct,
        vat_amount=line_vat,
        line_total_exclusive=line_total_exclusive,
        line_total_inclusive=line_total_inclusive,
        batch_data=batch_data_json
    )
    return invoice_item, line_total_exclusive, line_vat, item


@router.post("/invoice/{invoice_id}/items", response_model=SupplierInvoiceResponse)
def add_supplier_invoice_item(
    invoice_id: UUID,
    item_data: SupplierInvoiceItemCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Add one line to an existing DRAFT supplier invoice. Rejects duplicate item_id. O(1) load with joinedload/selectinload."""
    from sqlalchemy.orm import joinedload
    user = current_user_and_db[0]
    invoice = (
        db.query(SupplierInvoice)
        .options(
            joinedload(SupplierInvoice.company),
            joinedload(SupplierInvoice.branch),
            joinedload(SupplierInvoice.creator),
            selectinload(SupplierInvoice.items).selectinload(SupplierInvoiceItem.item),
        )
        .filter(SupplierInvoice.id == invoice_id)
        .first()
    )
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot add items to invoice with status {invoice.status}. Only DRAFT invoices can be edited."
        )
    for line in invoice.items:
        if line.item_id == item_data.item_id:
            raise HTTPException(
                status_code=400,
                detail="Item already exists on this invoice. Edit the existing line or remove it first."
            )
    inv_item, line_excl, line_vat, new_item = _supplier_invoice_item_to_totals(db, invoice_id, item_data)
    # Central batch/expiry validation (expired reject, short-expiry per config)
    stock_validation_config = get_stock_validation_config(db, invoice.company_id)
    if new_item and getattr(new_item, "track_expiry", False) and item_data.batches:
        _validate_batches_central(
            new_item.name or str(item_data.item_id),
            new_item,
            item_data.batches,
            stock_validation_config,
            override=False,
            from_dict=False,
        )
    db.add(inv_item)
    db.flush()
    invoice.total_exclusive += line_excl
    invoice.vat_amount += line_vat
    invoice.total_inclusive = invoice.total_exclusive + invoice.vat_amount
    sync_supplier_invoice_paid_from_allocations(db, invoice)

    # Build response: use already-loaded invoice_item.item for existing lines; new_item for the new line. O(1).
    for invoice_item in invoice.items:
        it = invoice_item.item if invoice_item.item_id != item_data.item_id else new_item
        if it:
            invoice_item.item = it
            invoice_item.item_code = it.sku or ''
            invoice_item.item_name = it.name or ''
            invoice_item.item_category = getattr(it, "category", None) or ''
            invoice_item.base_unit = (getattr(it, "retail_unit", None) or getattr(it, "base_unit", None) or "").strip() or ""
            if (invoice_item.vat_rate is None or float(invoice_item.vat_rate) == 0) and getattr(it, "vat_rate", None) is not None:
                invoice_item.vat_rate = Decimal(str(vat_rate_to_percent(it.vat_rate)))
    if invoice.supplier:
        invoice.supplier_name = invoice.supplier.name
    if invoice.branch:
        invoice.branch_name = invoice.branch.name
    if invoice.creator:
        invoice.created_by_name = invoice.creator.full_name or invoice.creator.email

    prepare_supplier_invoice_for_response(db, invoice)
    db.commit()
    return invoice


@router.delete("/invoice/{invoice_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier_invoice_item(
    invoice_id: UUID,
    item_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Remove one line from a DRAFT supplier invoice."""
    invoice = (
        db.query(SupplierInvoice)
        .options(selectinload(SupplierInvoice.items))
        .filter(SupplierInvoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot remove items from invoice with status {invoice.status}. Only DRAFT invoices can be edited."
        )
    line = next((i for i in invoice.items if i.item_id == item_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Item not found on this invoice")
    invoice.total_exclusive -= line.line_total_exclusive
    invoice.vat_amount -= line.vat_amount
    invoice.total_inclusive -= line.line_total_inclusive
    sync_supplier_invoice_paid_from_allocations(db, invoice)
    db.delete(line)
    db.commit()
    return None


@router.patch("/invoice/{invoice_id}/items/{item_id}", response_model=SupplierInvoiceResponse)
def update_supplier_invoice_item(
    invoice_id: UUID,
    item_id: UUID,
    payload: SupplierInvoiceItemUpdate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Update one line on a DRAFT supplier invoice (qty, unit, cost, batch_data)."""
    invoice = (
        db.query(SupplierInvoice)
        .options(selectinload(SupplierInvoice.items))
        .filter(SupplierInvoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit items on invoice with status {invoice.status}. Only DRAFT invoices can be edited."
        )
    line = next((i for i in invoice.items if i.item_id == item_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Item not found on this invoice")
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Discount model:
    # - `line.unit_cost_exclusive` is stored as gross/original cost (used for inventory valuation & last_unit_cost).
    # - `line.line_total_exclusive` is stored as net after discount (used for payable/supplier ledger totals).
    # - If client does not send discount_percent on update, infer the effective discount from existing totals.
    existing_gross_base = (line.unit_cost_exclusive or Decimal("0")) * (line.quantity or Decimal("0"))
    existing_net_exclusive = line.line_total_exclusive or Decimal("0")
    inferred_disc_pct = Decimal("0")
    if existing_gross_base > 0:
        inferred_disc_pct = (existing_gross_base - existing_net_exclusive) * Decimal("100") / existing_gross_base
    inferred_disc_pct = max(Decimal("0"), min(Decimal("100"), inferred_disc_pct))

    disc_pct = Decimal(str(payload.discount_percent)) if payload.discount_percent is not None else inferred_disc_pct
    disc_pct = max(Decimal("0"), min(Decimal("100"), disc_pct))

    if payload.quantity is not None:
        line.quantity = payload.quantity
    if payload.unit_name is not None:
        line.unit_name = payload.unit_name
    if payload.unit_cost_exclusive is not None:
        new_cost = payload.unit_cost_exclusive
        if new_cost <= 0:
            mult = get_unit_multiplier_from_item(item, line.unit_name or payload.unit_name)
            if mult and mult > 0:
                last_base = CanonicalPricingService.get_last_purchase_cost(
                    db, item_id, invoice.branch_id, invoice.company_id
                )
                if last_base and float(last_base) > 0:
                    new_cost = last_base * Decimal(str(mult))
        line.unit_cost_exclusive = new_cost
        # Same rules as stock adjustment: cost outlier check
        mult = get_unit_multiplier_from_item(item, line.unit_name)
        if mult and float(new_cost) > 0:
            unit_cost_base = Decimal(str(new_cost)) / Decimal(str(mult))
            from app.dependencies import _user_has_permission
            outlier = is_cost_outlier_vs_weighted_average(
                db, invoice.company_id, invoice.branch_id, item_id, unit_cost_base
            )
            if outlier.get("is_outlier"):
                has_override = _user_has_permission(db, current_user_and_db[0].id, "inventory.cost_override")
                if not has_override:
                    baseline = outlier.get("baseline_cost")
                    deviation = outlier.get("deviation_pct")
                    threshold = outlier.get("threshold_pct")
                    detail_msg = (
                        f"Unit cost {unit_cost_base} deviates {deviation:.1f}% from branch weighted average "
                        f"{baseline}. Manager override required."
                    )
                    if threshold is not None:
                        detail_msg += f" (Threshold {threshold:.1f}%.)"
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={"code": "COST_OUTLIER_OVERRIDE_REQUIRED", "message": detail_msg},
                    )
    if payload.vat_rate is not None:
        line.vat_rate = Decimal(str(vat_rate_to_percent(payload.vat_rate)))
    if payload.batch_data is not None:
        line.batch_data = payload.batch_data if str(payload.batch_data).strip() else None
    elif payload.batches is not None and len(payload.batches) > 0:
        if getattr(item, "track_expiry", False):
            _require_batch_and_expiry_for_track_expiry_item(
                item.name or str(item_id),
                payload.batches,
                from_dict=False,
                require_batch=bool(getattr(stock_validation_config, "require_batch_tracking", True)),
                require_expiry=bool(getattr(stock_validation_config, "require_expiry_tracking", True)),
            )
            stock_validation_config = get_stock_validation_config(db, invoice.company_id)
            _validate_batches_central(
                item.name or str(item_id), item, payload.batches,
                stock_validation_config, override=False, from_dict=False,
            )
        line.batch_data = json.dumps([{
            "batch_number": b.batch_number or "",
            "expiry_date": b.expiry_date.isoformat() if getattr(b, "expiry_date", None) else None,
            "quantity": float(b.quantity),
            "unit_cost": float(b.unit_cost)
        } for b in payload.batches])

    net_unit_cost_exclusive = (line.unit_cost_exclusive or Decimal("0")) * (Decimal("100") - disc_pct) / Decimal("100")
    line_total_exclusive = net_unit_cost_exclusive * (line.quantity or Decimal("0"))
    line_vat = line_total_exclusive * (line.vat_rate or Decimal("0")) / Decimal("100")
    line.line_total_exclusive = line_total_exclusive
    line.vat_amount = line_vat
    line.line_total_inclusive = line_total_exclusive + line_vat

    total_exclusive = sum(l.line_total_exclusive for l in invoice.items)
    total_vat = sum(l.vat_amount for l in invoice.items)
    invoice.total_exclusive = total_exclusive
    invoice.vat_amount = total_vat
    invoice.total_inclusive = total_exclusive + total_vat
    sync_supplier_invoice_paid_from_allocations(db, invoice)
    db.commit()
    db.refresh(invoice)
    return get_supplier_invoice(invoice_id, request, current_user_and_db, db)


@router.put("/invoice/{invoice_id}", response_model=SupplierInvoiceResponse)
def update_supplier_invoice(
    invoice_id: UUID,
    invoice_update: SupplierInvoiceCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Update supplier invoice (only if status is DRAFT)
    
    Only DRAFT invoices can be updated. BATCHED invoices cannot be updated
    (stock already added to inventory).
    
    This endpoint is called:
    - When user clicks "Update Invoice" button
    - Automatically when changes occur (auto-save)
    """
    db_invoice = db.query(SupplierInvoice).filter(SupplierInvoice.id == invoice_id).first()
    if not db_invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if db_invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update invoice with status {db_invoice.status}. Only DRAFT invoices can be updated. Stock has already been added to inventory."
        )

    # Enforce per-supplier requirement for external supplier invoice number when configured.
    supplier = (
        db.query(Supplier)
        .filter(
            Supplier.id == invoice_update.supplier_id,
            Supplier.company_id == db_invoice.company_id,
        )
        .first()
    )
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if getattr(supplier, "requires_supplier_invoice_number", False):
        if not (invoice_update.supplier_invoice_number and str(invoice_update.supplier_invoice_number).strip()):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Supplier invoice number is required for this supplier.",
            )
    
    # Ensure DRAFT has system document number (SPV{BRANCH}-{N}); assign if missing
    if not db_invoice.invoice_number or not str(db_invoice.invoice_number).strip().startswith("SPV"):
        try:
            db_invoice.invoice_number = DocumentService.get_supplier_invoice_number(
                db, db_invoice.company_id, db_invoice.branch_id
            )
        except Exception:
            pass  # Branch may lack code; keep existing value
    
    # Update invoice fields
    db_invoice.supplier_id = invoice_update.supplier_id
    db_invoice.invoice_date = invoice_update.invoice_date
    db_invoice.reference = invoice_update.supplier_invoice_number or invoice_update.reference
    db_invoice.due_date = invoice_update.due_date
    db_invoice.internal_reference = invoice_update.internal_reference
    db_invoice.linked_grn_id = invoice_update.linked_grn_id
    db_invoice.vat_rate = invoice_update.vat_rate
    # amount_paid / payment_status for posted invoices come from supplier_payment_allocations only

    # Recalculate totals
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    
    # Delete existing items
    db.query(SupplierInvoiceItem).filter(SupplierInvoiceItem.purchase_invoice_id == invoice_id).delete()
    
    # Preload all items (no N+1)
    item_ids_update = [item_data.item_id for item_data in invoice_update.items]
    items_preloaded = db.query(Item).filter(Item.id.in_(item_ids_update), Item.company_id == db_invoice.company_id).all()
    items_map_update = {item.id: item for item in items_preloaded}
    stock_validation_config_update = get_stock_validation_config(db, db_invoice.company_id)
    
    # Add new items
    invoice_items = []
    for item_data in invoice_update.items:
        # Get item from preloaded map
        item = items_map_update.get(item_data.item_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        multiplier = get_unit_multiplier_from_item(item, item_data.unit_name)
        if multiplier is None:
            raise HTTPException(status_code=404, detail=f"Unit '{item_data.unit_name}' not found for item {item_data.item_id}")
        
        # Enforce tracking fields for items with Track Expiry enabled (company-level toggles decide what is required)
        if getattr(item, "track_expiry", False):
            _require_batch_and_expiry_for_track_expiry_item(
                item.name or str(item_data.item_id),
                item_data.batches,
                from_dict=False,
                require_batch=bool(getattr(stock_validation_config_update, "require_batch_tracking", True)),
                require_expiry=bool(getattr(stock_validation_config_update, "require_expiry_tracking", True)),
            )
            if item_data.batches:
                _validate_batches_central(
                    item.name or str(item_data.item_id), item, item_data.batches,
                    stock_validation_config_update, override=True, from_dict=False,
                )
        
        # Accounting model:
        # - Keep original/gross unit cost in `unit_cost_exclusive`.
        # - Apply discount only to payable totals (line totals) by calculating net unit cost.
        disc_pct = Decimal(str(getattr(item_data, "discount_percent", 0) or 0))
        disc_pct = max(Decimal("0"), min(Decimal("100"), disc_pct))
        net_unit_cost_exclusive = item_data.unit_cost_exclusive * (Decimal("100") - disc_pct) / Decimal("100")

        # Calculate line totals (VAT) — normalize vat_rate; use item master VAT if request sent 0
        line_total_exclusive = net_unit_cost_exclusive * item_data.quantity
        vat_rate_pct = Decimal(str(vat_rate_to_percent(item_data.vat_rate)))
        if vat_rate_pct == 0 and getattr(item, "vat_rate", None) is not None:
            vat_rate_pct = Decimal(str(vat_rate_to_percent(item.vat_rate)))
        line_vat = line_total_exclusive * vat_rate_pct / Decimal("100")
        line_total_inclusive = line_total_exclusive + line_vat
        
        # Store batch data as JSON for later batching
        batch_data_json = None
        if item_data.batches and len(item_data.batches) > 0:
            import json
            batch_data_json = json.dumps([{
                "batch_number": batch.batch_number or "",
                "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
                "quantity": float(batch.quantity),
                "unit_cost": float(batch.unit_cost)
            } for batch in item_data.batches])
        
        invoice_item = SupplierInvoiceItem(
            purchase_invoice_id=invoice_id,
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_cost_exclusive=item_data.unit_cost_exclusive,
            vat_rate=vat_rate_pct,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive,
            batch_data=batch_data_json  # Store batch data for later
        )
        invoice_items.append(invoice_item)
        db.add(invoice_item)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
    
    total_inclusive = total_exclusive + total_vat

    # Update invoice totals
    db_invoice.total_exclusive = total_exclusive
    db_invoice.vat_amount = total_vat
    db_invoice.total_inclusive = total_inclusive
    sync_supplier_invoice_paid_from_allocations(db, db_invoice)

    db.commit()
    db.refresh(db_invoice)
    
    # Load relationships for response
    if db_invoice.supplier:
        db_invoice.supplier_name = db_invoice.supplier.name
    if db_invoice.branch:
        db_invoice.branch_name = db_invoice.branch.name
    created_by_user = db.query(User).filter(User.id == db_invoice.created_by).first()
    if created_by_user:
        db_invoice.created_by_name = created_by_user.full_name or created_by_user.email
    
    # Enhance items with full item details (and backfill VAT from item master when line has 0)
    for invoice_item in db_invoice.items:
        if invoice_item.item:
            invoice_item.item_code = invoice_item.item.sku or ''
            invoice_item.item_name = invoice_item.item.name or ''
            invoice_item.item_category = invoice_item.item.category or ''
            invoice_item.base_unit = (getattr(invoice_item.item, "retail_unit", None) or invoice_item.item.base_unit or "").strip() or ""
            if (invoice_item.vat_rate is None or float(invoice_item.vat_rate) == 0) and getattr(invoice_item.item, "vat_rate", None) is not None:
                pct = vat_rate_to_percent(invoice_item.item.vat_rate)
                invoice_item.vat_rate = Decimal(str(pct))
        # batch_data is already stored in the database and will be included in response

    prepare_supplier_invoice_for_response(db, db_invoice)
    return db_invoice


@router.post("/invoice/{invoice_id}/batch", response_model=SupplierInvoiceResponse)
def batch_supplier_invoice(
    invoice_id: UUID,
    request: Request,
    body: Optional[BatchSupplierInvoiceBody] = Body(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Batch Supplier Invoice - Add Stock to Inventory

    This is the only path that writes to inventory_ledger and updates item_branch_snapshot
    (stock and search/price). Creating or saving a supplier invoice (DRAFT) does not update
    ledger or snapshot until this endpoint is called.

    Row-level lock on invoice prevents concurrent batch; status checked after lock.
    Only DRAFT invoices can be batched. Once batched, status changes to BATCHED.
    Ensures invoice has a system document number (SPV...) before batching; assigns one if missing.
    """
    import logging
    _log = logging.getLogger(__name__)
    user = current_user_and_db[0]
    from sqlalchemy.orm import joinedload

    # Lock the invoice row first (no joins) - PostgreSQL disallows FOR UPDATE with LEFT OUTER JOIN.
    invoice = (
        db.query(SupplierInvoice)
        .filter(SupplierInvoice.id == invoice_id)
        .with_for_update()
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Load relationships (row already locked; no FOR UPDATE to avoid outer-join error)
    invoice = (
        db.query(SupplierInvoice)
        .options(
            joinedload(SupplierInvoice.supplier),
            joinedload(SupplierInvoice.branch),
            joinedload(SupplierInvoice.creator),
            selectinload(SupplierInvoice.items).selectinload(SupplierInvoiceItem.item),
        )
        .filter(SupplierInvoice.id == invoice_id)
        .first()
    )
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", request)

    if invoice.status == "BATCHED":
        raise HTTPException(
            status_code=400,
            detail="Invoice is already batched. Stock has already been added to inventory."
        )
    
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot batch invoice with status {invoice.status}. Only DRAFT invoices can be batched."
        )
    
    # Ensure invoice has system document number (SPV{BRANCH}-{N}); assign if missing (e.g. legacy invoices)
    if not invoice.invoice_number or not str(invoice.invoice_number).strip().startswith("SPV"):
        try:
            invoice.invoice_number = DocumentService.get_supplier_invoice_number(
                db, invoice.company_id, invoice.branch_id
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot batch: could not assign document number. Ensure branch has a code. {e!s}"
            )
    
    if not invoice.items or len(invoice.items) == 0:
        raise HTTPException(
            status_code=400,
            detail="Invoice has no line items. Add items before batching."
        )

    stock_validation_config_batch = get_stock_validation_config(db, invoice.company_id)
    short_expiry_override_batch = bool(body and getattr(body, "short_expiry_override", False))
    if short_expiry_override_batch:
        from app.dependencies import _user_has_permission
        from app.api.users import _user_has_owner_or_admin_role
        if not _user_has_permission(db, user.id, "inventory.short_expiry_override") and not _user_has_owner_or_admin_role(db, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SHORT_EXPIRY_OVERRIDE_FORBIDDEN",
                    "message": "Only users with Short Expiry Override permission (e.g. Manager or Pharmacist) can accept short-expiry batches. Ask a manager to batch this invoice.",
                },
            )

    # Pre-pass: collect (item_id, unit_cost_base) pairs that need floor-price confirmation
    needs_confirm = []  # [(item_id, unit_cost_base, item_name, floor_price, margin_below_standard)]
    seen = set()

    for invoice_item in invoice.items:
        item = invoice_item.item
        if not item:
            continue
        multiplier = get_unit_multiplier_from_item(item, invoice_item.unit_name)
        if multiplier is None or multiplier <= 0:
            continue
        unit_costs_base = []
        if invoice_item.batch_data:
            try:
                batches = json.loads(invoice_item.batch_data)
                if batches:
                    for batch in batches:
                        qty = batch.get("quantity", 0)
                        uc = batch.get("unit_cost")
                        if uc is not None and float(qty) > 0:
                            unit_cost_base = Decimal(str(uc)) / multiplier
                            unit_costs_base.append(float(unit_cost_base))
                else:
                    unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
                    unit_costs_base.append(float(unit_cost_base))
            except (json.JSONDecodeError, TypeError):
                unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
                unit_costs_base.append(float(unit_cost_base))
        else:
            unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
            unit_costs_base.append(float(unit_cost_base))

        # Cost outlier control per item/branch before creating ledger entries
        outlier = is_cost_outlier_vs_weighted_average(
            db, invoice.company_id, invoice.branch_id, invoice_item.item_id, unit_cost_base
        )
        if outlier.get("is_outlier"):
            from app.dependencies import _user_has_permission

            has_override = _user_has_permission(
                db, invoice.created_by, "inventory.cost_override"
            )
            if not has_override:
                baseline = outlier.get("baseline_cost")
                deviation = outlier.get("deviation_pct")
                threshold = outlier.get("threshold_pct")
                item_name = getattr(item, "name", None) or str(invoice_item.item_id)
                detail_msg = (
                    f"Invoice unit cost {unit_cost_base} for item '{item_name}' deviates "
                    f"{deviation:.1f}% from branch weighted average {baseline}. Manager override required."
                )
                if threshold is not None:
                    detail_msg += f" (Threshold {threshold:.1f}%.)"
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail_msg,
                )

        item_name = getattr(item, "name", None) or str(invoice_item.item_id)
        for uc in unit_costs_base:
            if uc <= 0:
                continue
            key = (str(invoice_item.item_id), round(uc, 4))
            if key in seen:
                continue
            check = check_stock_adjustment_requires_confirmation(
                db, invoice_item.item_id, invoice.company_id, Decimal(str(uc))
            )
            if check.get("requires_confirmation"):
                seen.add(key)
                needs_confirm.append({
                    "item_id": str(invoice_item.item_id),
                    "item_name": item_name,
                    "unit_cost_base": uc,
                    "floor_price": check.get("floor_price"),
                    "margin_below_standard": check.get("margin_below_standard", False),
                })

    if needs_confirm:
        confirm_map = {}
        if body and body.confirmations:
            for c in body.confirmations:
                k = (str(c.item_id), round(float(c.unit_cost_base), 4))
                confirm_map[k] = float(c.unit_cost_base)
        missing = []
        for nc in needs_confirm:
            k = (nc["item_id"], round(nc["unit_cost_base"], 4))
            if k not in confirm_map:
                missing.append(nc)
                continue
            if abs(confirm_map[k] - nc["unit_cost_base"]) > 0.01:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "PRICE_CONFIRMATION_MISMATCH",
                        "message": f"Confirmation for {nc['item_name']} does not match. Expected unit cost {nc['unit_cost_base']}.",
                    },
                )
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PRICE_CONFIRMATION_REQUIRED",
                    "message": "Some items have a floor price or margin below standard. Re-enter the unit cost for each to confirm.",
                    "items": missing,
                },
            )

    # Process each item and add stock based on batch data
    ledger_entries = []
    
    for invoice_item in invoice.items:
        item = invoice_item.item
        if not item:
            raise HTTPException(
                status_code=400,
                detail=f"Item {invoice_item.item_id} not found. Cannot batch."
            )
        
        multiplier = get_unit_multiplier_from_item(item, invoice_item.unit_name)
        if multiplier is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unit '{invoice_item.unit_name}' not found for item {item.name}. Cannot batch."
            )
        
        # Enforce tracking fields for items with Track Expiry enabled (before batching)
        if getattr(item, "track_expiry", False):
            if not (invoice_item.batch_data and str(invoice_item.batch_data).strip()):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Item '{item.name}' has Track Expiry enabled. Use 'Manage Batches' and enter "
                        "at least one batch with the required tracking fields before batching."
                    ),
                )
            try:
                batches_validate = json.loads(invoice_item.batch_data)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Item '{item.name}' has invalid batch data. Use 'Manage Batches' and enter "
                        "the required tracking fields for each batch."
                    ),
                )
            if not batches_validate:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Item '{item.name}' has Track Expiry enabled. Use 'Manage Batches' and enter "
                        "at least one batch with the required tracking fields before batching."
                    ),
                )
            _require_batch_and_expiry_for_track_expiry_item(
                item.name or str(invoice_item.item_id),
                batches_validate,
                from_dict=True,
                require_batch=bool(getattr(stock_validation_config_batch, "require_batch_tracking", True)),
                require_expiry=bool(getattr(stock_validation_config_batch, "require_expiry_tracking", True)),
            )
            _validate_batches_central(
                item.name or str(invoice_item.item_id),
                item,
                batches_validate,
                stock_validation_config_batch,
                override=short_expiry_override_batch,
                from_dict=True,
            )
        
        # Parse batch data from JSON
        if invoice_item.batch_data:
            try:
                batches = json.loads(invoice_item.batch_data)
                # Empty batch list = no distribution; add full quantity as single entry so stock is still added
                if not batches:
                    quantity_base = InventoryService.convert_to_base_units(
                        db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
                    )
                    unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
                    ledger_entry = InventoryLedger(
                        company_id=invoice.company_id,
                        branch_id=invoice.branch_id,
                        item_id=invoice_item.item_id,
                        batch_number=None,
                        expiry_date=None,
                        transaction_type="PURCHASE",
                        reference_type="purchase_invoice",
                        reference_id=invoice.id,
                        document_number=invoice.invoice_number,
                        quantity_delta=quantity_base,
                        unit_cost=unit_cost_base,
                        total_cost=unit_cost_base * quantity_base,
                        batch_cost=unit_cost_base,
                        remaining_quantity=quantity_base,
                        is_batch_tracked=False,
                        created_by=invoice.created_by
                    )
                    ledger_entries.append(ledger_entry)
                    continue
                # Validate batch quantities sum to item quantity
                total_batch_quantity = sum(batch.get("quantity", 0) for batch in batches)
                if abs(total_batch_quantity - float(invoice_item.quantity)) > 0.01:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Sum of batch quantities ({total_batch_quantity}) must equal item quantity ({invoice_item.quantity}) for item {item.name}"
                    )
                
                # Create ledger entries for each batch
                for batch_idx, batch in enumerate(batches):
                    expiry_date = None
                    if batch.get("expiry_date"):
                        expiry_date = datetime.fromisoformat(batch["expiry_date"]).date()
                    
                    quantity_base = int(float(batch["quantity"]) * float(multiplier))
                    unit_cost_base = Decimal(str(batch["unit_cost"])) / multiplier
                    
                    ledger_entry = InventoryLedger(
                        company_id=invoice.company_id,
                        branch_id=invoice.branch_id,
                        item_id=invoice_item.item_id,
                        batch_number=batch.get("batch_number") or None,
                        expiry_date=expiry_date,
                        transaction_type="PURCHASE",
                        reference_type="purchase_invoice",
                        reference_id=invoice.id,
                        document_number=invoice.invoice_number,
                        quantity_delta=quantity_base,  # Positive = add stock
                        unit_cost=unit_cost_base,
                        total_cost=unit_cost_base * quantity_base,
                        batch_cost=unit_cost_base,
                        remaining_quantity=quantity_base,
                        is_batch_tracked=bool(batch.get("batch_number")),
                        split_sequence=batch_idx,
                        created_by=invoice.created_by
                    )
                    ledger_entries.append(ledger_entry)
            except json.JSONDecodeError:
                # If batch_data is invalid JSON, create single entry without batch
                quantity_base = InventoryService.convert_to_base_units(
                    db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
                )
                unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
                
                ledger_entry = InventoryLedger(
                    company_id=invoice.company_id,
                    branch_id=invoice.branch_id,
                    item_id=invoice_item.item_id,
                    batch_number=None,
                    expiry_date=None,
                    transaction_type="PURCHASE",
                    reference_type="purchase_invoice",
                    reference_id=invoice.id,
                    document_number=invoice.invoice_number,
                    quantity_delta=quantity_base,
                    unit_cost=unit_cost_base,
                    total_cost=unit_cost_base * quantity_base,
                    batch_cost=unit_cost_base,
                    remaining_quantity=quantity_base,
                    is_batch_tracked=False,
                    created_by=invoice.created_by
                )
                ledger_entries.append(ledger_entry)
        else:
            # No batch data - create single entry
            quantity_base = InventoryService.convert_to_base_units(
                db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
            )
            unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
            
            ledger_entry = InventoryLedger(
                company_id=invoice.company_id,
                branch_id=invoice.branch_id,
                item_id=invoice_item.item_id,
                batch_number=None,
                expiry_date=None,
                transaction_type="PURCHASE",
                reference_type="purchase_invoice",
                reference_id=invoice.id,
                document_number=invoice.invoice_number,
                quantity_delta=quantity_base,
                unit_cost=unit_cost_base,
                total_cost=unit_cost_base * quantity_base,
                batch_cost=unit_cost_base,
                remaining_quantity=quantity_base,
                is_batch_tracked=False,
                created_by=invoice.created_by
            )
            ledger_entries.append(ledger_entry)

    try:
        # Add all ledger entries
        for entry in ledger_entries:
            db.add(entry)

        db.flush()

        # Update snapshots in same transaction
        for entry in ledger_entries:
            SnapshotService.upsert_inventory_balance(
                db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta,
                document_number=getattr(entry, "document_number", None) or invoice.invoice_number,
            )
        # Update last unit cost per item from invoice (cost per base unit; purchase snapshot for reporting)
        items_updated_for_cost = set()
        for inv_item in invoice.items:
            item = inv_item.item
            if not item:
                item = db.query(Item).filter(Item.id == inv_item.item_id, Item.company_id == invoice.company_id).first()
            if not item:
                continue
            multiplier = get_unit_multiplier_from_item(item, inv_item.unit_name)
            if multiplier is None or multiplier <= 0:
                continue
            unit_cost_base = Decimal(str(inv_item.unit_cost_exclusive)) / multiplier
            SnapshotService.upsert_purchase_snapshot(
                db, invoice.company_id, invoice.branch_id, inv_item.item_id,
                unit_cost_base, invoice.created_at, invoice.supplier_id
            )
            items_updated_for_cost.add(inv_item.item_id)
        db.flush()
        # Refresh item_branch_snapshot for every item that got ledger entries (search/price stay in sync)
        items_to_refresh = items_updated_for_cost | {e.item_id for e in ledger_entries}
        for iid in items_to_refresh:
            SnapshotRefreshService.refresh_item_sync(db, invoice.company_id, invoice.branch_id, iid)

        # Update invoice status to BATCHED
        invoice.status = "BATCHED"

        # Supplier ledger: debit = we owe (invoice posted)
        SupplierLedgerService.create_entry(
            db,
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            supplier_id=invoice.supplier_id,
            entry_date=invoice.invoice_date,
            entry_type="invoice",
            reference_id=invoice.id,
            debit=invoice.total_inclusive or Decimal("0"),
            credit=Decimal("0"),
        )

        # Order book lifecycle: mark ORDERED entries as received and archive to history (CLOSED)
        invoice_item_ids = list({e.item_id for e in ledger_entries})
        OrderBookService.mark_items_received(
            db, invoice.company_id, invoice.branch_id, invoice_item_ids,
            received_at=datetime.now(timezone.utc),
        )

        db.commit()
        db.refresh(invoice)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        _log.exception("Batch supplier invoice failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    
    # Response from eagerly loaded relations (no extra queries)
    if invoice.supplier:
        invoice.supplier_name = invoice.supplier.name
    if invoice.branch:
        invoice.branch_name = invoice.branch.name
    if invoice.creator:
        invoice.created_by_name = invoice.creator.full_name or invoice.creator.email

    prepare_supplier_invoice_for_response(db, invoice)
    return invoice


@router.put("/invoice/{invoice_id}/payment", response_model=SupplierInvoiceResponse)
def update_invoice_payment(
    invoice_id: UUID,
    amount_paid: Optional[Decimal] = Query(None, description="Deprecated — ignored"),
    payment_reference: Optional[str] = Query(
        None,
        max_length=255,
        description="Deprecated — ignored",
    ),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Removed: invoice amounts are derived from supplier_payment_allocations only.
    Use POST /suppliers/payments with allocations (see Supplier Payments in the app).
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Direct invoice payment updates are no longer supported. "
            "Record supplier payments via POST /suppliers/payments with allocations (same as Supplier Payments)."
        ),
    )


@router.delete("/invoice/{invoice_id}", status_code=status.HTTP_200_OK)
def delete_supplier_invoice(
    invoice_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Delete Supplier Invoice (Only if DRAFT status)
    
    Only DRAFT invoices can be deleted. BATCHED invoices cannot be deleted
    (stock already added to inventory).
    """
    invoice = db.query(SupplierInvoice).filter(SupplierInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete invoice with status {invoice.status}. Only DRAFT invoices can be deleted."
        )
    
    # Delete invoice items (cascade should handle this, but explicit is safer)
    db.query(SupplierInvoiceItem).filter(SupplierInvoiceItem.purchase_invoice_id == invoice_id).delete()
    
    # Delete invoice
    db.delete(invoice)
    db.commit()
    
    return {"message": "Invoice deleted successfully", "deleted": True}


# =====================================================
# PURCHASE ORDERS
# =====================================================

@router.post("/order", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    order: PurchaseOrderCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create Purchase Order
    
    Purchase orders are created before receiving goods.
    They can later be converted to GRN when goods are received.
    """
    # Generate order number
    order_no = DocumentService.get_purchase_order_number(
        db, order.company_id, order.branch_id
    )
    
    total_amount = Decimal("0")
    order_items = []
    
    for item_data in order.items:
        total_item_price = Decimal(str(item_data.unit_price)) * item_data.quantity
        total_amount += total_item_price
        
        order_item = PurchaseOrderItem(
            purchase_order_id=None,  # Will be set after order creation
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_price=item_data.unit_price,
            total_price=total_item_price
        )
        order_items.append(order_item)
    
    # Create purchase order
    db_order = PurchaseOrder(
        company_id=order.company_id,
        branch_id=order.branch_id,
        supplier_id=order.supplier_id,
        order_number=order_no,
        order_date=order.order_date,
        reference=order.reference,
        notes=order.notes,
        total_amount=total_amount,
        status=order.status or "PENDING",
        created_by=order.created_by,
        is_official=getattr(order, "is_official", True),
    )
    db.add(db_order)
    db.flush()
    
    # Link items to order
    for item in order_items:
        item.purchase_order_id = db_order.id
        db.add(item)

    db.flush()
    for item in order_items:
        SnapshotService.upsert_search_snapshot_last_order(
            db, order.company_id, order.branch_id, item.item_id, db_order.order_date
        )

    # Add each PO line to the order book as ORDERED (one row per branch/item/entry_date)
    entry_date = db_order.order_date if isinstance(db_order.order_date, date) else db_order.order_date.date()
    for item in order_items:
        existing = (
            db.query(DailyOrderBook)
            .filter(
                DailyOrderBook.branch_id == order.branch_id,
                DailyOrderBook.item_id == item.item_id,
                DailyOrderBook.entry_date == entry_date,
                DailyOrderBook.status.in_(["PENDING", "ORDERED"]),
            )
            .first()
        )
        if existing:
            existing.status = "ORDERED"
            existing.purchase_order_id = db_order.id
            existing.source_reference_type = "purchase_order"
            existing.source_reference_id = db_order.id
            existing.quantity_needed = (existing.quantity_needed or 0) + item.quantity
            existing.supplier_id = db_order.supplier_id
            existing.unit_name = item.unit_name
        else:
            ob_entry = DailyOrderBook(
                company_id=order.company_id,
                branch_id=order.branch_id,
                item_id=item.item_id,
                entry_date=entry_date,
                supplier_id=db_order.supplier_id,
                quantity_needed=item.quantity,
                unit_name=item.unit_name,
                reason="DIRECT_PO",
                source_reference_type="purchase_order",
                source_reference_id=db_order.id,
                status="ORDERED",
                purchase_order_id=db_order.id,
                created_by=order.created_by,
            )
            db.add(ob_entry)

    db.commit()
    db.refresh(db_order)
    
    # Load relationships for response
    if db_order.supplier:
        db_order.supplier_name = db_order.supplier.name
    if db_order.branch:
        db_order.branch_name = db_order.branch.name
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == db_order.created_by).first()
    if created_by_user:
        db_order.created_by_name = created_by_user.full_name or created_by_user.email
    
    return db_order


@router.get("/order", response_model=List[PurchaseOrderResponse])
def list_purchase_orders(
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID"),
    supplier_id: Optional[UUID] = Query(None, description="Supplier ID"),
    date_from: Optional[date] = Query(None, description="Filter orders from this date"),
    date_to: Optional[date] = Query(None, description="Filter orders to this date"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, APPROVED, RECEIVED, CANCELLED)"),
    db: Session = Depends(get_tenant_db)
):
    """
    List purchase orders with filtering
    
    Filters:
    - branch_id: Filter by branch
    - supplier_id: Filter by supplier
    - date_from: Filter orders from this date
    - date_to: Filter orders to this date
    - status: Filter by status (PENDING, APPROVED, RECEIVED, CANCELLED)
    """
    query = db.query(PurchaseOrder).filter(PurchaseOrder.company_id == company_id)
    
    if branch_id:
        query = query.filter(PurchaseOrder.branch_id == branch_id)
    
    if supplier_id:
        query = query.filter(PurchaseOrder.supplier_id == supplier_id)
    
    # Default to today when no date range given so we don't return all orders
    today_default = date.today()
    use_from = date_from if date_from is not None else today_default
    use_to = date_to if date_to is not None else today_default
    query = query.filter(PurchaseOrder.order_date >= use_from, PurchaseOrder.order_date <= use_to)
    
    if status:
        query = query.filter(PurchaseOrder.status == status)
    
    # Order by date descending (newest first)
    # Eagerly load items relationship to avoid lazy loading issues
    orders = query.options(
        selectinload(PurchaseOrder.items)
    ).order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc()).all()
    
    # Load supplier, branch, user names, approved_by_name
    for order in orders:
        if order.supplier:
            order.supplier_name = order.supplier.name
        if order.branch:
            order.branch_name = order.branch.name
        created_by_user = db.query(User).filter(User.id == order.created_by).first()
        if created_by_user:
            order.created_by_name = created_by_user.full_name or created_by_user.email
        if order.approved_by_user_id:
            approver = db.query(User).filter(User.id == order.approved_by_user_id).first()
            if approver:
                order.approved_by_name = approver.full_name or approver.email
        for oi in order.items:
            if oi.item:
                oi.is_controlled = getattr(oi.item, "is_controlled", False)
    
    return orders


@router.get("/order/{order_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(
    order_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Optional[Tenant] = Depends(get_tenant_optional),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """Get purchase order by ID with full item details"""
    user = current_user_and_db[0]
    # Load order with items and item relationships
    order = db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.item)
    ).filter(PurchaseOrder.id == order_id).first()
    require_document_belongs_to_user_company(db, user, order, "Purchase order", request)
    # Load supplier, branch, and user names
    if order.supplier:
        order.supplier_name = order.supplier.name
    if order.branch:
        order.branch_name = order.branch.name
    # Logo URL for print (company-assets or tenant-assets; works without tenant)
    company = getattr(order, "company", None) or db.query(Company).filter(Company.id == order.company_id).first()
    logo_path = getattr(company, "logo_url", None) if company else None
    if logo_path and _is_storage_path(logo_path):
        order.logo_url = _resolve_signed_url(logo_path, tenant, master_db)
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == order.created_by).first()
    if created_by_user:
        order.created_by_name = created_by_user.full_name or created_by_user.email
    
    # Enhance items with full item details (similar to phAMACore response)
    for order_item in order.items:
        if order_item.item:
            # Add item details to order_item object (will be serialized by response model)
            order_item.item_code = order_item.item.sku or ''
            order_item.item_name = order_item.item.name or ''
            order_item.item_category = order_item.item.category or ''
            order_item.base_unit = (getattr(order_item.item, "retail_unit", None) or order_item.item.base_unit or "").strip() or ""
            order_item.is_controlled = getattr(order_item.item, 'is_controlled', False)
            # Cost from inventory_ledger only (never from items table)
            from app.services.canonical_pricing import CanonicalPricingService
            order_item.default_cost = float(CanonicalPricingService.get_best_available_cost(db, order_item.item_id, order.branch_id, order.company_id)) if order.branch_id else 0.0
    if order.approved_by_user_id:
        approver = db.query(User).filter(User.id == order.approved_by_user_id).first()
        if approver:
            order.approved_by_name = approver.full_name or approver.email
    return order


@router.post("/order/{order_id}/items", response_model=PurchaseOrderResponse)
def add_purchase_order_item(
    order_id: UUID,
    item_data: PurchaseOrderItemCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Optional[Tenant] = Depends(get_tenant_optional),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """Add one line to an existing PENDING purchase order. Rejects duplicate item_id. O(1) load with joinedload/selectinload."""
    from sqlalchemy.orm import joinedload
    user = current_user_and_db[0]
    order = (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.company),
            joinedload(PurchaseOrder.branch),
            joinedload(PurchaseOrder.supplier),
            joinedload(PurchaseOrder.creator),
            joinedload(PurchaseOrder.approved_by_user),
            selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.item),
        )
        .filter(PurchaseOrder.id == order_id)
        .first()
    )
    require_document_belongs_to_user_company(db, user, order, "Purchase order", request)
    if order.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot add items to order with status {order.status}. Only PENDING orders can be edited."
        )
    for line in order.items:
        if line.item_id == item_data.item_id:
            raise HTTPException(
                status_code=400,
                detail="Item already on this order. Edit the existing line or remove it first."
            )
    total_item_price = Decimal(str(item_data.unit_price)) * item_data.quantity
    order_item = PurchaseOrderItem(
        purchase_order_id=order_id,
        item_id=item_data.item_id,
        unit_name=item_data.unit_name,
        quantity=item_data.quantity,
        unit_price=item_data.unit_price,
        total_price=total_item_price
    )
    db.add(order_item)
    db.flush()
    order.total_amount = (order.total_amount or Decimal("0")) + total_item_price
    entry_date = order.order_date if hasattr(order.order_date, 'date') else order.order_date
    if hasattr(entry_date, 'date'):
        entry_date = entry_date.date()
    existing = (
        db.query(DailyOrderBook)
        .filter(
            DailyOrderBook.branch_id == order.branch_id,
            DailyOrderBook.item_id == item_data.item_id,
            DailyOrderBook.entry_date == entry_date,
            DailyOrderBook.status.in_(["PENDING", "ORDERED"]),
        )
        .first()
    )
    if existing:
        existing.status = "ORDERED"
        existing.purchase_order_id = order.id
        existing.source_reference_type = "purchase_order"
        existing.source_reference_id = order.id
        existing.quantity_needed = (existing.quantity_needed or 0) + item_data.quantity
        existing.supplier_id = order.supplier_id
        existing.unit_name = item_data.unit_name
    else:
        ob_entry = DailyOrderBook(
            company_id=order.company_id,
            branch_id=order.branch_id,
            item_id=item_data.item_id,
            entry_date=entry_date,
            supplier_id=order.supplier_id,
            quantity_needed=float(item_data.quantity),
            unit_name=item_data.unit_name,
            reason="DIRECT_PO",
            status="ORDERED",
            purchase_order_id=order.id,
            source_reference_type="purchase_order",
            source_reference_id=order.id,
            created_by=order.created_by,
        )
        db.add(ob_entry)

    # Build response: use already-loaded order_item.item for existing lines; single Item fetch for new line only. O(1).
    new_item = db.query(Item).filter(Item.id == item_data.item_id).first()
    for order_item in order.items:
        it = order_item.item if order_item.item_id != item_data.item_id else new_item
        if it:
            order_item.item = it
            order_item.item_code = it.sku or ''
            order_item.item_name = it.name or ''
            order_item.item_category = getattr(it, "category", None) or ''
            order_item.base_unit = (getattr(it, "retail_unit", None) or getattr(it, "base_unit", None) or "").strip() or ""
            order_item.is_controlled = getattr(it, "is_controlled", False)
            if order_item.item_id == item_data.item_id and order.branch_id:
                from app.services.canonical_pricing import CanonicalPricingService
                order_item.default_cost = float(CanonicalPricingService.get_best_available_cost(db, order_item.item_id, order.branch_id, order.company_id))
            else:
                order_item.default_cost = 0.0
        else:
            order_item.default_cost = 0.0
    if order.supplier:
        order.supplier_name = order.supplier.name
    if order.branch:
        order.branch_name = order.branch.name
    logo_path = getattr(order.company, "logo_url", None) if order.company else None
    if logo_path and _is_storage_path(logo_path):
        order.logo_url = _resolve_signed_url(logo_path, tenant, master_db)
    if order.creator:
        order.created_by_name = order.creator.full_name or order.creator.email
    if order.approved_by_user:
        order.approved_by_name = order.approved_by_user.full_name or order.approved_by_user.email

    db.commit()
    return order


@router.delete("/order/{order_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order_item(
    order_id: UUID,
    item_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Remove one line from a PENDING purchase order."""
    order = (
        db.query(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
        .filter(PurchaseOrder.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot remove items from order with status {order.status}. Only PENDING orders can be edited."
        )
    line = next((i for i in order.items if i.item_id == item_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Item not found on this order")
    order.total_amount = (order.total_amount or Decimal("0")) - line.total_price
    db.delete(line)
    db.commit()
    return None


@router.put("/order/{order_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(order_id: UUID, order_update: PurchaseOrderCreate, db: Session = Depends(get_tenant_db)):
    """Update purchase order (only if status is PENDING)"""
    db_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if db_order.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update purchase order with status {db_order.status}. Only PENDING orders can be updated."
        )
    
    # Update order fields
    db_order.supplier_id = order_update.supplier_id
    db_order.order_date = order_update.order_date
    db_order.reference = order_update.reference
    db_order.notes = order_update.notes
    db_order.status = order_update.status or "PENDING"
    if hasattr(order_update, "is_official") and order_update.is_official is not None:
        db_order.is_official = order_update.is_official
    
    # Delete existing items
    db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order_id).delete()
    
    # Add new items
    total_amount = Decimal("0")
    for item_data in order_update.items:
        total_item_price = Decimal(str(item_data.unit_price)) * item_data.quantity
        total_amount += total_item_price
        
        order_item = PurchaseOrderItem(
            purchase_order_id=order_id,
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_price=item_data.unit_price,
            total_price=total_item_price
        )
        db.add(order_item)
    
    db_order.total_amount = total_amount
    db.commit()
    db.refresh(db_order)
    
    # Load supplier, branch, and user names
    if db_order.supplier:
        db_order.supplier_name = db_order.supplier.name
    if db_order.branch:
        db_order.branch_name = db_order.branch.name
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == db_order.created_by).first()
    if created_by_user:
        db_order.created_by_name = created_by_user.full_name or created_by_user.email
    
    return db_order


def _tenant_for_stored_path(master_db: Session, stored_path: Optional[str]) -> Optional[Tenant]:
    """Resolve Tenant for stored_path (tenant-assets/{tenant_id}/...) for legacy asset access."""
    if not stored_path or not str(stored_path).startswith("tenant-assets/"):
        return None
    path_tid = tenant_id_from_stored_path(stored_path)
    if not path_tid:
        return None
    try:
        return master_db.query(Tenant).filter(Tenant.id == UUID(str(path_tid))).first()
    except (ValueError, TypeError):
        return None


def _is_storage_path(path: Optional[str]) -> bool:
    """True if path is company-assets/, user-assets/, or tenant-assets/ (stored in DB)."""
    if not path or not isinstance(path, str):
        return False
    p = path.strip()
    return p.startswith("company-assets/") or p.startswith("user-assets/") or p.startswith("tenant-assets/")


def _resolve_asset_bytes(
    stored_path: Optional[str],
    tenant: Optional[Any],
    master_db: Session,
) -> Optional[bytes]:
    """
    Resolve asset bytes from stored path (company-assets/, user-assets/, or tenant-assets/).
    Prefers path-based download (no tenant) so company/user assets work; falls back to tenant for legacy paths.
    """
    raw = str(stored_path or "").strip()
    if not raw:
        return None
    # Support already-signed/absolute asset URLs (defensive for migrated data).
    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(raw)
            if resp.status_code == 200 and resp.content:
                return bytes(resp.content)
        except Exception:
            return None
        return None
    if not _is_storage_path(raw):
        return None
    # First try without tenant (works for company-assets, user-assets, and tenant-assets with global client)
    data = download_file(raw, tenant=None)
    if data is not None:
        return data
    if not raw.startswith("tenant-assets/"):
        # For company-assets/user-assets, authenticated download can fail in some envs;
        # fallback to signed URL then fetch bytes over HTTPS.
        signed = _resolve_signed_url(raw, tenant, master_db)
        if signed:
            try:
                with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                    resp = client.get(signed)
                if resp.status_code == 200 and resp.content:
                    return bytes(resp.content)
            except Exception:
                return None
        return None
    if tenant is not None:
        data = download_file(raw, tenant=tenant)
        if data is not None:
            return data
    if _legacy_path_tenant_fallback_enabled():
        path_tenant = _tenant_for_stored_path(master_db, raw)
        if path_tenant:
            data = download_file_with_path_tenant(raw, path_tenant)
            if data is not None:
                return data
    # Last resort for tenant-assets too: signed URL fetch.
    signed = _resolve_signed_url(raw, tenant, master_db)
    if signed:
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(signed)
            if resp.status_code == 200 and resp.content:
                return bytes(resp.content)
        except Exception:
            return None
    return None


def _resolve_signed_url(
    stored_path: Optional[str],
    tenant: Optional[Any],
    master_db: Session,
) -> Optional[str]:
    """Resolve signed URL for stored path (company-assets/, user-assets/, or tenant-assets/). Works without tenant."""
    if not _is_storage_path(stored_path):
        return None
    url = get_signed_url(stored_path, tenant=None)
    if url:
        return url
    if tenant is not None:
        url = get_signed_url(stored_path, tenant=tenant)
        if url:
            return url
    if _legacy_path_tenant_fallback_enabled() and str(stored_path).startswith("tenant-assets/"):
        path_tenant = _tenant_for_stored_path(master_db, stored_path)
        if path_tenant:
            return get_signed_url_with_path_tenant(stored_path, path_tenant)
    return None


@router.patch("/order/{order_id}/approve", response_model=PurchaseOrderResponse)
def approve_purchase_order(
    order_id: UUID,
    tenant: Tenant = Depends(get_tenant_or_default),
    user_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """
    Approve a purchase order. Sets status=APPROVED, approved_by_user_id, approved_at,
    generates immutable PDF (logo, stamp, approver signature), uploads to Supabase, sets pdf_path.
    Requires tenant (X-Tenant-ID/X-Tenant-Subdomain or default DB as tenant) so PDF can be stored.
    """
    current_user, _ = user_db
    db_order = db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.item),
        selectinload(PurchaseOrder.company),
        selectinload(PurchaseOrder.branch),
        selectinload(PurchaseOrder.supplier),
    ).filter(PurchaseOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if db_order.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Only PENDING orders can be approved. Current status: {db_order.status}",
        )
    now = datetime.now(timezone.utc)
    db_order.status = "APPROVED"
    db_order.approved_by_user_id = current_user.id
    db_order.approved_at = now
    db.flush()
    # Load document_branding and stamp path
    branding_row = db.query(CompanySetting).filter(
        CompanySetting.company_id == db_order.company_id,
        CompanySetting.setting_key == "document_branding",
    ).first()
    try:
        document_branding = json.loads(branding_row.setting_value or "{}") if branding_row else {}
    except json.JSONDecodeError:
        document_branding = {}
    stamp_path = document_branding.get("stamp_url")
    company = db_order.company
    branch = db_order.branch
    approver = current_user
    items_data = []
    for oi in db_order.items:
        items_data.append({
            "item_code": oi.item.sku if oi.item else None,
            "item_name": oi.item.name if oi.item else None,
            "quantity": float(oi.quantity),
            "unit_name": oi.unit_name,
            "unit_price": float(oi.unit_price),
            "total_price": float(oi.total_price),
            "is_controlled": getattr(oi.item, "is_controlled", False) if oi.item else False,
        })
    order_dt = db_order.order_date
    if hasattr(order_dt, "isoformat") and not isinstance(order_dt, datetime):
        order_dt = datetime.combine(order_dt, datetime.min.time().replace(tzinfo=timezone.utc))

    # Resolve logo from company (logo_url), stamp from document_branding (stamp_url), signature from user (signature_path)
    # Supports company-assets/, user-assets/, and tenant-assets/ paths; fallback to tenant for legacy
    company_logo_path = getattr(company, "logo_url", None) if company else None
    company_logo_bytes = _resolve_asset_bytes(company_logo_path, tenant, master_db)
    stamp_bytes = _resolve_asset_bytes(stamp_path, tenant, master_db)
    approver_sig_path = getattr(approver, "signature_path", None)
    signature_bytes = _resolve_asset_bytes(approver_sig_path, tenant, master_db)

    pdf_bytes = build_po_pdf(
        company_name=company.name or "—",
        company_address=company.address,
        company_phone=company.phone,
        company_pin=company.pin,
        company_logo_path=company.logo_url,
        company_logo_bytes=company_logo_bytes,
        branch_name=branch.name if branch else None,
        branch_address=branch.address if branch else None,
        order_number=db_order.order_number,
        order_date=order_dt,
        supplier_name=db_order.supplier.name if db_order.supplier else "—",
        reference=db_order.reference,
        items=items_data,
        total_amount=db_order.total_amount or Decimal("0"),
        document_branding=document_branding,
        stamp_path=stamp_path,
        stamp_bytes=stamp_bytes,
        approver_name=approver.full_name or approver.email,
        approver_designation=getattr(approver, "designation", None),
        approver_ppb_number=getattr(approver, "ppb_number", None),
        signature_path=approver_sig_path,
        signature_bytes=signature_bytes,
        approved_at=now,
    )
    stored_path = upload_po_pdf(tenant.id, db_order.id, pdf_bytes, tenant=tenant)
    if stored_path:
        db_order.pdf_path = stored_path
    db.commit()
    db.refresh(db_order)
    # Load names for response
    if db_order.supplier:
        db_order.supplier_name = db_order.supplier.name
    if db_order.branch:
        db_order.branch_name = db_order.branch.name
    created_by_user = db.query(User).filter(User.id == db_order.created_by).first()
    if created_by_user:
        db_order.created_by_name = created_by_user.full_name or created_by_user.email
    approver_user = db.query(User).filter(User.id == db_order.approved_by_user_id).first()
    if approver_user:
        db_order.approved_by_name = approver_user.full_name or approver_user.email
    for oi in db_order.items:
        if oi.item:
            oi.item_code = oi.item.sku or ""
            oi.item_name = oi.item.name or ""
            oi.is_controlled = getattr(oi.item, "is_controlled", False)
    return db_order


@router.get("/order/{order_id}/pdf-url")
def get_purchase_order_pdf_url(
    order_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Optional[Tenant] = Depends(get_tenant_optional),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """Return signed URL for the stored PO PDF (only when approved and pdf_path set). Expires in 1 hour."""
    user = current_user_and_db[0]
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    require_document_belongs_to_user_company(db, user, order, "Purchase order", request)
    if not order.pdf_path:
        raise HTTPException(
            status_code=404,
            detail="No PDF available for this order. The order may have been approved before PDF generation was enabled. Use 'Regenerate PDF' to generate it now.",
        )
    url = None
    if tenant is not None:
        url = get_signed_url(order.pdf_path, tenant=tenant)
    if not url and _legacy_path_tenant_fallback_enabled() and str(order.pdf_path or "").startswith("tenant-assets/"):
        path_tenant = _tenant_for_stored_path(master_db, order.pdf_path)
        if path_tenant:
            url = get_signed_url_with_path_tenant(order.pdf_path, path_tenant)
    if not url:
        url = get_signed_url(order.pdf_path, tenant=None)
    if not url:
        raise HTTPException(
            status_code=503,
            detail="Could not generate PDF URL. Check Supabase storage config (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) and Render logs.",
        )
    url_str = str(url)
    # Do not log token itself; only validate structure.
    # Print to stdout so it always shows up in Render/terminal logs.
    print(
        f"pdf-url ok order_id={order_id} pdf_path_prefix={(str(order.pdf_path or ''))[:80]} "
        f"url_prefix={url_str[:80]} token_present={'token=' in url_str} starts_http={url_str.startswith('http')}",
        flush=True,
    )
    return {"url": url}


@router.post("/order/{order_id}/regenerate-pdf")
def regenerate_purchase_order_pdf(
    order_id: UUID,
    request: Request,
    tenant: Tenant = Depends(get_tenant_or_default),
    user_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """
    Regenerate and store PDF for an already-approved purchase order (overwrites existing PDF if present).
    Use when document branding changes (logo/stamp/signature) or after migration when PDF was not generated.
    Embeds logo, stamp, signature.
    """
    user = user_db[0]
    db_order = db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.item),
        selectinload(PurchaseOrder.company),
        selectinload(PurchaseOrder.branch),
        selectinload(PurchaseOrder.supplier),
    ).filter(PurchaseOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    require_document_belongs_to_user_company(db, user, db_order, "Purchase order", request)
    if db_order.status != "APPROVED":
        raise HTTPException(
            status_code=400,
            detail="Only approved orders can have a PDF generated. Current status: " + str(db_order.status),
        )
    branding_row = db.query(CompanySetting).filter(
        CompanySetting.company_id == db_order.company_id,
        CompanySetting.setting_key == "document_branding",
    ).first()
    try:
        document_branding = json.loads(branding_row.setting_value or "{}") if branding_row else {}
    except json.JSONDecodeError:
        document_branding = {}
    stamp_path = document_branding.get("stamp_url")
    company = db_order.company
    branch = db_order.branch
    approver = db.query(User).filter(User.id == db_order.approved_by_user_id).first() if db_order.approved_by_user_id else user
    items_data = []
    for oi in db_order.items:
        items_data.append({
            "item_code": oi.item.sku if oi.item else None,
            "item_name": oi.item.name if oi.item else None,
            "quantity": float(oi.quantity),
            "unit_name": oi.unit_name,
            "unit_price": float(oi.unit_price),
            "total_price": float(oi.total_price),
            "is_controlled": getattr(oi.item, "is_controlled", False) if oi.item else False,
        })
    order_dt = db_order.order_date
    if hasattr(order_dt, "isoformat") and not isinstance(order_dt, datetime):
        order_dt = datetime.combine(order_dt, datetime.min.time().replace(tzinfo=timezone.utc))
    approved_at = db_order.approved_at or datetime.now(timezone.utc)
    if hasattr(approved_at, "isoformat") and not isinstance(approved_at, datetime):
        approved_at = datetime.combine(approved_at, datetime.min.time().replace(tzinfo=timezone.utc))

    company_logo_path = getattr(company, "logo_url", None) if company else None
    company_logo_bytes = _resolve_asset_bytes(company_logo_path, tenant, master_db)
    stamp_bytes = _resolve_asset_bytes(stamp_path, tenant, master_db)
    approver_sig_path = getattr(approver, "signature_path", None)
    signature_bytes = _resolve_asset_bytes(approver_sig_path, tenant, master_db)

    pdf_bytes = build_po_pdf(
        company_name=company.name or "—",
        company_address=company.address,
        company_phone=company.phone,
        company_pin=company.pin,
        company_logo_path=company_logo_path,
        company_logo_bytes=company_logo_bytes,
        branch_name=branch.name if branch else None,
        branch_address=branch.address if branch else None,
        order_number=db_order.order_number,
        order_date=order_dt,
        supplier_name=db_order.supplier.name if db_order.supplier else "—",
        reference=db_order.reference,
        items=items_data,
        total_amount=db_order.total_amount or Decimal("0"),
        document_branding=document_branding,
        stamp_path=stamp_path,
        stamp_bytes=stamp_bytes,
        approver_name=approver.full_name or approver.email,
        approver_designation=getattr(approver, "designation", None),
        approver_ppb_number=getattr(approver, "ppb_number", None),
        signature_path=approver_sig_path,
        signature_bytes=signature_bytes,
        approved_at=approved_at,
    )
    stored_path = upload_po_pdf(tenant.id, db_order.id, pdf_bytes, tenant=tenant)
    if not stored_path:
        raise HTTPException(
            status_code=503,
            detail="Could not upload PDF. Check Supabase storage configuration.",
        )
    db_order.pdf_path = stored_path
    db.commit()
    url = _resolve_signed_url(stored_path, tenant, master_db)
    return {"url": url, "pdf_path": stored_path}


@router.delete("/order/{order_id}", status_code=status.HTTP_200_OK)
def delete_purchase_order(
    order_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Delete purchase order (only if status is PENDING)"""
    db_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if db_order.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete purchase order with status {db_order.status}. Only PENDING orders can be deleted."
        )
    
    # Delete order items (cascade should handle this, but explicit is safer)
    db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order_id).delete()
    
    # Delete order
    db.delete(db_order)
    db.commit()
    
    return {"message": "Purchase order deleted successfully", "deleted": True}

