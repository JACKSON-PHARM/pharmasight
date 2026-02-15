"""
Quotations API routes
Quotations are non-stock-affecting sales documents that can be converted to invoices
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime
from app.dependencies import get_tenant_db

logger = logging.getLogger(__name__)
from app.models import (
    Quotation, QuotationItem, SalesInvoice, SalesInvoiceItem,
    Item, InventoryLedger, Company, Branch, User
)
from app.schemas.sale import (
    QuotationCreate, QuotationResponse, QuotationUpdate,
    QuotationItemCreate, QuotationItemResponse,
    SalesInvoiceCreate, SalesInvoiceResponse,
    QuotationConvertRequest
)
from app.services.pricing_service import PricingService
from app.services.inventory_service import InventoryService
from app.services.document_service import DocumentService
from app.services.document_items_helper import deduplicate_quotation_items
from app.services.order_book_service import OrderBookService
from app.services.item_units_helper import get_unit_multiplier_from_item, get_unit_display_short
from app.utils.vat import vat_rate_to_percent

router = APIRouter()


@router.post("", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
def create_quotation(quotation: QuotationCreate, db: Session = Depends(get_tenant_db)):
    """
    Create a quotation (does NOT affect inventory)
    """
    # Generate quotation number
    quotation_no = DocumentService.get_quotation_number(
        db, quotation.company_id, quotation.branch_id
    )
    
    # Ensure no duplicate lines per (item_id, unit_name); merge before saving
    items_to_save = deduplicate_quotation_items(quotation.items)
    if not items_to_save:
        raise HTTPException(status_code=400, detail="At least one line item is required")

    # Calculate totals
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    
    # Process each item (NO stock allocation - quotations don't affect inventory)
    quotation_items = []
    
    for item_data in items_to_save:
        # Get item details
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Item {item_data.item_id} not found"
            )
        
        # Get VAT rate from item (Kenya: percentage; normalize if stored as 0.16)
        vat_rate = Decimal(str(vat_rate_to_percent(item.vat_rate))) if item.vat_rate is not None else Decimal("16.00")
        
        # Calculate line totals
        quantity = Decimal(str(item_data.quantity))
        unit_price = Decimal(str(item_data.unit_price_exclusive or 0))
        
        line_subtotal = quantity * unit_price
        discount_percent = Decimal(str(item_data.discount_percent or 0))
        discount_amount = line_subtotal * (discount_percent / Decimal("100"))
        line_total_exclusive = line_subtotal - discount_amount
        line_vat = line_total_exclusive * (vat_rate / Decimal("100"))
        line_total_inclusive = line_total_exclusive + line_vat
        
        # Create quotation item (NO batch allocation, NO ledger entries)
        quotation_item = QuotationItem(
            quotation_id=None,  # Will be set after quotation is created
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=quantity,
            unit_price_exclusive=unit_price,
            discount_percent=discount_percent,
            discount_amount=discount_amount,
            vat_rate=vat_rate,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive
        )
        quotation_items.append(quotation_item)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
    
    # Apply quotation-level discount
    total_exclusive -= quotation.discount_amount
    total_inclusive = total_exclusive + total_vat
    
    # Calculate average VAT rate
    invoice_vat_rate = (total_vat / total_exclusive * Decimal("100")) if total_exclusive > 0 else Decimal("0")
    
    # Create quotation
    db_quotation = Quotation(
        company_id=quotation.company_id,
        branch_id=quotation.branch_id,
        quotation_no=quotation_no,
        quotation_date=quotation.quotation_date,
        customer_name=quotation.customer_name,
        customer_pin=quotation.customer_pin,
        reference=quotation.reference,
        notes=quotation.notes,
        status=quotation.status,
        total_exclusive=total_exclusive,
        vat_rate=invoice_vat_rate,
        vat_amount=total_vat,
        discount_amount=quotation.discount_amount,
        total_inclusive=total_inclusive,
        valid_until=quotation.valid_until,
        created_by=quotation.created_by
    )
    db.add(db_quotation)
    db.flush()
    
    # Link items to quotation
    for item in quotation_items:
        item.quotation_id = db_quotation.id
        db.add(item)
    
    db.commit()
    db.refresh(db_quotation)
    return db_quotation


@router.get("/{quotation_id}", response_model=QuotationResponse)
def get_quotation(quotation_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get quotation by ID with full item details, margin, and print header (company/branch/user)"""
    from sqlalchemy.orm import selectinload
    # Load quotation with items and item relationships
    quotation = db.query(Quotation).options(
        selectinload(Quotation.items).selectinload(QuotationItem.item)
    ).filter(Quotation.id == quotation_id).first()
    
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    
    # Enhance items with item name/code, margin, and unit_display_short (P/W/S for print)
    for quotation_item in quotation.items:
        if quotation_item.item:
            quotation_item.item_code = quotation_item.item.sku or ''
            quotation_item.item_name = quotation_item.item.name or ''
            quotation_item.unit_display_short = get_unit_display_short(
                quotation_item.item, quotation_item.unit_name or ''
            )
        # Margin calculation: cost per sale unit and margin %
        cost_base = PricingService.get_item_cost(
            db, quotation_item.item_id, quotation.branch_id
        )
        if cost_base is not None:
            # Expose base-unit cost for UI to calculate margins consistently across unit tiers
            quotation_item.unit_cost_base = cost_base
            item = quotation_item.item
            mult = get_unit_multiplier_from_item(item, quotation_item.unit_name) if item else None
            if mult is not None:
                cost_per_sale_unit = cost_base * mult
                quotation_item.unit_cost_used = cost_per_sale_unit
                price = quotation_item.unit_price_exclusive or Decimal("0")
                if price > 0:
                    quotation_item.margin_percent = (
                        (price - cost_per_sale_unit) / price * Decimal("100")
                    )
    
    # Print header: company, branch, user
    company = db.query(Company).filter(Company.id == quotation.company_id).first()
    if company:
        quotation.company_name = company.name
        quotation.company_address = getattr(company, "address", None) or ""
    branch = db.query(Branch).filter(Branch.id == quotation.branch_id).first()
    if branch:
        quotation.branch_name = branch.name
        quotation.branch_address = getattr(branch, "address", None) or ""
        quotation.branch_phone = getattr(branch, "phone", None) or ""
    creator = db.query(User).filter(User.id == quotation.created_by).first()
    if creator:
        quotation.created_by_username = creator.username or getattr(creator, "full_name", None) or ""
    
    return quotation


