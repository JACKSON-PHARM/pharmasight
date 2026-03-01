"""
Branch Inventory API - Branch orders, transfers, receipts.
Reuses: InventoryService (FEFO), SnapshotService, inventory_ledger (TRANSFER),
DocumentService, same RBAC pattern. No changes to purchase/sales/costing.
"""
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from app.dependencies import get_tenant_db, get_current_user
from app.models import (
    BranchOrder,
    BranchOrderLine,
    BranchTransfer,
    BranchTransferLine,
    BranchReceipt,
    BranchReceiptLine,
    Item,
    Branch,
    InventoryLedger,
    DailyOrderBook,
)
from app.schemas.branch_inventory import (
    BranchOrderCreate,
    BranchOrderUpdate,
    BranchOrderResponse,
    BranchOrderLineResponse,
    BranchTransferCreate,
    BranchTransferResponse,
    BranchTransferLineResponse,
    BranchReceiptResponse,
    BranchReceiptLineResponse,
)
from app.services.inventory_service import InventoryService
from app.services.snapshot_service import SnapshotService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.document_service import DocumentService

router = APIRouter()
logger = logging.getLogger(__name__)


def _branch_order_to_response(order: BranchOrder, db: Session) -> BranchOrderResponse:
    lines = []
    for line in order.lines:
        item = db.query(Item).filter(Item.id == line.item_id).first()
        lines.append(BranchOrderLineResponse(
            id=line.id,
            branch_order_id=line.branch_order_id,
            item_id=line.item_id,
            unit_name=line.unit_name,
            quantity=line.quantity,
            fulfilled_qty=line.fulfilled_qty,
            created_at=line.created_at,
            item_name=item.name if item else None,
        ))
    ord_br = db.query(Branch).filter(Branch.id == order.ordering_branch_id).first()
    sup_br = db.query(Branch).filter(Branch.id == order.supplying_branch_id).first()
    return BranchOrderResponse(
        id=order.id,
        company_id=order.company_id,
        ordering_branch_id=order.ordering_branch_id,
        supplying_branch_id=order.supplying_branch_id,
        order_number=order.order_number,
        status=order.status,
        created_by=order.created_by,
        created_at=order.created_at,
        updated_at=order.updated_at,
        lines=lines,
        ordering_branch_name=ord_br.name if ord_br else None,
        supplying_branch_name=sup_br.name if sup_br else None,
    )


def _transfer_to_response(t: BranchTransfer, db: Session) -> BranchTransferResponse:
    lines = []
    for line in t.lines:
        item = db.query(Item).filter(Item.id == line.item_id).first()
        lines.append(BranchTransferLineResponse(
            id=line.id,
            branch_transfer_id=line.branch_transfer_id,
            branch_order_line_id=line.branch_order_line_id,
            item_id=line.item_id,
            batch_number=line.batch_number,
            expiry_date=line.expiry_date.date() if hasattr(line.expiry_date, "date") and line.expiry_date else line.expiry_date,
            unit_name=line.unit_name,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
            created_at=line.created_at,
            item_name=item.name if item else None,
        ))
    sup = db.query(Branch).filter(Branch.id == t.supplying_branch_id).first()
    rec = db.query(Branch).filter(Branch.id == t.receiving_branch_id).first()
    return BranchTransferResponse(
        id=t.id,
        company_id=t.company_id,
        supplying_branch_id=t.supplying_branch_id,
        receiving_branch_id=t.receiving_branch_id,
        branch_order_id=t.branch_order_id,
        transfer_number=t.transfer_number,
        status=t.status,
        created_by=t.created_by,
        created_at=t.created_at,
        updated_at=t.updated_at,
        lines=lines,
        supplying_branch_name=sup.name if sup else None,
        receiving_branch_name=rec.name if rec else None,
    )


def _receipt_to_response(r: BranchReceipt, db: Session) -> BranchReceiptResponse:
    lines = []
    for line in r.lines:
        item = db.query(Item).filter(Item.id == line.item_id).first()
        lines.append(BranchReceiptLineResponse(
            id=line.id,
            branch_receipt_id=line.branch_receipt_id,
            item_id=line.item_id,
            batch_number=line.batch_number,
            expiry_date=line.expiry_date.date() if hasattr(line.expiry_date, "date") and line.expiry_date else line.expiry_date,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
            created_at=line.created_at,
            item_name=item.name if item else None,
        ))
    rec_br = db.query(Branch).filter(Branch.id == r.receiving_branch_id).first()
    return BranchReceiptResponse(
        id=r.id,
        company_id=r.company_id,
        receiving_branch_id=r.receiving_branch_id,
        branch_transfer_id=r.branch_transfer_id,
        receipt_number=r.receipt_number,
        status=r.status,
        received_at=r.received_at,
        received_by=r.received_by,
        created_at=r.created_at,
        lines=lines,
        receiving_branch_name=rec_br.name if rec_br else None,
    )


