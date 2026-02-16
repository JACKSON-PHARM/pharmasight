"""
Order Book API routes
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, and_, or_
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime
from app.dependencies import get_tenant_db
from app.models import (
    DailyOrderBook, OrderBookHistory,
    Item, Supplier, PurchaseOrder, PurchaseOrderItem,
    SupplierInvoice, SupplierInvoiceItem,
    InventoryLedger, InventoryBalance, Branch, User
)
from app.schemas.order_book import (
    OrderBookEntryCreate, OrderBookEntryResponse, OrderBookEntryUpdate,
    OrderBookBulkCreate, CreatePurchaseOrderFromBook,
    AutoGenerateRequest, OrderBookHistoryResponse
)
from app.services.document_service import DocumentService
from app.services.snapshot_service import SnapshotService

router = APIRouter()


@router.get("/", response_model=List[OrderBookEntryResponse])
def list_order_book_entries(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status: PENDING, ORDERED, CANCELLED"),
    db: Session = Depends(get_tenant_db)
):
    """
    List all order book entries for a branch
    
    Returns entries with item details and current stock levels.
    """
    query = db.query(DailyOrderBook).filter(
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.company_id == company_id
    )
    
    if status_filter:
        query = query.filter(DailyOrderBook.status == status_filter)
    else:
        # Default to PENDING entries
        query = query.filter(DailyOrderBook.status == "PENDING")
    
    entries = (
        query.options(
            selectinload(DailyOrderBook.item),
            selectinload(DailyOrderBook.supplier)
        )
        .order_by(
            DailyOrderBook.priority.desc(),
            DailyOrderBook.created_at.desc()
        )
        .all()
    )

    # Batch fetch current stock from inventory_balances (fast snapshot)
    item_ids = [e.item_id for e in entries]
    stock_map = {}
    if item_ids:
        try:
            balances = (
                db.query(InventoryBalance.item_id, InventoryBalance.current_stock)
                .filter(
                    InventoryBalance.item_id.in_(item_ids),
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.branch_id == branch_id
                )
                .all()
            )
            stock_map = {row.item_id: int(row.current_stock or 0) for row in balances}
        except Exception:
            stock_map = {}

    # Fallback: use ledger if inventory_balances not available
    def _get_stock(item_id):
        if item_id in stock_map:
            return stock_map[item_id]
        stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == branch_id
        )
        val = stock_query.scalar()
        return int(val or 0)

    result = []
    for entry in entries:
        try:
            entry_dict = {
                "id": entry.id,
                "company_id": entry.company_id,
                "branch_id": entry.branch_id,
                "item_id": entry.item_id,
                "supplier_id": entry.supplier_id,
                "quantity_needed": entry.quantity_needed,
                "unit_name": entry.unit_name or "unit",
                "reason": entry.reason or "MANUAL_ADD",
                "source_reference_type": entry.source_reference_type,
                "source_reference_id": entry.source_reference_id,
                "notes": entry.notes,
                "priority": entry.priority if entry.priority is not None else 5,
                "status": entry.status or "PENDING",
                "purchase_order_id": entry.purchase_order_id,
                "created_by": entry.created_by,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "item_name": entry.item.name if entry.item else "Unknown",
                "item_sku": entry.item.sku if entry.item else None,
                "supplier_name": entry.supplier.name if entry.supplier else None,
                "current_stock": _get_stock(entry.item_id)
            }
            result.append(OrderBookEntryResponse(**entry_dict))
        except Exception as e:
            logging.getLogger(__name__).warning("Skipping order book entry %s due to error: %s", entry.id, e)
            continue
    return result


@router.post("/", response_model=OrderBookEntryResponse, status_code=status.HTTP_201_CREATED)
def create_order_book_entry(
    entry: OrderBookEntryCreate,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the entry"),
    db: Session = Depends(get_tenant_db)
):
    """
    Create a new order book entry
    
    If a PENDING entry already exists for this item, it will be updated instead.
    """
    # Check if item exists
    item = db.query(Item).filter(Item.id == entry.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item {entry.item_id} not found")
    
    # Check if supplier exists (if provided)
    if entry.supplier_id:
        supplier = db.query(Supplier).filter(Supplier.id == entry.supplier_id).first()
        if not supplier:
            raise HTTPException(status_code=404, detail=f"Supplier {entry.supplier_id} not found")
    
    # Check if PENDING entry already exists for this item
    existing_entry = db.query(DailyOrderBook).filter(
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.item_id == entry.item_id,
        DailyOrderBook.status == "PENDING"
    ).first()
    
    if existing_entry:
        # Update existing entry
        existing_entry.quantity_needed = entry.quantity_needed
        existing_entry.unit_name = entry.unit_name
        existing_entry.reason = entry.reason or "MANUAL_ADD"  # Default to MANUAL_ADD for manual entries
        existing_entry.source_reference_type = None  # Not used - simplified to just reason + created_by
        existing_entry.source_reference_id = None  # Not used
        existing_entry.notes = entry.notes
        existing_entry.priority = entry.priority
        if entry.supplier_id:
            existing_entry.supplier_id = entry.supplier_id
        existing_entry.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(existing_entry)
        
        # Enhance response
        entry_dict = {
            "id": existing_entry.id,
            "company_id": existing_entry.company_id,
            "branch_id": existing_entry.branch_id,
            "item_id": existing_entry.item_id,
            "supplier_id": existing_entry.supplier_id,
            "quantity_needed": existing_entry.quantity_needed,
            "unit_name": existing_entry.unit_name,
            "reason": existing_entry.reason,
            "source_reference_type": existing_entry.source_reference_type,
            "source_reference_id": existing_entry.source_reference_id,
            "notes": existing_entry.notes,
            "priority": existing_entry.priority,
            "status": existing_entry.status,
            "purchase_order_id": existing_entry.purchase_order_id,
            "created_by": existing_entry.created_by,
            "created_at": existing_entry.created_at,
            "updated_at": existing_entry.updated_at,
            "item_name": item.name,
            "item_sku": item.sku,
            "supplier_name": existing_entry.supplier.name if existing_entry.supplier else None,
            "current_stock": None
        }
        
        # Get current stock
        stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            InventoryLedger.item_id == entry.item_id,
            InventoryLedger.branch_id == branch_id
        )
        current_stock = stock_query.scalar() or 0
        entry_dict["current_stock"] = int(current_stock)
        
        return OrderBookEntryResponse(**entry_dict)
    else:
        # Create new entry
        # For manual entries, use MANUAL_ADD reason and clear source_reference fields
        reason = entry.reason or "MANUAL_ADD"
        db_entry = DailyOrderBook(
            company_id=company_id,
            branch_id=branch_id,
            item_id=entry.item_id,
            supplier_id=entry.supplier_id,
            quantity_needed=entry.quantity_needed,
            unit_name=entry.unit_name,
            reason=reason,
            source_reference_type=None,  # Not used - simplified to just reason + created_by
            source_reference_id=None,  # Not used
            notes=entry.notes,
            priority=entry.priority,
            status="PENDING",
            created_by=created_by
        )
        db.add(db_entry)
        db.flush()
        SnapshotService.upsert_search_snapshot_last_order_book(
            db, company_id, branch_id, entry.item_id, db_entry.created_at or datetime.utcnow()
        )
        db.commit()
        db.refresh(db_entry)
        
        # Enhance response
        entry_dict = {
            "id": db_entry.id,
            "company_id": db_entry.company_id,
            "branch_id": db_entry.branch_id,
            "item_id": db_entry.item_id,
            "supplier_id": db_entry.supplier_id,
            "quantity_needed": db_entry.quantity_needed,
            "unit_name": db_entry.unit_name,
            "reason": db_entry.reason,
            "source_reference_type": db_entry.source_reference_type,
            "source_reference_id": db_entry.source_reference_id,
            "notes": db_entry.notes,
            "priority": db_entry.priority,
            "status": db_entry.status,
            "purchase_order_id": db_entry.purchase_order_id,
            "created_by": db_entry.created_by,
            "created_at": db_entry.created_at,
            "updated_at": db_entry.updated_at,
            "item_name": item.name,
            "item_sku": item.sku,
            "supplier_name": db_entry.supplier.name if db_entry.supplier else None,
            "current_stock": None
        }
        
        # Get current stock
        stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            InventoryLedger.item_id == entry.item_id,
            InventoryLedger.branch_id == branch_id
        )
        current_stock = stock_query.scalar() or 0
        entry_dict["current_stock"] = int(current_stock)
        
        return OrderBookEntryResponse(**entry_dict)


@router.post("/bulk", response_model=List[OrderBookEntryResponse], status_code=status.HTTP_201_CREATED)
def bulk_create_order_book_entries(
    bulk_data: OrderBookBulkCreate,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the entries"),
    db: Session = Depends(get_tenant_db)
):
    """
    Bulk create order book entries from selected items
    
    Used when user selects multiple items to add to order book.
    """
    created_entries = []
    
    for item_id in bulk_data.item_ids:
        # Get item
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            continue  # Skip if item not found
        
        # Check if entry already exists
        existing = db.query(DailyOrderBook).filter(
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.item_id == item_id,
            DailyOrderBook.status == "PENDING"
        ).first()
        
        if existing:
            continue  # Skip if already exists
        
        # Create entry
        entry = DailyOrderBook(
            company_id=company_id,
            branch_id=branch_id,
            item_id=item_id,
            supplier_id=bulk_data.supplier_id,
            quantity_needed=Decimal("1"),  # Default to 1, user can update
            unit_name=item.base_unit,
            reason=bulk_data.reason or "MANUAL_ADD",
            source_reference_type=None,  # Not used - simplified to just reason + created_by
            source_reference_id=None,  # Not used
            notes=bulk_data.notes,
            priority=5,
            status="PENDING",
            created_by=created_by
        )
        db.add(entry)
        created_entries.append(entry)
    
    db.commit()
    
    # Enhance and return
    result = []
    for entry in created_entries:
        db.refresh(entry)
        entry_dict = {
            "id": entry.id,
            "company_id": entry.company_id,
            "branch_id": entry.branch_id,
            "item_id": entry.item_id,
            "supplier_id": entry.supplier_id,
            "quantity_needed": entry.quantity_needed,
            "unit_name": entry.unit_name,
            "reason": entry.reason,
            "source_reference_type": entry.source_reference_type,
            "source_reference_id": entry.source_reference_id,
            "notes": entry.notes,
            "priority": entry.priority,
            "status": entry.status,
            "purchase_order_id": entry.purchase_order_id,
            "created_by": entry.created_by,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "item_name": entry.item.name if entry.item else None,
            "item_sku": entry.item.sku if entry.item else None,
            "supplier_name": entry.supplier.name if entry.supplier else None,
            "current_stock": None
        }
        
        # Get current stock
        stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            InventoryLedger.item_id == entry.item_id,
            InventoryLedger.branch_id == branch_id
        )
        current_stock = stock_query.scalar() or 0
        entry_dict["current_stock"] = int(current_stock)
        
        result.append(OrderBookEntryResponse(**entry_dict))
    
    return result


@router.put("/{entry_id}", response_model=OrderBookEntryResponse)
def update_order_book_entry(
    entry_id: UUID,
    entry_update: OrderBookEntryUpdate,
    db: Session = Depends(get_tenant_db)
):
    """
    Update an order book entry
    
    Only PENDING entries can be updated.
    """
    entry = db.query(DailyOrderBook).filter(DailyOrderBook.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Order book entry not found")
    
    if entry.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update entry with status {entry.status}. Only PENDING entries can be updated."
        )
    
    # Update fields
    if entry_update.quantity_needed is not None:
        entry.quantity_needed = entry_update.quantity_needed
    if entry_update.supplier_id is not None:
        entry.supplier_id = entry_update.supplier_id
    if entry_update.priority is not None:
        entry.priority = entry_update.priority
    if entry_update.notes is not None:
        entry.notes = entry_update.notes
    
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    
    # Enhance response
    entry_dict = {
        "id": entry.id,
        "company_id": entry.company_id,
        "branch_id": entry.branch_id,
        "item_id": entry.item_id,
        "supplier_id": entry.supplier_id,
        "quantity_needed": entry.quantity_needed,
        "unit_name": entry.unit_name,
        "reason": entry.reason,
        "source_reference_type": entry.source_reference_type,
        "source_reference_id": entry.source_reference_id,
        "notes": entry.notes,
        "priority": entry.priority,
        "status": entry.status,
        "purchase_order_id": entry.purchase_order_id,
        "created_by": entry.created_by,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "item_name": entry.item.name if entry.item else None,
        "item_sku": entry.item.sku if entry.item else None,
        "supplier_name": entry.supplier.name if entry.supplier else None,
        "current_stock": None
    }
    
    # Get current stock
    stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
        InventoryLedger.item_id == entry.item_id,
        InventoryLedger.branch_id == entry.branch_id
    )
    current_stock = stock_query.scalar() or 0
    entry_dict["current_stock"] = int(current_stock)
    
    return OrderBookEntryResponse(**entry_dict)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order_book_entry(entry_id: UUID, db: Session = Depends(get_tenant_db)):
    """
    Delete (cancel) an order book entry
    
    Moves entry to history with CANCELLED status.
    """
    entry = db.query(DailyOrderBook).filter(DailyOrderBook.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Order book entry not found")
    
    if entry.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete entry with status {entry.status}. Only PENDING entries can be deleted."
        )
    
    # Move to history
    history_entry = OrderBookHistory(
        company_id=entry.company_id,
        branch_id=entry.branch_id,
        item_id=entry.item_id,
        supplier_id=entry.supplier_id,
        quantity_needed=entry.quantity_needed,
        unit_name=entry.unit_name,
        reason=entry.reason,
        source_reference_type=entry.source_reference_type,
        source_reference_id=entry.source_reference_id,
        notes=entry.notes,
        priority=entry.priority,
        status="CANCELLED",
        purchase_order_id=entry.purchase_order_id,
        created_by=entry.created_by,
        created_at=entry.created_at,
        updated_at=datetime.utcnow()
    )
    db.add(history_entry)
    
    # Delete from active table
    db.delete(entry)
    db.commit()
    
    return None


@router.post("/auto-generate", response_model=dict)
def auto_generate_order_book_entries(
    request: AutoGenerateRequest,
    db: Session = Depends(get_tenant_db)
):
    """
    Auto-generate order book entries based on stock thresholds
    
    Uses the database function to calculate thresholds and create entries.
    """
    # Call the database function
    result = db.execute(
        func.auto_generate_order_book_entries(
            request.branch_id,
            request.company_id
        )
    )
    entries_created = result.scalar() or 0
    
    return {
        "entries_created": entries_created,
        "branch_id": str(request.branch_id),
        "company_id": str(request.company_id)
    }


@router.post("/create-purchase-order", response_model=dict)
def create_purchase_order_from_book(
    request: CreatePurchaseOrderFromBook,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the purchase order"),
    db: Session = Depends(get_tenant_db)
):
    """
    Create a purchase order from selected order book entries
    
    Converts selected order book entries to a purchase order and marks them as ORDERED.
    """
    # Get all entries
    entries = db.query(DailyOrderBook).filter(
        DailyOrderBook.id.in_(request.entry_ids),
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.status == "PENDING"
    ).all()
    
    if not entries:
        raise HTTPException(status_code=400, detail="No valid entries found")
    
    # Verify all entries have the same supplier (or use provided supplier)
    supplier_id = request.supplier_id
    for entry in entries:
        if entry.supplier_id and entry.supplier_id != supplier_id:
            # Use entry's supplier if no supplier provided
            if not supplier_id:
                supplier_id = entry.supplier_id
            elif entry.supplier_id != supplier_id:
                raise HTTPException(
                    status_code=400,
                    detail="All entries must have the same supplier, or provide a supplier_id"
                )
    
    if not supplier_id:
        raise HTTPException(status_code=400, detail="Supplier ID is required")
    
    # Verify supplier exists
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")
    
    # Generate purchase order number
    order_number = DocumentService.get_purchase_order_number(
        db, company_id, branch_id
    )
    
    # Parse order date
    order_date = datetime.fromisoformat(request.order_date.replace('Z', '+00:00')).date() if isinstance(request.order_date, str) else request.order_date
    
    # Calculate total
    total_amount = Decimal("0")
    order_items = []
    
    for entry in entries:
        # Get item to find purchase unit and price
        item = db.query(Item).filter(Item.id == entry.item_id).first()
        if not item:
            continue
        
        # Get base unit multiplier (assume 1 for base unit)
        # In real scenario, you'd get the purchase unit from item units
        # For now, use base unit
        quantity = entry.quantity_needed
        unit_name = entry.unit_name
        
        # Get last purchase price or use 0
        last_price = Decimal("0")
        last_purchase = db.query(SupplierInvoiceItem).join(SupplierInvoice).filter(
            SupplierInvoiceItem.item_id == entry.item_id,
            SupplierInvoice.branch_id == branch_id
        ).order_by(SupplierInvoice.invoice_date.desc()).first()
        
        if last_purchase:
            last_price = last_purchase.unit_cost_exclusive
        
        unit_price = last_price
        total_price = quantity * unit_price
        total_amount += total_price
        
        order_item = PurchaseOrderItem(
            purchase_order_id=None,  # Will be set after PO creation
            item_id=entry.item_id,
            unit_name=unit_name,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price
        )
        order_items.append(order_item)
    
    # Create purchase order
    purchase_order = PurchaseOrder(
        company_id=company_id,
        branch_id=branch_id,
        supplier_id=supplier_id,
        order_number=order_number,
        order_date=order_date,
        reference=request.reference,
        notes=request.notes,
        total_amount=total_amount,
        status="PENDING",
        created_by=created_by
    )
    db.add(purchase_order)
    db.flush()
    
    # Link items
    for item in order_items:
        item.purchase_order_id = purchase_order.id
        db.add(item)

    db.flush()
    for item in order_items:
        SnapshotService.upsert_search_snapshot_last_order(
            db, company_id, branch_id, item.item_id, order_date
        )
    
    # Update order book entries
    for entry in entries:
        entry.status = "ORDERED"
        entry.purchase_order_id = purchase_order.id
        entry.updated_at = datetime.utcnow()
        
        # Move to history
        history_entry = OrderBookHistory(
            company_id=entry.company_id,
            branch_id=entry.branch_id,
            item_id=entry.item_id,
            supplier_id=entry.supplier_id,
            quantity_needed=entry.quantity_needed,
            unit_name=entry.unit_name,
            reason=entry.reason,
            source_reference_type=entry.source_reference_type,
            source_reference_id=entry.source_reference_id,
            notes=entry.notes,
            priority=entry.priority,
            status="ORDERED",
            purchase_order_id=purchase_order.id,
            created_by=entry.created_by,
            created_at=entry.created_at,
            updated_at=datetime.utcnow()
        )
        db.add(history_entry)
        db.delete(entry)
    
    db.commit()
    db.refresh(purchase_order)
    
    return {
        "purchase_order_id": str(purchase_order.id),
        "order_number": purchase_order.order_number,
        "entries_processed": len(entries)
    }


@router.get("/history", response_model=List[OrderBookHistoryResponse])
def get_order_book_history(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_tenant_db)
):
    """
    Get order book history (ordered or cancelled entries)
    """
    entries = db.query(OrderBookHistory).filter(
        OrderBookHistory.branch_id == branch_id,
        OrderBookHistory.company_id == company_id
    ).order_by(OrderBookHistory.archived_at.desc()).limit(limit).all()
    
    result = []
    for entry in entries:
        entry_dict = {
            "id": entry.id,
            "company_id": entry.company_id,
            "branch_id": entry.branch_id,
            "item_id": entry.item_id,
            "supplier_id": entry.supplier_id,
            "quantity_needed": entry.quantity_needed,
            "unit_name": entry.unit_name,
            "reason": entry.reason,
            "source_reference_type": entry.source_reference_type,
            "source_reference_id": entry.source_reference_id,
            "notes": entry.notes,
            "priority": entry.priority,
            "status": entry.status,
            "purchase_order_id": entry.purchase_order_id,
            "created_by": entry.created_by,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "archived_at": entry.archived_at,
            "item_name": entry.item.name if entry.item else None,
            "item_sku": entry.item.sku if entry.item else None,
            "supplier_name": entry.supplier.name if entry.supplier else None
        }
        result.append(OrderBookHistoryResponse(**entry_dict))
    
    return result
