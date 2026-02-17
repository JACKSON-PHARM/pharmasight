"""
Order Book API routes
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, and_, or_
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime, timedelta
from app.dependencies import get_tenant_db
from app.models import (
    DailyOrderBook, OrderBookHistory,
    Item, Supplier, PurchaseOrder, PurchaseOrderItem,
    SupplierInvoice, SupplierInvoiceItem,
    InventoryLedger, InventoryBalance, Branch, User
)
from app.schemas.order_book import (
    OrderBookEntryCreate, OrderBookEntryResponse, OrderBookEntryUpdate,
    OrderBookBulkCreate, OrderBookBulkCreateResponse, CreatePurchaseOrderFromBook,
    AutoGenerateRequest, OrderBookHistoryResponse
)
from app.services.document_service import DocumentService
from app.services.snapshot_service import SnapshotService
from app.services.order_book_service import OrderBookService

router = APIRouter()


def _serialize_order_book_entry(entry, _get_stock):
    """Build a JSON-serializable dict for one order book entry."""
    def _dt(d):
        return d.isoformat() if d and hasattr(d, "isoformat") else str(d) if d else None
    def _uuid(u):
        return str(u) if u else None
    entry_date = getattr(entry, "entry_date", None)
    return {
        "id": _uuid(entry.id),
        "company_id": _uuid(entry.company_id),
        "branch_id": _uuid(entry.branch_id),
        "item_id": _uuid(entry.item_id),
        "entry_date": _dt(entry_date) if entry_date else None,
        "supplier_id": _uuid(entry.supplier_id),
        "quantity_needed": float(entry.quantity_needed) if entry.quantity_needed is not None else 1,
        "unit_name": entry.unit_name or "unit",
        "reason": entry.reason or "MANUAL_ADD",
        "source_reference_type": entry.source_reference_type,
        "source_reference_id": _uuid(entry.source_reference_id),
        "notes": entry.notes,
        "priority": int(entry.priority) if entry.priority is not None else 5,
        "status": entry.status or "PENDING",
        "purchase_order_id": _uuid(entry.purchase_order_id),
        "created_by": _uuid(entry.created_by),
        "created_at": _dt(entry.created_at),
        "updated_at": _dt(entry.updated_at),
        "item_name": entry.item.name if entry.item else "Unknown",
        "item_sku": entry.item.sku if entry.item else None,
        "supplier_name": entry.supplier.name if entry.supplier else None,
        "current_stock": _get_stock(entry.item_id),
    }


@router.get("")
@router.get("/")
def list_order_book_entries(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status: PENDING, ORDERED, CANCELLED"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD) for entry_date filter"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD) for entry_date filter"),
    include_ordered: Optional[bool] = Query(False, description="If true, include ORDERED entries (for showing converted)"),
    supplier_id: Optional[UUID] = Query(None, description="Filter by supplier: show only items from this supplier"),
    db: Session = Depends(get_tenant_db)
):
    """
    List order book entries for a branch, optionally filtered by date and supplier.
    Returns JSON array with item details and current stock levels.
    """
    try:
        query = db.query(DailyOrderBook).filter(
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.company_id == company_id
        )
        if supplier_id is not None:
            query = query.filter(DailyOrderBook.supplier_id == supplier_id)
        if status_filter:
            query = query.filter(DailyOrderBook.status == status_filter)
        elif include_ordered:
            query = query.filter(DailyOrderBook.status.in_(["PENDING", "ORDERED"]))
        else:
            query = query.filter(DailyOrderBook.status == "PENDING")

        # Filter by entry_date when present (date-unique order book); fallback to created_at for pre-migration data
        if date_from:
            try:
                start = date.fromisoformat(date_from.strip())
                if hasattr(DailyOrderBook, "entry_date"):
                    query = query.filter(DailyOrderBook.entry_date >= start)
                else:
                    query = query.filter(func.date(DailyOrderBook.created_at) >= start)
            except (ValueError, TypeError):
                pass
        if date_to:
            try:
                end = date.fromisoformat(date_to.strip())
                if hasattr(DailyOrderBook, "entry_date"):
                    query = query.filter(DailyOrderBook.entry_date <= end)
                else:
                    query = query.filter(func.date(DailyOrderBook.created_at) <= end)
            except (ValueError, TypeError):
                pass

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

        def _get_stock(item_id):
            if item_id in stock_map:
                return stock_map[item_id]
            val = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id
            ).scalar()
            return int(val or 0)

        result = []
        for entry in entries:
            try:
                result.append(_serialize_order_book_entry(entry, _get_stock))
            except Exception as e:
                logging.getLogger(__name__).warning("Skipping order book entry %s: %s", entry.id, e)
        return JSONResponse(content=result, media_type="application/json")
    except Exception as e:
        logging.getLogger(__name__).exception("Order book list failed")
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to load order book", "error": str(e)},
            media_type="application/json",
        )


@router.post("", response_model=OrderBookEntryResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=OrderBookEntryResponse, status_code=status.HTTP_201_CREATED)
def create_order_book_entry(
    entry: OrderBookEntryCreate,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the entry"),
    db: Session = Depends(get_tenant_db)
):
    """
    Create a new order book entry.
    Returns 409 if the item is already in today's order book.
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
    
    # Entry date: request or today (items unique per branch, item, entry_date)
    entry_date_val = getattr(entry, "entry_date", None) or date.today()
    if hasattr(entry_date_val, "date") and callable(getattr(entry_date_val, "date", None)):
        entry_date_val = entry_date_val.date()

    # Item can only be in the order book once per date; if already PENDING or ORDERED for this date, tell the user
    existing_filter = [
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.item_id == entry.item_id,
        DailyOrderBook.status.in_(["PENDING", "ORDERED"])
    ]
    if hasattr(DailyOrderBook, "entry_date"):
        existing_filter.append(DailyOrderBook.entry_date == entry_date_val)
    existing_entry = db.query(DailyOrderBook).filter(*existing_filter).first()

    if existing_entry:
        if existing_entry.status == "ORDERED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This item is already on a purchase order (ordered). Check the order book."
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This item is already in the order book for this date."
        )
    # Resolve supplier when not provided: lowest unit cost (per wholesale) or item default from import
    resolved_supplier_id = entry.supplier_id
    if not resolved_supplier_id:
        resolved_supplier_id = OrderBookService.get_supplier_lowest_unit_cost(db, entry.item_id, company_id)
    # Default to wholesale unit (last unit costs are in wholesale)
    unit_name_val = (entry.unit_name or "").strip() or (item.wholesale_unit or item.base_unit or "unit").strip() or "unit"

    # Create new entry (catch race condition: duplicate insert from another request)
    reason = entry.reason or "MANUAL_ADD"
    create_kw = dict(
        company_id=company_id,
        branch_id=branch_id,
        item_id=entry.item_id,
        supplier_id=resolved_supplier_id,
        quantity_needed=entry.quantity_needed,
        unit_name=unit_name_val,
        reason=reason,
        source_reference_type=None,
        source_reference_id=None,
        notes=entry.notes,
        priority=entry.priority,
        status="PENDING",
        created_by=created_by
    )
    if hasattr(DailyOrderBook, "entry_date"):
        create_kw["entry_date"] = entry_date_val
    db_entry = DailyOrderBook(**create_kw)
    db.add(db_entry)
    try:
        db.flush()
        SnapshotService.upsert_search_snapshot_last_order_book(
            db, company_id, branch_id, entry.item_id, db_entry.created_at or datetime.utcnow()
        )
        db.commit()
        db.refresh(db_entry)
    except IntegrityError as e:
        db.rollback()
        logging.getLogger(__name__).warning("Order book duplicate on create (race or constraint): %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This item is already in the order book."
        )

    # Enhance response
    entry_dict = {
        "id": db_entry.id,
        "company_id": db_entry.company_id,
        "branch_id": db_entry.branch_id,
        "item_id": db_entry.item_id,
        "supplier_id": db_entry.supplier_id,
        "entry_date": getattr(db_entry, "entry_date", None),
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
    stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
        InventoryLedger.item_id == entry.item_id,
        InventoryLedger.branch_id == branch_id
    )
    current_stock = stock_query.scalar() or 0
    entry_dict["current_stock"] = int(current_stock)
    return OrderBookEntryResponse(**entry_dict)