# ---------- Phase 2: Read-only API ----------

@router.get("/orders", response_model=List[BranchOrderResponse])
def get_branch_orders(
    ordering_branch_id: Optional[UUID] = Query(None),
    supplying_branch_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get branch orders; filter by ordering/supplying branch and status."""
    user, _ = user_db
    q = db.query(BranchOrder).options(selectinload(BranchOrder.lines))
    if ordering_branch_id is not None:
        q = q.filter(BranchOrder.ordering_branch_id == ordering_branch_id)
    if supplying_branch_id is not None:
        q = q.filter(BranchOrder.supplying_branch_id == supplying_branch_id)
    if status_filter:
        q = q.filter(BranchOrder.status == status_filter)
    q = q.order_by(BranchOrder.created_at.desc())
    orders = q.all()
    return [_branch_order_to_response(o, db) for o in orders]


@router.get("/orders/pending-supply", response_model=List[BranchOrderResponse])
def get_pending_branch_orders_for_supplying_branch(
    supplying_branch_id: UUID = Query(..., description="Supplying branch (fulfiller)"),
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get pending (BATCHED) branch orders that the given branch must fulfill."""
    user, _ = user_db
    orders = (
        db.query(BranchOrder)
        .options(selectinload(BranchOrder.lines))
        .filter(
            BranchOrder.supplying_branch_id == supplying_branch_id,
            BranchOrder.status == "BATCHED",
        )
        .order_by(BranchOrder.created_at.desc())
        .all()
    )
    return [_branch_order_to_response(o, db) for o in orders]


@router.get("/orders/{order_id}", response_model=BranchOrderResponse)
def get_branch_order(
    order_id: UUID,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get a single branch order by ID."""
    user, _ = user_db
    order = (
        db.query(BranchOrder)
        .options(selectinload(BranchOrder.lines))
        .filter(BranchOrder.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Branch order not found")
    return _branch_order_to_response(order, db)


@router.get("/transfers", response_model=List[BranchTransferResponse])
def get_branch_transfers(
    supplying_branch_id: Optional[UUID] = Query(None),
    receiving_branch_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get branch transfers; filter by supplying/receiving branch and status."""
    user, _ = user_db
    q = db.query(BranchTransfer).options(selectinload(BranchTransfer.lines))
    if supplying_branch_id is not None:
        q = q.filter(BranchTransfer.supplying_branch_id == supplying_branch_id)
    if receiving_branch_id is not None:
        q = q.filter(BranchTransfer.receiving_branch_id == receiving_branch_id)
    if status_filter:
        q = q.filter(BranchTransfer.status == status_filter)
    q = q.order_by(BranchTransfer.created_at.desc())
    transfers = q.all()
    return [_transfer_to_response(t, db) for t in transfers]


@router.get("/transfers/{transfer_id}", response_model=BranchTransferResponse)
def get_branch_transfer(
    transfer_id: UUID,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get a single branch transfer by ID."""
    user, _ = user_db
    t = (
        db.query(BranchTransfer)
        .options(selectinload(BranchTransfer.lines))
        .filter(BranchTransfer.id == transfer_id)
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Branch transfer not found")
    return _transfer_to_response(t, db)


@router.get("/receipts/pending", response_model=List[BranchReceiptResponse])
def get_pending_receipts(
    receiving_branch_id: UUID = Query(..., description="Receiving branch"),
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get pending receipts for the given receiving branch."""
    user, _ = user_db
    receipts = (
        db.query(BranchReceipt)
        .options(selectinload(BranchReceipt.lines))
        .filter(
            BranchReceipt.receiving_branch_id == receiving_branch_id,
            BranchReceipt.status == "PENDING",
        )
        .order_by(BranchReceipt.created_at.desc())
        .all()
    )
    return [_receipt_to_response(r, db) for r in receipts]


@router.get("/receipts", response_model=List[BranchReceiptResponse])
def get_branch_receipts(
    receiving_branch_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get branch receipts; filter by receiving branch and status."""
    user, _ = user_db
    q = db.query(BranchReceipt).options(selectinload(BranchReceipt.lines))
    if receiving_branch_id is not None:
        q = q.filter(BranchReceipt.receiving_branch_id == receiving_branch_id)
    if status_filter:
        q = q.filter(BranchReceipt.status == status_filter)
    q = q.order_by(BranchReceipt.created_at.desc())
    receipts = q.all()
    return [_receipt_to_response(r, db) for r in receipts]


@router.get("/receipts/{receipt_id}", response_model=BranchReceiptResponse)
def get_branch_receipt(
    receipt_id: UUID,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Get a single branch receipt by ID."""
    user, _ = user_db
    r = (
        db.query(BranchReceipt)
        .options(selectinload(BranchReceipt.lines))
        .filter(BranchReceipt.id == receipt_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Branch receipt not found")
    return _receipt_to_response(r, db)


# ---------- Phase 3: Branch Order Logic (draft, batch, lock) ----------

@router.post("/orders", response_model=BranchOrderResponse, status_code=status.HTTP_201_CREATED)
def create_branch_order(
    body: BranchOrderCreate,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Create a branch order (DRAFT). No inventory movement."""
    user, _ = user_db
    if not body.lines:
        raise HTTPException(status_code=400, detail="At least one line item required")
    # Validate branches same company
    ord_br = db.query(Branch).filter(Branch.id == body.ordering_branch_id).first()
    sup_br = db.query(Branch).filter(Branch.id == body.supplying_branch_id).first()
    if not ord_br or not sup_br:
        raise HTTPException(status_code=404, detail="Branch not found")
    if ord_br.company_id != sup_br.company_id:
        raise HTTPException(status_code=400, detail="Branches must belong to the same company")
    if body.ordering_branch_id == body.supplying_branch_id:
        raise HTTPException(status_code=400, detail="Ordering branch and supplying branch must be different (no self-order)")
    company_id = ord_br.company_id
    order = BranchOrder(
        company_id=company_id,
        ordering_branch_id=body.ordering_branch_id,
        supplying_branch_id=body.supplying_branch_id,
        status="DRAFT",
        created_by=user.id,
    )
    db.add(order)
    db.flush()
    for line in body.lines:
        item = db.query(Item).filter(Item.id == line.item_id).first()
        if not item:
            raise HTTPException(status_code=400, detail=f"Item {line.item_id} not found")
        db.add(BranchOrderLine(
            branch_order_id=order.id,
            item_id=line.item_id,
            unit_name=line.unit_name,
            quantity=line.quantity,
            fulfilled_qty=Decimal("0"),
        ))
    db.commit()
    db.refresh(order)
    order = db.query(BranchOrder).options(selectinload(BranchOrder.lines)).filter(BranchOrder.id == order.id).first()
    return _branch_order_to_response(order, db)


@router.patch("/orders/{order_id}", response_model=BranchOrderResponse)
def update_branch_order(
    order_id: UUID,
    body: BranchOrderUpdate,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Update a DRAFT branch order (lines only)."""
    user, _ = user_db
    order = db.query(BranchOrder).options(selectinload(BranchOrder.lines)).filter(BranchOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Branch order not found")
    if order.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Only DRAFT orders can be updated")
    if body.lines is not None:
        for existing in list(order.lines):
            db.delete(existing)
        for line in body.lines:
            item = db.query(Item).filter(Item.id == line.item_id).first()
            if not item:
                raise HTTPException(status_code=400, detail=f"Item {line.item_id} not found")
            db.add(BranchOrderLine(
                branch_order_id=order.id,
                item_id=line.item_id,
                unit_name=line.unit_name,
                quantity=line.quantity,
                fulfilled_qty=Decimal("0"),
            ))
    db.commit()
    db.refresh(order)
    order = db.query(BranchOrder).options(selectinload(BranchOrder.lines)).filter(BranchOrder.id == order.id).first()
    return _branch_order_to_response(order, db)


@router.post("/orders/{order_id}/batch", response_model=BranchOrderResponse)
def batch_branch_order(
    order_id: UUID,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Lock branch order (DRAFT -> BATCHED). Assigns order_number. No inventory movement."""
    user, _ = user_db
    order = (
        db.query(BranchOrder)
        .options(selectinload(BranchOrder.lines))
        .filter(BranchOrder.id == order_id)
        .with_for_update()
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Branch order not found")
    if order.status == "BATCHED":
        raise HTTPException(status_code=400, detail="Order is already batched (locked)")
    if order.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Only DRAFT orders can be batched")
    if not order.lines:
        raise HTTPException(status_code=400, detail="Order has no lines")
    try:
        order_number = DocumentService.get_branch_order_number(db, order.company_id, order.ordering_branch_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not assign order number: {e}")
    order.order_number = order_number
    order.status = "BATCHED"

    # Add/update order book entries for ordering branch (mark as ORDERED with branch_order_id), same pattern as PO
    entry_date = date.today()
    for line in order.lines:
        existing = (
            db.query(DailyOrderBook)
            .filter(
                DailyOrderBook.branch_id == order.ordering_branch_id,
                DailyOrderBook.item_id == line.item_id,
                DailyOrderBook.entry_date == entry_date,
                DailyOrderBook.status.in_(["PENDING", "ORDERED"]),
            )
            .first()
        )
        qty = float(line.quantity) if line.quantity else 0
        unit_name = (line.unit_name or "piece").strip() or "piece"
        if existing:
            existing.status = "ORDERED"
            existing.branch_order_id = order.id
            existing.source_reference_type = "branch_order"
            existing.source_reference_id = order.id
            existing.quantity_needed = (float(existing.quantity_needed or 0)) + qty
            existing.unit_name = unit_name
        else:
            ob_entry = DailyOrderBook(
                company_id=order.company_id,
                branch_id=order.ordering_branch_id,
                item_id=line.item_id,
                entry_date=entry_date,
                supplier_id=None,
                quantity_needed=Decimal(str(qty)),
                unit_name=unit_name,
                reason="BRANCH_ORDER",
                source_reference_type="branch_order",
                source_reference_id=order.id,
                status="ORDERED",
                branch_order_id=order.id,
                created_by=user.id,
            )
            db.add(ob_entry)

    db.commit()
    db.refresh(order)
    order = db.query(BranchOrder).options(selectinload(BranchOrder.lines)).filter(BranchOrder.id == order.id).first()
    return _branch_order_to_response(order, db)


# ---------- Phase 4: Branch Transfer Logic (FEFO, row lock, deduct) ----------

@router.post("/transfers", response_model=BranchTransferResponse, status_code=status.HTTP_201_CREATED)
def create_branch_transfer(
    body: BranchTransferCreate,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """Create a branch transfer in DRAFT (no stock deduction yet)."""
    user, _ = user_db
    if not body.lines:
        raise HTTPException(status_code=400, detail="At least one line required")
    sup_br = db.query(Branch).filter(Branch.id == body.supplying_branch_id).first()
    rec_br = db.query(Branch).filter(Branch.id == body.receiving_branch_id).first()
    if not sup_br or not rec_br:
        raise HTTPException(status_code=404, detail="Branch not found")
    if sup_br.company_id != rec_br.company_id:
        raise HTTPException(status_code=400, detail="Branches must belong to the same company")
    if body.supplying_branch_id == body.receiving_branch_id:
        raise HTTPException(status_code=400, detail="Supplying and receiving branch must be different (no self-transfer)")
    company_id = sup_br.company_id
    transfer = BranchTransfer(
        company_id=company_id,
        supplying_branch_id=body.supplying_branch_id,
        receiving_branch_id=body.receiving_branch_id,
        branch_order_id=body.branch_order_id,
        status="DRAFT",
        created_by=user.id,
    )
    db.add(transfer)
    db.flush()
    for line in body.lines:
        db.add(BranchTransferLine(
            branch_transfer_id=transfer.id,
            branch_order_line_id=line.branch_order_line_id,
            item_id=line.item_id,
            batch_number=line.batch_number,
            expiry_date=line.expiry_date,
            unit_name=line.unit_name,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
        ))
    db.commit()
    db.refresh(transfer)
    t = db.query(BranchTransfer).options(selectinload(BranchTransfer.lines)).filter(BranchTransfer.id == transfer.id).first()
    return _transfer_to_response(t, db)


@router.post("/transfers/{transfer_id}/complete", response_model=BranchTransferResponse)
def complete_branch_transfer(
    transfer_id: UUID,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """
    Complete branch transfer: FEFO allocation with row lock, deduct from supplying branch,
    log inventory_ledger (TRANSFER), update snapshot, update fulfilled_qty on order lines.
    Single transaction; rollback on any validation failure.
    """
    user, _ = user_db
    transfer = (
        db.query(BranchTransfer)
        .options(selectinload(BranchTransfer.lines))
        .filter(BranchTransfer.id == transfer_id)
        .with_for_update()
        .first()
    )
    if not transfer:
        raise HTTPException(status_code=404, detail="Branch transfer not found")
    if transfer.status == "COMPLETED":
        raise HTTPException(status_code=400, detail="Transfer is already completed")
    if transfer.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Only DRAFT transfers can be completed")
    if not transfer.lines:
        raise HTTPException(status_code=400, detail="Transfer has no lines")

    try:
        from collections import defaultdict

        # Assign transfer number
        transfer.transfer_number = DocumentService.get_branch_transfer_number(
            db, transfer.company_id, transfer.supplying_branch_id
        )
        supplying_branch_id = transfer.supplying_branch_id
        company_id = transfer.company_id

        # Aggregate requested quantity per item and map item_id -> branch_order_line_id (for fulfilled_qty)
        item_qty_base = defaultdict(lambda: 0.0)
        item_to_order_line_id = {}
        for line in transfer.lines:
            item = db.query(Item).filter(Item.id == line.item_id).first()
            if not item:
                raise HTTPException(status_code=400, detail=f"Item {line.item_id} not found")
            qty_base = InventoryService.convert_to_base_units(
                db, line.item_id, float(line.quantity), line.unit_name
            )
            item_qty_base[line.item_id] += qty_base
            if line.branch_order_line_id is not None:
                item_to_order_line_id[line.item_id] = line.branch_order_line_id

        # Audit: preserve requested quantities before FEFO line replacement (reconstructable intent)
        request_audit = [{"item_id": str(k), "quantity_base": v} for k, v in item_qty_base.items()]

        # FEFO allocate with lock per item; build batch-level lines and ledger entries
        ledger_entries = []
        new_transfer_lines = []  # (item_id, batch_number, expiry_date, unit_name, quantity, unit_cost, order_line_id)

        for item_id, quantity_needed_base in item_qty_base.items():
            allocations = InventoryService.allocate_stock_fefo_with_lock(
                db, item_id, supplying_branch_id, quantity_needed_base, exclude_expired=True
            )
            item = db.query(Item).filter(Item.id == item_id).first()
            unit_name = item.base_unit or "piece" if item else "piece"
            order_line_id = item_to_order_line_id.get(item_id)
            for alloc in allocations:
                qty = Decimal(str(alloc["quantity"]))
                uc = Decimal(str(alloc["unit_cost"]))
                entry = InventoryLedger(
                    company_id=company_id,
                    branch_id=supplying_branch_id,
                    item_id=item_id,
                    batch_number=alloc.get("batch_number"),
                    expiry_date=alloc.get("expiry_date"),
                    transaction_type="TRANSFER",
                    reference_type="branch_transfer",
                    reference_id=transfer.id,
                    quantity_delta=-qty,
                    unit_cost=uc,
                    total_cost=uc * qty,
                    created_by=user.id,
                )
                ledger_entries.append(entry)
                new_transfer_lines.append({
                    "item_id": item_id,
                    "batch_number": alloc.get("batch_number"),
                    "expiry_date": alloc.get("expiry_date"),
                    "unit_name": unit_name,
                    "quantity": qty,
                    "unit_cost": uc,
                    "branch_order_line_id": order_line_id,
                })

        for entry in ledger_entries:
            db.add(entry)
        db.flush()
        for entry in ledger_entries:
            SnapshotService.upsert_inventory_balance(
                db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta
            )

        # Inventory sanity guard: balance after deduction must be >= 0 for each affected (branch, item)
        for item_id in item_qty_base:
            balance = InventoryService.get_current_stock(db, item_id, supplying_branch_id)
            if balance < 0:
                raise ValueError(
                    f"Inventory sanity check failed: balance for item {item_id} at supplying branch would be {balance}"
                )

        # Replace transfer lines with batch-level lines from FEFO; store request audit on transfer
        transfer.request_audit = request_audit
        for old_line in list(transfer.lines):
            db.delete(old_line)
        db.flush()
        for row in new_transfer_lines:
            db.add(BranchTransferLine(
                branch_transfer_id=transfer.id,
                branch_order_line_id=row["branch_order_line_id"],
                item_id=row["item_id"],
                batch_number=row["batch_number"],
                expiry_date=row["expiry_date"],
                unit_name=row["unit_name"],
                quantity=row["quantity"],
                unit_cost=row["unit_cost"],
            ))
        db.flush()

        # Update fulfilled_qty on order lines
        order_line_fulfilled = defaultdict(lambda: Decimal("0"))
        for row in new_transfer_lines:
            ol_id = row["branch_order_line_id"]
            if ol_id is not None:
                order_line_fulfilled[ol_id] += row["quantity"]
        for order_line_id, delta in order_line_fulfilled.items():
            ol = db.query(BranchOrderLine).filter(BranchOrderLine.id == order_line_id).first()
            if ol:
                new_fulfilled = (ol.fulfilled_qty or Decimal("0")) + delta
                ol.fulfilled_qty = min(ol.quantity, new_fulfilled)  # Cap: over-fulfillment impossible

        transfer.status = "COMPLETED"

        # Create pending receipt for receiving branch (one receipt per transfer)
        receipt = BranchReceipt(
            company_id=company_id,
            receiving_branch_id=transfer.receiving_branch_id,
            branch_transfer_id=transfer.id,
            status="PENDING",
        )
        try:
            receipt.receipt_number = DocumentService.get_branch_receipt_number(
                db, company_id, transfer.receiving_branch_id
            )
        except Exception:
            receipt.receipt_number = f"BR-{transfer.transfer_number or transfer.id}"
        db.add(receipt)
        db.flush()
        for row in new_transfer_lines:
            db.add(BranchReceiptLine(
                branch_receipt_id=receipt.id,
                item_id=row["item_id"],
                batch_number=row["batch_number"],
                expiry_date=row["expiry_date"],
                quantity=row["quantity"],
                unit_cost=row["unit_cost"],
            ))

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.exception("Complete branch transfer failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Transfer failed: {str(e)}")

    db.refresh(transfer)
    t = db.query(BranchTransfer).options(selectinload(BranchTransfer.lines)).filter(BranchTransfer.id == transfer.id).first()
    return _transfer_to_response(t, db)


# ---------- Phase 5: Branch Receipt Logic ----------

@router.post("/receipts/{receipt_id}/receive", response_model=BranchReceiptResponse)
def confirm_branch_receipt(
    receipt_id: UUID,
    db: Session = Depends(get_tenant_db),
    user_db=Depends(get_current_user),
):
    """
    Confirm receipt: add inventory batch records to receiving branch (same batch_number,
    expiry_date, unit_cost). Log inventory_ledger TRANSFER (positive), update snapshot.
    """
    user, _ = user_db
    receipt = (
        db.query(BranchReceipt)
        .options(selectinload(BranchReceipt.lines), selectinload(BranchReceipt.transfer))
        .filter(BranchReceipt.id == receipt_id)
        .with_for_update()
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="Branch receipt not found")
    if receipt.status == "RECEIVED":
        raise HTTPException(status_code=400, detail="Receipt is already received")
    if receipt.status != "PENDING":
        raise HTTPException(status_code=400, detail="Only PENDING receipts can be confirmed")
    if not receipt.lines:
        raise HTTPException(status_code=400, detail="Receipt has no lines")

    try:
        receiving_branch_id = receipt.receiving_branch_id
        company_id = receipt.company_id
        ledger_entries = []
        for line in receipt.lines:
            qty = Decimal(str(line.quantity))
            uc = Decimal(str(line.unit_cost))
            entry = InventoryLedger(
                company_id=company_id,
                branch_id=receiving_branch_id,
                item_id=line.item_id,
                batch_number=line.batch_number,
                expiry_date=line.expiry_date,
                transaction_type="TRANSFER",
                reference_type="branch_receipt",
                reference_id=receipt.id,
                quantity_delta=qty,
                unit_cost=uc,
                total_cost=uc * qty,
                created_by=user.id,
            )
            ledger_entries.append(entry)
        for entry in ledger_entries:
            db.add(entry)
        db.flush()
        for entry in ledger_entries:
            SnapshotService.upsert_inventory_balance(
                db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta
            )
            SnapshotRefreshService.schedule_snapshot_refresh(db, entry.company_id, entry.branch_id, item_id=entry.item_id)
        receipt.status = "RECEIVED"
        receipt.received_at = datetime.utcnow()
        receipt.received_by = user.id
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Confirm receipt failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    db.refresh(receipt)
    r = db.query(BranchReceipt).options(selectinload(BranchReceipt.lines)).filter(BranchReceipt.id == receipt.id).first()
    return _receipt_to_response(r, db)
