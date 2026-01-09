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
    Item, ItemUnit
)
from app.schemas.sale import (
    SalesInvoiceCreate, SalesInvoiceResponse,
    SalesInvoiceItemCreate
)
from app.services.inventory_service import InventoryService
from app.services.pricing_service import PricingService
from app.services.document_service import DocumentService

router = APIRouter()


@router.post("/invoice", response_model=SalesInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_sales_invoice(invoice: SalesInvoiceCreate, db: Session = Depends(get_db)):
    """
    Create a sales invoice with FEFO stock allocation
    
    This is the core POS transaction endpoint.
    """
    # Generate invoice number
    invoice_no = DocumentService.get_sales_invoice_number(
        db, invoice.company_id, invoice.branch_id
    )
    
    # Calculate totals
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    vat_rate = Decimal("16.00")
    
    # Process each item
    invoice_items = []
    ledger_entries = []
    
    for item_data in invoice.items:
        # Get item
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        # Convert quantity to base units
        quantity_base = InventoryService.convert_to_base_units(
            db, item_data.item_id, float(item_data.quantity), item_data.unit_name
        )
        
        # Check availability
        is_available, available, required = InventoryService.check_stock_availability(
            db, item_data.item_id, invoice.branch_id,
            float(item_data.quantity), item_data.unit_name
        )
        if not is_available:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {item.name}. Available: {available}, Required: {required}"
            )
        
        # Allocate stock (FEFO)
        allocations = InventoryService.allocate_stock_fefo(
            db, item_data.item_id, invoice.branch_id,
            quantity_base, item_data.unit_name
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
        line_vat = line_total_exclusive * vat_rate / Decimal("100")
        line_total_inclusive = line_total_exclusive + line_vat
        
        # Create invoice item
        invoice_item = SalesInvoiceItem(
            sales_invoice_id=None,  # Will be set after invoice creation
            item_id=item_data.item_id,
            batch_id=allocations[0]["ledger_entry_id"] if allocations else None,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_price_exclusive=unit_price,
            discount_percent=item_data.discount_percent,
            discount_amount=discount_amount,
            vat_rate=vat_rate,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive,
            unit_cost_used=unit_cost_used
        )
        invoice_items.append(invoice_item)
        
        # Create ledger entries (negative for sales)
        for allocation in allocations:
            ledger_entry = InventoryLedger(
                company_id=invoice.company_id,
                branch_id=invoice.branch_id,
                item_id=item_data.item_id,
                batch_number=allocation["batch_number"],
                expiry_date=allocation["expiry_date"],
                transaction_type="SALE",
                reference_type="sales_invoice",
                quantity_delta=-allocation["quantity"],  # Negative
                unit_cost=Decimal(str(allocation["unit_cost"])),
                total_cost=Decimal(str(allocation["unit_cost"])) * allocation["quantity"],
                created_by=invoice.created_by
            )
            ledger_entries.append(ledger_entry)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
    
    # Apply invoice-level discount
    total_exclusive -= invoice.discount_amount
    total_inclusive = total_exclusive + total_vat
    
    # Create invoice
    db_invoice = SalesInvoice(
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        invoice_no=invoice_no,
        invoice_date=invoice.invoice_date,
        customer_name=invoice.customer_name,
        customer_pin=invoice.customer_pin,
        payment_mode=invoice.payment_mode,
        payment_status=invoice.payment_status,
        total_exclusive=total_exclusive,
        vat_rate=vat_rate,
        vat_amount=total_vat,
        discount_amount=invoice.discount_amount,
        total_inclusive=total_inclusive,
        created_by=invoice.created_by
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
    
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.get("/invoice/{invoice_id}", response_model=SalesInvoiceResponse)
def get_sales_invoice(invoice_id: UUID, db: Session = Depends(get_db)):
    """Get sales invoice by ID"""
    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/branch/{branch_id}/invoices", response_model=List[SalesInvoiceResponse])
def get_branch_invoices(branch_id: UUID, db: Session = Depends(get_db)):
    """Get all invoices for a branch"""
    invoices = db.query(SalesInvoice).filter(
        SalesInvoice.branch_id == branch_id
    ).order_by(SalesInvoice.invoice_date.desc()).all()
    return invoices

