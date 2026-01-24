"""
Sales API routes (KRA Compliant)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from uuid import UUID
from decimal import Decimal
from app.database import get_db
from app.models import (
    SalesInvoice, SalesInvoiceItem, InventoryLedger,
    Item, ItemUnit, InvoicePayment
)
from app.schemas.sale import (
    SalesInvoiceCreate, SalesInvoiceResponse,
    SalesInvoiceItemCreate, SalesInvoiceUpdate,
    InvoicePaymentCreate, InvoicePaymentResponse
)
from app.services.inventory_service import InventoryService
from app.services.pricing_service import PricingService
from app.services.document_service import DocumentService

router = APIRouter()


@router.post("/invoice", response_model=SalesInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_sales_invoice(invoice: SalesInvoiceCreate, db: Session = Depends(get_db)):
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
    
    # Calculate totals
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    
    # Process each item
    invoice_items = []
    
    # Check if customer_phone column exists (for backward compatibility)
    from sqlalchemy import inspect
    inspector = inspect(SalesInvoice)
    has_customer_phone = 'customer_phone' in [col.name for col in inspector.columns]
    
    for item_data in invoice.items:
        # Get item
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        # Copy VAT classification from item (Kenya Pharmacy Context)
        item_vat_rate = Decimal(str(item.vat_rate or 0))
        
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
        unit_price = item_data.unit_price_exclusive
        unit_cost_used = None
        
        if not unit_price:
            price_info = PricingService.calculate_recommended_price(
                db, item_data.item_id, invoice.branch_id,
                invoice.company_id, item_data.unit_name
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
            # Get cost for margin calculation
            cost_info = PricingService.get_item_cost(
                db, item_data.item_id, invoice.branch_id
            )
            if cost_info:
                unit_cost_used = cost_info
        
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


@router.get("/invoice/{invoice_id}", response_model=SalesInvoiceResponse)
def get_sales_invoice(invoice_id: UUID, db: Session = Depends(get_db)):
    """Get sales invoice by ID with full item details"""
    from sqlalchemy.orm import selectinload
    # Load invoice with items and item relationships
    invoice = db.query(SalesInvoice).options(
        selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item)
    ).filter(SalesInvoice.id == invoice_id).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
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
    
    # Use cached item_name/item_code if available, otherwise fallback to item relationship
    for invoice_item in invoice.items:
        if not hasattr(invoice_item, 'item_name') or not invoice_item.item_name:
            if invoice_item.item:
                invoice_item.item_name = invoice_item.item.name or ''
        if not hasattr(invoice_item, 'item_code') or not invoice_item.item_code:
            if invoice_item.item:
                invoice_item.item_code = invoice_item.item.sku or ''
    
    return invoice


@router.get("/branch/{branch_id}/invoices", response_model=List[SalesInvoiceResponse])
def get_branch_invoices(branch_id: UUID, db: Session = Depends(get_db)):
    """Get all invoices for a branch"""
    try:
        invoices = db.query(SalesInvoice).filter(
            SalesInvoice.branch_id == branch_id
        ).order_by(SalesInvoice.invoice_date.desc()).all()
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


@router.put("/invoice/{invoice_id}", response_model=SalesInvoiceResponse)
def update_sales_invoice(
    invoice_id: UUID,
    invoice_update: SalesInvoiceUpdate,
    db: Session = Depends(get_db)
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
def batch_sales_invoice(invoice_id: UUID, batched_by: UUID, db: Session = Depends(get_db)):
    """
    Batch Sales Invoice - Reduce Stock from Inventory
    
    This endpoint processes a DRAFT invoice and reduces stock from inventory based on FEFO allocation.
    Only DRAFT invoices can be batched. Once batched, status changes to BATCHED.
    """
    from sqlalchemy.orm import selectinload
    from datetime import datetime
    
    invoice = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items))
        .filter(SalesInvoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
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
    
    # Process each item and reduce stock based on FEFO allocation
    ledger_entries = []
    
    for invoice_item in invoice.items:
        item = db.query(Item).filter(Item.id == invoice_item.item_id).first()
        if not item:
            raise HTTPException(
                status_code=400,
                detail=f"Item {invoice_item.item_id} not found. Cannot batch."
            )
        
        # Convert quantity to base units
        quantity_base = InventoryService.convert_to_base_units(
            db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
        )
        
        # Check availability again (stock may have changed since DRAFT creation)
        is_available, available, required = InventoryService.check_stock_availability(
            db, invoice_item.item_id, invoice.branch_id,
            float(invoice_item.quantity), invoice_item.unit_name
        )
        if not is_available:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {invoice_item.item_name or item.name}. Available: {available}, Required: {required}"
            )
        
        # Allocate stock (FEFO)
        allocations = InventoryService.allocate_stock_fefo(
            db, invoice_item.item_id, invoice.branch_id,
            quantity_base, invoice_item.unit_name
        )
        
        # Update invoice item with batch_id from first allocation
        if allocations:
            invoice_item.batch_id = allocations[0]["ledger_entry_id"]
        
        # Create ledger entries (negative for sales)
        for allocation in allocations:
            ledger_entry = InventoryLedger(
                company_id=invoice.company_id,
                branch_id=invoice.branch_id,
                item_id=invoice_item.item_id,
                batch_number=allocation["batch_number"],
                expiry_date=allocation["expiry_date"],
                transaction_type="SALE",
                reference_type="sales_invoice",
                reference_id=invoice.id,
                quantity_delta=-allocation["quantity"],  # Negative
                unit_cost=Decimal(str(allocation["unit_cost"])),
                total_cost=Decimal(str(allocation["unit_cost"])) * allocation["quantity"],
                created_by=batched_by
            )
            ledger_entries.append(ledger_entry)
    
    # Update invoice status to BATCHED
    invoice.status = "BATCHED"
    invoice.batched = True
    invoice.batched_by = batched_by
    invoice.batched_at = datetime.utcnow()
    
    # Add ledger entries
    for entry in ledger_entries:
        db.add(entry)
    
    db.commit()
    db.refresh(invoice)
    return invoice


@router.delete("/invoice/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_invoice(invoice_id: UUID, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
):
    """
    Add a split payment to a sales invoice
    
    Supports multiple payment modes per invoice (cash, M-Pesa, card, etc.)
    """
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status not in ["BATCHED", "PAID"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot add payment to invoice with status {invoice.status}. Invoice must be BATCHED."
        )
    
    # Calculate total payments so far
    existing_payments = db.query(func.sum(InvoicePayment.amount)).filter(
        InvoicePayment.invoice_id == invoice_id
    ).scalar() or Decimal("0")
    
    total_paid = existing_payments + payment.amount
    
    # Validate payment doesn't exceed invoice total
    if total_paid > invoice.total_inclusive:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount exceeds invoice total. Invoice: {invoice.total_inclusive}, Total paid: {total_paid}"
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
        from datetime import datetime
        invoice.approved_at = datetime.utcnow()
    elif total_paid > 0:
        invoice.payment_status = "PARTIAL"
    
    db.commit()
    db.refresh(db_payment)
    return db_payment


@router.get("/invoice/{invoice_id}/payments", response_model=List[InvoicePaymentResponse])
def get_invoice_payments(invoice_id: UUID, db: Session = Depends(get_db)):
    """Get all payments for a sales invoice"""
    payments = db.query(InvoicePayment).filter(
        InvoicePayment.invoice_id == invoice_id
    ).order_by(InvoicePayment.created_at).all()
    return payments


@router.delete("/invoice/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice_payment(payment_id: UUID, db: Session = Depends(get_db)):
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
def convert_sales_invoice_to_quotation(invoice_id: UUID, db: Session = Depends(get_db)):
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