@router.post("/bulk", response_model=OrderBookBulkCreateResponse, status_code=status.HTTP_201_CREATED)
def bulk_create_order_book_entries(
    bulk_data: OrderBookBulkCreate,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the entries"),
    db: Session = Depends(get_tenant_db)
):
    """
    Bulk create order book entries from selected items.
    Items already in the order book (PENDING or ORDERED) for the given date are skipped and returned.
    """
    created_entries = []
    skipped_item_ids: List[UUID] = []
    skipped_item_names: List[str] = []

    entry_date_val = getattr(bulk_data, "entry_date", None) or date.today()
    if hasattr(entry_date_val, "date") and callable(getattr(entry_date_val, "date", None)):
        entry_date_val = entry_date_val.date()

    for item_id in bulk_data.item_ids:
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            continue

        existing_filter = [
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.item_id == item_id,
            DailyOrderBook.status.in_(["PENDING", "ORDERED"])
        ]
        if hasattr(DailyOrderBook, "entry_date"):
            existing_filter.append(DailyOrderBook.entry_date == entry_date_val)
        existing = db.query(DailyOrderBook).filter(*existing_filter).first()

        if existing:
            skipped_item_ids.append(item_id)
            skipped_item_names.append(item.name or str(item_id))
            continue

        # Resolve supplier per item when not provided: lowest unit cost or item default
        resolved_supplier_id = bulk_data.supplier_id
        if not resolved_supplier_id:
            resolved_supplier_id = OrderBookService.get_supplier_lowest_unit_cost(db, item_id, company_id)
        # Default to wholesale unit (last unit costs are in wholesale)
        unit_name_val = (item.wholesale_unit or item.base_unit or "unit").strip() or "unit"

        create_kw = dict(
            company_id=company_id,
            branch_id=branch_id,
            item_id=item_id,
            supplier_id=resolved_supplier_id,
            quantity_needed=Decimal("1"),
            unit_name=unit_name_val,
            reason=bulk_data.reason or "MANUAL_ADD",
            source_reference_type=None,
            source_reference_id=None,
            notes=bulk_data.notes,
            priority=5,
            status="PENDING",
            created_by=created_by
        )
        if hasattr(DailyOrderBook, "entry_date"):
            create_kw["entry_date"] = entry_date_val
        entry = DailyOrderBook(**create_kw)
        db.add(entry)
        created_entries.append(entry)

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        logging.getLogger(__name__).warning("Order book bulk duplicate (race): %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more items are already in the order book. Please refresh and try again."
        )

    result = []
    for entry in created_entries:
        db.refresh(entry)
        entry_dict = {
            "id": entry.id,
            "company_id": entry.company_id,
            "branch_id": entry.branch_id,
            "item_id": entry.item_id,
            "entry_date": getattr(entry, "entry_date", None),
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
        stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            InventoryLedger.item_id == entry.item_id,
            InventoryLedger.branch_id == branch_id
        )
        current_stock = stock_query.scalar() or 0
        entry_dict["current_stock"] = int(current_stock)
        result.append(OrderBookEntryResponse(**entry_dict))

    return OrderBookBulkCreateResponse(
        entries=result,
        skipped_item_ids=skipped_item_ids,
        skipped_item_names=skipped_item_names
    )


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
    
    # Use the supplier selected in the modal for the entire purchase order.
    # Order book entries may have different or null supplier_id; the user's choice in the modal is the source of truth.
    supplier_id = request.supplier_id
    if not supplier_id:
        raise HTTPException(status_code=400, detail="Supplier ID is required")
    
    # Verify supplier exists
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")
    
    # Parse order date once
    order_date = datetime.fromisoformat(request.order_date.replace('Z', '+00:00')).date() if isinstance(request.order_date, str) else request.order_date

    for attempt in range(2):
        try:
            order_number = DocumentService.get_purchase_order_number(
                db, company_id, branch_id
            )

            total_amount = Decimal("0")
            order_items = []

            for entry in entries:
                item = db.query(Item).filter(Item.id == entry.item_id).first()
                if not item:
                    continue
                quantity = entry.quantity_needed
                unit_name = entry.unit_name
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
                    purchase_order_id=None,
                    item_id=entry.item_id,
                    unit_name=unit_name,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                order_items.append(order_item)

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

            for item in order_items:
                item.purchase_order_id = purchase_order.id
                db.add(item)

            db.flush()
            for item in order_items:
                SnapshotService.upsert_search_snapshot_last_order(
                    db, company_id, branch_id, item.item_id, order_date
                )

            for entry in entries:
                entry.status = "ORDERED"
                entry.purchase_order_id = purchase_order.id
                entry.supplier_id = supplier_id  # record the supplier used for this PO
                entry.updated_at = datetime.utcnow()
                # Keep entry in daily_order_book so it shows as "Converted" in the UI
                history_entry = OrderBookHistory(
                    company_id=entry.company_id,
                    branch_id=entry.branch_id,
                    item_id=entry.item_id,
                    supplier_id=supplier_id,
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
                # Do not delete: entry stays in order book labeled as converted (ORDERED)

            db.commit()
            db.refresh(purchase_order)

            return {
                "purchase_order_id": str(purchase_order.id),
                "order_number": purchase_order.order_number,
                "entries_processed": len(entries)
            }
        except IntegrityError as e:
            db.rollback()
            if attempt == 0:
                logging.getLogger(__name__).warning("Duplicate order number on create from order book, retrying: %s", e)
                continue
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A purchase order was already created (possible duplicate click). Check Purchase Orders list."
            ) from e


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