@router.get("/branch/{branch_id}", response_model=List[QuotationResponse])
def get_branch_quotations(branch_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get all quotations for a branch"""
    from sqlalchemy.orm import selectinload
    quotations = db.query(Quotation).options(
        selectinload(Quotation.items)
    ).filter(
        Quotation.branch_id == branch_id
    ).order_by(Quotation.quotation_date.desc()).all()
    return quotations


@router.put("/{quotation_id}", response_model=QuotationResponse)
def update_quotation(quotation_id: UUID, quotation: QuotationUpdate, db: Session = Depends(get_tenant_db)):
    """Update quotation (only if status is 'draft')"""
    db_quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not db_quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    
    if db_quotation.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update quotation with status '{db_quotation.status}'. Only 'draft' quotations can be updated."
        )
    
    # Update basic fields
    if quotation.customer_name is not None:
        db_quotation.customer_name = quotation.customer_name
    if quotation.customer_pin is not None:
        db_quotation.customer_pin = quotation.customer_pin
    if quotation.reference is not None:
        db_quotation.reference = quotation.reference
    if quotation.notes is not None:
        db_quotation.notes = quotation.notes
    if quotation.status is not None:
        db_quotation.status = quotation.status
    if quotation.discount_amount is not None:
        db_quotation.discount_amount = quotation.discount_amount
    if quotation.valid_until is not None:
        db_quotation.valid_until = quotation.valid_until
    
    # Update items if provided
    if quotation.items is not None:
        # Ensure no duplicate lines per (item_id, unit_name); merge before saving
        items_to_save = deduplicate_quotation_items(quotation.items)
        if not items_to_save:
            raise HTTPException(status_code=400, detail="At least one line item is required")

        # Delete existing items
        db.query(QuotationItem).filter(QuotationItem.quotation_id == quotation_id).delete()
        
        # Recalculate totals
        total_exclusive = Decimal("0")
        total_vat = Decimal("0")
        quotation_items = []
        
        for item_data in items_to_save:
            item = db.query(Item).filter(Item.id == item_data.item_id).first()
            if not item:
                raise HTTPException(
                    status_code=404,
                    detail=f"Item {item_data.item_id} not found"
                )
            
            # VAT from item (normalize decimal 0.16 -> 16%)
            vat_rate = Decimal(str(vat_rate_to_percent(item.vat_rate))) if item.vat_rate is not None else Decimal("16.00")
            quantity = Decimal(str(item_data.quantity))
            unit_price = Decimal(str(item_data.unit_price_exclusive or 0))
            
            line_subtotal = quantity * unit_price
            discount_percent = Decimal(str(item_data.discount_percent or 0))
            discount_amount = line_subtotal * (discount_percent / Decimal("100"))
            line_total_exclusive = line_subtotal - discount_amount
            line_vat = line_total_exclusive * (vat_rate / Decimal("100"))
            line_total_inclusive = line_total_exclusive + line_vat
            
            quotation_item = QuotationItem(
                quotation_id=quotation_id,
                item_id=item_data.item_id,
                unit_name=item_data.unit_name,
                quantity=quantity,
                unit_price_exclusive=unit_price,
                discount_percent=discount_percent,
                discount_amount=discount_amount,
                vat_rate=vat_rate,
                vat_amount=line_vat,
                line_total_exclusive=line_total_exclusive,
                line_total_inclusive=line_total_inclusive
            )
            quotation_items.append(quotation_item)
            total_exclusive += line_total_exclusive
            total_vat += line_vat
        
        total_exclusive -= db_quotation.discount_amount
        total_inclusive = total_exclusive + total_vat
        invoice_vat_rate = (total_vat / total_exclusive * Decimal("100")) if total_exclusive > 0 else Decimal("0")
        
        db_quotation.total_exclusive = total_exclusive
        db_quotation.vat_rate = invoice_vat_rate
        db_quotation.vat_amount = total_vat
        db_quotation.total_inclusive = total_inclusive
        
        for item in quotation_items:
            db.add(item)
    
    db.commit()
    db.refresh(db_quotation)
    return db_quotation


@router.delete("/{quotation_id}", status_code=status.HTTP_200_OK)
def delete_quotation(quotation_id: UUID, db: Session = Depends(get_tenant_db)):
    """Delete quotation (only if status is 'draft')"""
    db_quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not db_quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    
    if db_quotation.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete quotation with status '{db_quotation.status}'. Only 'draft' quotations can be deleted."
        )
    
    # Delete quotation items (cascade should handle this, but explicit is safer)
    from app.models import QuotationItem
    db.query(QuotationItem).filter(QuotationItem.quotation_id == quotation_id).delete()
    
    # Delete quotation
    db.delete(db_quotation)
    db.commit()
    
    return {"message": "Quotation deleted successfully", "deleted": True}


@router.post("/{quotation_id}/convert-to-invoice", response_model=SalesInvoiceResponse, status_code=status.HTTP_201_CREATED)
def convert_quotation_to_invoice(
    quotation_id: UUID,
    convert_request: QuotationConvertRequest,
    db: Session = Depends(get_tenant_db)
):
    """
    Convert quotation to sales invoice
    This will:
    1. Check stock availability for all items
    2. Create a sales invoice with FEFO stock allocation
    3. Update quotation status to 'converted'
    4. Link quotation to the new invoice
    """
    # Get quotation
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    
    if quotation.status == "converted":
        raise HTTPException(
            status_code=400,
            detail="Quotation has already been converted to an invoice"
        )
    
    # Check stock availability for all items
    stock_errors = []
    for q_item in quotation.items:
        # Check stock availability
        is_available, available_base, required_base = InventoryService.check_stock_availability(
            db, q_item.item_id, quotation.branch_id, q_item.quantity, q_item.unit_name
        )
        if not is_available:
            item = db.query(Item).filter(Item.id == q_item.item_id).first()
            # Convert available_base back to sale unit for display (items table is source of truth)
            item = db.query(Item).filter(Item.id == q_item.item_id).first()
            mult = get_unit_multiplier_from_item(item, q_item.unit_name) if item else None
            if mult and float(mult) > 0:
                available_in_sale_unit = available_base / float(mult)
            else:
                available_in_sale_unit = available_base
            stock_errors.append(
                f"Item '{item.name if item else q_item.item_id}': "
                f"Required {q_item.quantity} {q_item.unit_name}, "
                f"but only {available_in_sale_unit:.2f} {q_item.unit_name} available"
            )
    
    if stock_errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Insufficient stock to convert quotation to invoice",
                "stock_errors": stock_errors
            }
        )
    
    # Generate invoice number
    invoice_no = DocumentService.get_sales_invoice_number(
        db, quotation.company_id, quotation.branch_id
    )
    
    # Use convert_request values or fall back to quotation values
    invoice_date = convert_request.invoice_date or quotation.quotation_date
    customer_name = convert_request.customer_name or quotation.customer_name
    customer_pin = convert_request.customer_pin or quotation.customer_pin
    reference = convert_request.reference or quotation.reference
    notes = convert_request.notes or quotation.notes
    
    # Calculate totals and process items with stock allocation
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    invoice_items = []
    ledger_entries = []
    
    for q_item in quotation.items:
        # Get item details
        item = db.query(Item).filter(Item.id == q_item.item_id).first()
        
        # Allocate stock using FEFO (unit from items table)
        quantity_base_units = InventoryService.convert_to_base_units(
            db, q_item.item_id, q_item.quantity, q_item.unit_name
        )
        allocations = InventoryService.allocate_stock_fefo(
            db,
            q_item.item_id,
            quotation.branch_id,
            quantity_base_units,
            q_item.unit_name
        )
        
        if not allocations:
            raise HTTPException(
                status_code=400,
                detail=f"Could not allocate stock for item {item.name if item else q_item.item_id}"
            )
        
        # Calculate unit cost (weighted average from allocations)
        total_cost = sum(Decimal(str(a["unit_cost"])) * a["quantity"] for a in allocations)
        total_qty = sum(a["quantity"] for a in allocations)
        unit_cost_used = total_cost / total_qty if total_qty > 0 else Decimal("0")
        
        # Use quotation item prices
        line_subtotal = q_item.quantity * q_item.unit_price_exclusive
        discount_amount = q_item.discount_amount
        line_total_exclusive = line_subtotal - discount_amount
        line_vat = q_item.vat_amount
        line_total_inclusive = q_item.line_total_inclusive
        
        # Create invoice item
        invoice_item = SalesInvoiceItem(
            sales_invoice_id=None,  # Will be set after invoice creation
            item_id=q_item.item_id,
            unit_name=q_item.unit_name,
            quantity=q_item.quantity,
            unit_price_exclusive=q_item.unit_price_exclusive,
            discount_percent=q_item.discount_percent,
            discount_amount=q_item.discount_amount,
            vat_rate=q_item.vat_rate,
            vat_amount=q_item.vat_amount,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive,
            unit_cost_used=unit_cost_used
        )
        invoice_items.append(invoice_item)
        
        # Create ledger entries (negative for sales)
        for allocation in allocations:
            ledger_entry = InventoryLedger(
                company_id=quotation.company_id,
                branch_id=quotation.branch_id,
                item_id=q_item.item_id,
                batch_number=allocation["batch_number"],
                expiry_date=allocation["expiry_date"],
                transaction_type="SALE",
                reference_type="sales_invoice",
                quantity_delta=-allocation["quantity"],
                unit_cost=Decimal(str(allocation["unit_cost"])),
                total_cost=Decimal(str(allocation["unit_cost"])) * allocation["quantity"],
                created_by=quotation.created_by
            )
            ledger_entries.append(ledger_entry)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
    
    # Apply discount
    total_exclusive -= quotation.discount_amount
    total_inclusive = total_exclusive + total_vat
    
    # Calculate average VAT rate
    invoice_vat_rate = (total_vat / total_exclusive * Decimal("100")) if total_exclusive > 0 else Decimal("0")
    
    # Create invoice
    db_invoice = SalesInvoice(
        company_id=quotation.company_id,
        branch_id=quotation.branch_id,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        customer_name=customer_name,
        customer_pin=customer_pin,
        payment_mode=convert_request.payment_mode,
        payment_status=convert_request.payment_status,
        total_exclusive=total_exclusive,
        vat_rate=invoice_vat_rate,
        vat_amount=total_vat,
        discount_amount=quotation.discount_amount,
        total_inclusive=total_inclusive,
        created_by=quotation.created_by
    )
    db.add(db_invoice)
    db.flush()
    
    # Link items to invoice
    for item in invoice_items:
        item.sales_invoice_id = db_invoice.id
        db.add(item)
    
    # Add ledger entries
    for entry in ledger_entries:
        entry.reference_id = db_invoice.id
        db.add(entry)
    
    # Update quotation status
    quotation.status = "converted"
    quotation.converted_to_invoice_id = db_invoice.id
    
    # Set invoice status to BATCHED since stock has been reduced
    db_invoice.status = "BATCHED"
    db_invoice.batched = True
    db_invoice.batched_by = quotation.created_by
    db_invoice.batched_at = datetime.utcnow()
    
    db.commit()
    
    # After stock is reduced, check if items should be added to order book
    # Only BATCHED invoices trigger order book (process_sale_for_order_book checks this)
    try:
        order_book_entries = OrderBookService.process_sale_for_order_book(
            db=db,
            company_id=db_invoice.company_id,
            branch_id=db_invoice.branch_id,
            invoice_id=db_invoice.id,
            user_id=quotation.created_by
        )
        if order_book_entries:
            logger.info(f"✅ Auto-added {len(order_book_entries)} items to order book from converted quotation {quotation_id}")
    except Exception as e:
        logger.error(f"Error processing order book after quotation conversion: {e}", exc_info=True)
        # Don't fail the conversion if order book check fails
    
    db.refresh(db_invoice)
    return db_invoice
