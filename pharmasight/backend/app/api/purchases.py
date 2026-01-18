"""
Purchases API routes (GRN and Purchase Invoices)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date
from app.database import get_db
from app.models import (
    GRN, GRNItem, PurchaseInvoice, PurchaseInvoiceItem,
    PurchaseOrder, PurchaseOrderItem,
    InventoryLedger, Item, ItemUnit, Supplier, Branch, User
)
from app.schemas.purchase import (
    GRNCreate, GRNResponse,
    PurchaseInvoiceCreate, PurchaseInvoiceResponse,
    PurchaseOrderCreate, PurchaseOrderResponse
)
from app.services.inventory_service import InventoryService
from app.services.document_service import DocumentService

router = APIRouter()


@router.post("/grn", response_model=GRNResponse, status_code=status.HTTP_201_CREATED)
def create_grn(grn: GRNCreate, db: Session = Depends(get_db)):
    """
    Create GRN (Goods Received Note)
    
    This updates inventory ledger with stock and cost.
    VAT is handled separately in Purchase Invoice.
    """
    # Generate GRN number
    grn_no = DocumentService.get_grn_number(
        db, grn.company_id, grn.branch_id
    )
    
    total_cost = Decimal("0")
    grn_items = []
    ledger_entries = []
    
    for item_data in grn.items:
        # Get item
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        # Convert quantity to base units
        quantity_base = InventoryService.convert_to_base_units(
            db, item_data.item_id, float(item_data.quantity), item_data.unit_name
        )
        
        # Calculate cost per base unit
        unit_cost_base = Decimal(str(item_data.unit_cost)) / Decimal(str(
            db.query(ItemUnit).filter(
                ItemUnit.item_id == item_data.item_id,
                ItemUnit.unit_name == item_data.unit_name
            ).first().multiplier_to_base
        ))
        
        total_item_cost = Decimal(str(item_data.unit_cost)) * item_data.quantity
        total_cost += total_item_cost
        
        # Create GRN item
        grn_item = GRNItem(
            grn_id=None,  # Will be set after GRN creation
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
            quantity_delta=quantity_base,  # Positive
            unit_cost=unit_cost_base,
            total_cost=unit_cost_base * quantity_base,
            created_by=grn.created_by
        )
        ledger_entries.append(ledger_entry)
    
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
    
    db.commit()
    db.refresh(db_grn)
    return db_grn


@router.get("/grn/{grn_id}", response_model=GRNResponse)
def get_grn(grn_id: UUID, db: Session = Depends(get_db)):
    """Get GRN by ID"""
    grn = db.query(GRN).filter(GRN.id == grn_id).first()
    if not grn:
        raise HTTPException(status_code=404, detail="GRN not found")
    return grn


@router.post("/invoice", response_model=PurchaseInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_invoice(invoice: PurchaseInvoiceCreate, db: Session = Depends(get_db)):
    """
    Create Purchase Invoice (VAT Input)
    
    This is separate from GRN for KRA compliance.
    Can be linked to a GRN.
    """
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    invoice_items = []
    
    for item_data in invoice.items:
        # Calculate line totals
        line_total_exclusive = item_data.unit_cost_exclusive * item_data.quantity
        line_vat = line_total_exclusive * item_data.vat_rate / Decimal("100")
        line_total_inclusive = line_total_exclusive + line_vat
        
        invoice_item = PurchaseInvoiceItem(
            purchase_invoice_id=None,  # Will be set after invoice creation
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_cost_exclusive=item_data.unit_cost_exclusive,
            vat_rate=item_data.vat_rate,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive
        )
        invoice_items.append(invoice_item)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
    
    total_inclusive = total_exclusive + total_vat
    
    # Create invoice
    db_invoice = PurchaseInvoice(
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        supplier_id=invoice.supplier_id,
        invoice_number=invoice.invoice_number,
        pin_number=invoice.pin_number,
        invoice_date=invoice.invoice_date,
        linked_grn_id=invoice.linked_grn_id,
        total_exclusive=total_exclusive,
        vat_rate=invoice.vat_rate,
        vat_amount=total_vat,
        total_inclusive=total_inclusive,
        created_by=invoice.created_by
    )
    db.add(db_invoice)
    db.flush()
    
    # Link items
    for item in invoice_items:
        item.purchase_invoice_id = db_invoice.id
        db.add(item)
    
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.get("/invoice/{invoice_id}", response_model=PurchaseInvoiceResponse)
def get_purchase_invoice(invoice_id: UUID, db: Session = Depends(get_db)):
    """Get purchase invoice by ID"""
    invoice = db.query(PurchaseInvoice).filter(PurchaseInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


# =====================================================
# PURCHASE ORDERS
# =====================================================

@router.post("/order", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_order(order: PurchaseOrderCreate, db: Session = Depends(get_db)):
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
        created_by=order.created_by
    )
    db.add(db_order)
    db.flush()
    
    # Link items to order
    for item in order_items:
        item.purchase_order_id = db_order.id
        db.add(item)
    
    db.commit()
    db.refresh(db_order)
    
    # Load relationships for response
    if db_order.supplier:
        db_order.supplier_name = db_order.supplier.name
    if db_order.branch:
        db_order.branch_name = db_order.branch.name
    
    return db_order


@router.get("/order", response_model=List[PurchaseOrderResponse])
def list_purchase_orders(
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID"),
    supplier_id: Optional[UUID] = Query(None, description="Supplier ID"),
    date_from: Optional[date] = Query(None, description="Filter orders from this date"),
    date_to: Optional[date] = Query(None, description="Filter orders to this date"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, APPROVED, RECEIVED, CANCELLED)"),
    db: Session = Depends(get_db)
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
    
    if date_from:
        query = query.filter(PurchaseOrder.order_date >= date_from)
    
    if date_to:
        query = query.filter(PurchaseOrder.order_date <= date_to)
    
    if status:
        query = query.filter(PurchaseOrder.status == status)
    
    # Order by date descending (newest first)
    orders = query.order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc()).all()
    
    # Load supplier and branch names
    for order in orders:
        if order.supplier:
            order.supplier_name = order.supplier.name
        if order.branch:
            order.branch_name = order.branch.name
    
    return orders


@router.get("/order/{order_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(order_id: UUID, db: Session = Depends(get_db)):
    """Get purchase order by ID"""
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    # Load supplier and branch names
    if order.supplier:
        order.supplier_name = order.supplier.name
    if order.branch:
        order.branch_name = order.branch.name
    
    return order


@router.put("/order/{order_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(order_id: UUID, order_update: PurchaseOrderCreate, db: Session = Depends(get_db)):
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
    
    # Load supplier and branch names
    if db_order.supplier:
        db_order.supplier_name = db_order.supplier.name
    if db_order.branch:
        db_order.branch_name = db_order.branch.name
    
    return db_order

