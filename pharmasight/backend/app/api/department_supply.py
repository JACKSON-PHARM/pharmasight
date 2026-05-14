"""
Department supply workflow: department orders stock from same-branch pharmacy,
pharmacy completes transfer (FEFO / DEPARTMENT_ISSUE), department confirms receipt into mini-store.
Scoped by company_id + branch access. Not tied to encounters.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from app.dependencies import (
    get_current_user,
    get_effective_company_id_for_user,
    get_tenant_db,
    ensure_user_has_branch_access,
)
from app.models import Item, User, InventoryLedger
from app.models.clinic import DepartmentStore, DepartmentStoreStock, DepartmentStoreMovement
from app.models.department_supply import (
    DepartmentSupplyOrder,
    DepartmentSupplyOrderLine,
    DepartmentSupplyTransfer,
    DepartmentSupplyTransferLine,
    DepartmentSupplyReceipt,
    DepartmentSupplyReceiptLine,
)
from app.schemas.department_supply import (
    DepartmentSupplyOrderCreate,
    DepartmentSupplyOrderResponse,
    DepartmentSupplyOrderLineResponse,
    DepartmentSupplyTransferFromOrder,
    DepartmentSupplyTransferResponse,
    DepartmentSupplyTransferLineResponse,
    DepartmentSupplyReceiptResponse,
    DepartmentSupplyReceiptLineResponse,
)
from app.services.document_number_service import DocumentNumberService, DOC_TYPE_DSO, DOC_TYPE_DST, DOC_TYPE_DSR
from app.services.inventory_service import InventoryService
from app.services.snapshot_service import SnapshotService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.order_book_service import OrderBookService
from app.services.etims.item_kra_sync_policy import enqueue_item_sync_for_stock_event
from app.config import settings

router = APIRouter(tags=["Department Supply"])
logger = logging.getLogger(__name__)


def _company_id(db: Session, user: User) -> UUID:
    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot resolve company")
    return cid


def _get_store(db: Session, store_id: UUID, company_id: UUID) -> DepartmentStore:
    s = db.query(DepartmentStore).filter(DepartmentStore.id == store_id, DepartmentStore.company_id == company_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Department store not found")
    return s


def _upsert_department_store_stock(db: Session, store_id: UUID, item_id: UUID, qty_delta_base: Decimal) -> DepartmentStoreStock:
    row = (
        db.query(DepartmentStoreStock)
        .filter(DepartmentStoreStock.store_id == store_id, DepartmentStoreStock.item_id == item_id)
        .with_for_update()
        .first()
    )
    if not row:
        row = DepartmentStoreStock(store_id=store_id, item_id=item_id, quantity_base=Decimal("0"))
        db.add(row)
        db.flush()
    next_qty = Decimal(str(row.quantity_base or 0)) + Decimal(str(qty_delta_base or 0))
    if next_qty < 0:
        raise HTTPException(status_code=400, detail="Insufficient department stock")
    row.quantity_base = next_qty
    db.add(row)
    return row


def _order_to_response(order: DepartmentSupplyOrder, db: Session) -> DepartmentSupplyOrderResponse:
    lines = []
    for line in order.lines:
        item = db.query(Item).filter(Item.id == line.item_id).first()
        lines.append(
            DepartmentSupplyOrderLineResponse(
                id=line.id,
                department_supply_order_id=line.department_supply_order_id,
                item_id=line.item_id,
                unit_name=line.unit_name,
                quantity=line.quantity,
                fulfilled_qty=line.fulfilled_qty or Decimal("0"),
                created_at=line.created_at,
                item_name=item.name if item else None,
            )
        )
    store = db.query(DepartmentStore).filter(DepartmentStore.id == order.department_store_id).first()
    return DepartmentSupplyOrderResponse(
        id=order.id,
        company_id=order.company_id,
        branch_id=order.branch_id,
        department_store_id=order.department_store_id,
        order_number=order.order_number,
        status=order.status,
        notes=order.notes,
        created_by=order.created_by,
        created_at=order.created_at,
        updated_at=order.updated_at,
        lines=lines,
        department_store_name=store.name if store else None,
        department_store_code=store.code if store else None,
    )


def _transfer_to_response(t: DepartmentSupplyTransfer, db: Session) -> DepartmentSupplyTransferResponse:
    lines = []
    for line in t.lines:
        item = db.query(Item).filter(Item.id == line.item_id).first()
        lines.append(
            DepartmentSupplyTransferLineResponse(
                id=line.id,
                department_supply_transfer_id=line.department_supply_transfer_id,
                department_supply_order_line_id=line.department_supply_order_line_id,
                item_id=line.item_id,
                batch_number=line.batch_number,
                expiry_date=line.expiry_date.date() if line.expiry_date and hasattr(line.expiry_date, "date") else line.expiry_date,
                unit_name=line.unit_name,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                created_at=line.created_at,
                item_name=item.name if item else None,
            )
        )
    store = db.query(DepartmentStore).filter(DepartmentStore.id == t.department_store_id).first()
    return DepartmentSupplyTransferResponse(
        id=t.id,
        company_id=t.company_id,
        branch_id=t.branch_id,
        department_store_id=t.department_store_id,
        department_supply_order_id=t.department_supply_order_id,
        transfer_number=t.transfer_number,
        status=t.status,
        created_by=t.created_by,
        created_at=t.created_at,
        updated_at=t.updated_at,
        lines=lines,
        department_store_name=store.name if store else None,
    )


def _receipt_to_response(r: DepartmentSupplyReceipt, db: Session) -> DepartmentSupplyReceiptResponse:
    lines = []
    for line in r.lines:
        item = db.query(Item).filter(Item.id == line.item_id).first()
        lines.append(
            DepartmentSupplyReceiptLineResponse(
                id=line.id,
                department_supply_receipt_id=line.department_supply_receipt_id,
                item_id=line.item_id,
                batch_number=line.batch_number,
                expiry_date=line.expiry_date.date() if line.expiry_date and hasattr(line.expiry_date, "date") else line.expiry_date,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                created_at=line.created_at,
                item_name=item.name if item else None,
            )
        )
    store = db.query(DepartmentStore).filter(DepartmentStore.id == r.department_store_id).first()
    tr = db.query(DepartmentSupplyTransfer).filter(DepartmentSupplyTransfer.id == r.department_supply_transfer_id).first()
    return DepartmentSupplyReceiptResponse(
        id=r.id,
        company_id=r.company_id,
        branch_id=r.branch_id,
        department_store_id=r.department_store_id,
        department_supply_transfer_id=r.department_supply_transfer_id,
        receipt_number=r.receipt_number,
        status=r.status,
        received_at=r.received_at,
        received_by=r.received_by,
        created_at=r.created_at,
        lines=lines,
        department_store_name=store.name if store else None,
        transfer_number=tr.transfer_number if tr else None,
    )


def _maybe_close_order(db: Session, order: DepartmentSupplyOrder) -> None:
    db.refresh(order)
    for ol in order.lines:
        if Decimal(str(ol.fulfilled_qty or 0)) < Decimal(str(ol.quantity or 0)):
            return
    order.status = "CLOSED"


@router.post("/orders", response_model=DepartmentSupplyOrderResponse, status_code=status.HTTP_201_CREATED)
def create_department_supply_order(
    body: DepartmentSupplyOrderCreate,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    store = _get_store(db, body.department_store_id, company_id)
    ensure_user_has_branch_access(db, user.id, store.branch_id)
    order = DepartmentSupplyOrder(
        company_id=company_id,
        branch_id=store.branch_id,
        department_store_id=store.id,
        status="DRAFT",
        notes=(body.notes or "").strip() or None,
        created_by=user.id,
    )
    db.add(order)
    db.flush()
    for line in body.lines:
        item = db.query(Item).filter(Item.id == line.item_id, Item.company_id == company_id).first()
        if not item:
            raise HTTPException(status_code=400, detail="Invalid item on order line")
        un = (line.unit_name or "").strip() or item.retail_unit or item.base_unit or "piece"
        db.add(
            DepartmentSupplyOrderLine(
                department_supply_order_id=order.id,
                item_id=line.item_id,
                unit_name=un,
                quantity=Decimal(str(line.quantity)),
                fulfilled_qty=Decimal("0"),
            )
        )
    db.commit()
    db.refresh(order)
    o = db.query(DepartmentSupplyOrder).options(selectinload(DepartmentSupplyOrder.lines)).filter(DepartmentSupplyOrder.id == order.id).first()
    return _order_to_response(o, db)


@router.get("/orders", response_model=List[DepartmentSupplyOrderResponse])
def list_department_supply_orders(
    branch_id: UUID = Query(...),
    department_store_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    ensure_user_has_branch_access(db, user.id, branch_id)
    q = db.query(DepartmentSupplyOrder).options(selectinload(DepartmentSupplyOrder.lines)).filter(
        DepartmentSupplyOrder.company_id == company_id,
        DepartmentSupplyOrder.branch_id == branch_id,
    )
    if department_store_id:
        q = q.filter(DepartmentSupplyOrder.department_store_id == department_store_id)
    if status_filter:
        q = q.filter(DepartmentSupplyOrder.status == status_filter)
    orders = q.order_by(DepartmentSupplyOrder.created_at.desc()).all()
    return [_order_to_response(o, db) for o in orders]


@router.get("/orders/{order_id}", response_model=DepartmentSupplyOrderResponse)
def get_department_supply_order(
    order_id: UUID,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    order = (
        db.query(DepartmentSupplyOrder)
        .options(selectinload(DepartmentSupplyOrder.lines))
        .filter(DepartmentSupplyOrder.id == order_id, DepartmentSupplyOrder.company_id == company_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    ensure_user_has_branch_access(db, user.id, order.branch_id)
    return _order_to_response(order, db)


@router.post("/orders/{order_id}/submit", response_model=DepartmentSupplyOrderResponse)
def submit_department_supply_order(
    order_id: UUID,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    order = (
        db.query(DepartmentSupplyOrder)
        .options(selectinload(DepartmentSupplyOrder.lines))
        .filter(DepartmentSupplyOrder.id == order_id, DepartmentSupplyOrder.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    ensure_user_has_branch_access(db, user.id, order.branch_id)
    if order.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Only DRAFT orders can be submitted")
    if not order.lines:
        raise HTTPException(status_code=400, detail="Order has no lines")
    order.order_number = DocumentNumberService.get_next(db, company_id, order.branch_id, DOC_TYPE_DSO)
    order.status = "OPEN"
    db.commit()
    db.refresh(order)
    return _order_to_response(order, db)


@router.post("/transfers/from-order", response_model=DepartmentSupplyTransferResponse, status_code=status.HTTP_201_CREATED)
def create_transfer_from_department_order(
    body: DepartmentSupplyTransferFromOrder,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    order = (
        db.query(DepartmentSupplyOrder)
        .options(selectinload(DepartmentSupplyOrder.lines))
        .filter(DepartmentSupplyOrder.id == body.department_supply_order_id, DepartmentSupplyOrder.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "OPEN":
        raise HTTPException(status_code=400, detail="Only OPEN orders can be transferred")
    ensure_user_has_branch_access(db, user.id, order.branch_id)

    dup = (
        db.query(DepartmentSupplyTransfer)
        .filter(
            DepartmentSupplyTransfer.department_supply_order_id == order.id,
            DepartmentSupplyTransfer.status == "DRAFT",
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=409, detail="A draft transfer already exists for this order; complete or delete it first")

    draft_lines: List[tuple] = []
    for ol in order.lines:
        rem = Decimal(str(ol.quantity)) - Decimal(str(ol.fulfilled_qty or 0))
        if rem <= 0:
            continue
        draft_lines.append((ol.id, ol.item_id, ol.unit_name, rem))

    if not draft_lines:
        raise HTTPException(status_code=400, detail="Nothing left to fulfill on this order")

    transfer = DepartmentSupplyTransfer(
        company_id=company_id,
        branch_id=order.branch_id,
        department_store_id=order.department_store_id,
        department_supply_order_id=order.id,
        status="DRAFT",
        created_by=user.id,
    )
    db.add(transfer)
    db.flush()
    for order_line_id, item_id, unit_name, qty in draft_lines:
        db.add(
            DepartmentSupplyTransferLine(
                department_supply_transfer_id=transfer.id,
                department_supply_order_line_id=order_line_id,
                item_id=item_id,
                unit_name=unit_name,
                quantity=qty,
                unit_cost=Decimal("0"),
            )
        )
    db.commit()
    t = (
        db.query(DepartmentSupplyTransfer)
        .options(selectinload(DepartmentSupplyTransfer.lines))
        .filter(DepartmentSupplyTransfer.id == transfer.id)
        .first()
    )
    return _transfer_to_response(t, db)


@router.get("/transfers", response_model=List[DepartmentSupplyTransferResponse])
def list_department_supply_transfers(
    branch_id: UUID = Query(...),
    department_store_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    ensure_user_has_branch_access(db, user.id, branch_id)
    q = db.query(DepartmentSupplyTransfer).options(selectinload(DepartmentSupplyTransfer.lines)).filter(
        DepartmentSupplyTransfer.company_id == company_id,
        DepartmentSupplyTransfer.branch_id == branch_id,
    )
    if department_store_id:
        q = q.filter(DepartmentSupplyTransfer.department_store_id == department_store_id)
    if status_filter:
        q = q.filter(DepartmentSupplyTransfer.status == status_filter)
    rows = q.order_by(DepartmentSupplyTransfer.created_at.desc()).all()
    return [_transfer_to_response(t, db) for t in rows]


@router.get("/transfers/{transfer_id}", response_model=DepartmentSupplyTransferResponse)
def get_department_supply_transfer(
    transfer_id: UUID,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    t = (
        db.query(DepartmentSupplyTransfer)
        .options(selectinload(DepartmentSupplyTransfer.lines))
        .filter(DepartmentSupplyTransfer.id == transfer_id, DepartmentSupplyTransfer.company_id == company_id)
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Transfer not found")
    ensure_user_has_branch_access(db, user.id, t.branch_id)
    return _transfer_to_response(t, db)


@router.post("/transfers/{transfer_id}/complete", response_model=DepartmentSupplyTransferResponse)
def complete_department_supply_transfer(
    transfer_id: UUID,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    transfer = (
        db.query(DepartmentSupplyTransfer)
        .options(selectinload(DepartmentSupplyTransfer.lines))
        .filter(DepartmentSupplyTransfer.id == transfer_id, DepartmentSupplyTransfer.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    ensure_user_has_branch_access(db, user.id, transfer.branch_id)
    if transfer.status == "COMPLETED":
        raise HTTPException(status_code=400, detail="Transfer already completed")
    if transfer.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Only DRAFT transfers can be completed")
    if not transfer.lines:
        raise HTTPException(status_code=400, detail="Transfer has no lines")

    branch_id = transfer.branch_id
    ledger_entries: List[InventoryLedger] = []
    new_transfer_lines: List[dict] = []
    request_audit: List[dict] = []

    try:
        transfer.transfer_number = DocumentNumberService.get_next(db, company_id, branch_id, DOC_TYPE_DST)

        for line in transfer.lines:
            item = db.query(Item).filter(Item.id == line.item_id).first()
            if not item:
                raise HTTPException(status_code=400, detail=f"Item {line.item_id} not found")
            qty_base = InventoryService.convert_to_base_units(db, line.item_id, float(line.quantity), line.unit_name)
            request_audit.append(
                {
                    "item_id": str(line.item_id),
                    "department_supply_order_line_id": str(line.department_supply_order_line_id)
                    if line.department_supply_order_line_id
                    else None,
                    "quantity_base": qty_base,
                }
            )
            allocations = InventoryService.allocate_stock_fefo_with_lock(
                db, line.item_id, branch_id, qty_base, exclude_expired=True
            )
            unit_name = item.base_unit or "piece"
            order_line_id = line.department_supply_order_line_id
            for alloc in allocations:
                qty = Decimal(str(alloc["quantity"]))
                uc = Decimal(str(alloc["unit_cost"]))
                entry = InventoryLedger(
                    company_id=company_id,
                    branch_id=branch_id,
                    item_id=line.item_id,
                    batch_number=alloc.get("batch_number"),
                    expiry_date=alloc.get("expiry_date"),
                    transaction_type="DEPARTMENT_ISSUE",
                    reference_type="department_supply_transfer",
                    reference_id=transfer.id,
                    document_number=transfer.transfer_number,
                    quantity_delta=-qty,
                    unit_cost=uc,
                    total_cost=uc * qty,
                    created_by=user.id,
                    notes="Department supply transfer (pharmacy issue)",
                )
                ledger_entries.append(entry)
                new_transfer_lines.append(
                    {
                        "item_id": line.item_id,
                        "batch_number": alloc.get("batch_number"),
                        "expiry_date": alloc.get("expiry_date"),
                        "unit_name": unit_name,
                        "quantity": qty,
                        "unit_cost": uc,
                        "department_supply_order_line_id": order_line_id,
                    }
                )

        for entry in ledger_entries:
            db.add(entry)
        db.flush()
        for entry in ledger_entries:
            SnapshotService.upsert_inventory_balance(
                db,
                entry.company_id,
                entry.branch_id,
                entry.item_id,
                entry.quantity_delta,
                document_number=entry.document_number or transfer.transfer_number,
            )
            SnapshotRefreshService.schedule_snapshot_refresh(db, entry.company_id, entry.branch_id, item_id=entry.item_id)
        max_attempts = max(int(settings.KRA_OUTBOX_MAX_ATTEMPTS or 12), 1)
        for entry in ledger_entries:
            item = db.query(Item).filter(Item.id == entry.item_id).first()
            if item:
                enqueue_item_sync_for_stock_event(
                    db,
                    item=item,
                    branch_id=branch_id,
                    source="stock.department_issue",
                    max_attempts=max_attempts,
                )

        item_ids_touched = list({line.item_id for line in transfer.lines})
        for item_id in item_ids_touched:
            balance = InventoryService.get_current_stock(db, item_id, branch_id)
            if balance < 0:
                raise ValueError(f"Inventory sanity check failed for item {item_id}")

        transfer.request_audit = {"lines": request_audit}
        for old_line in list(transfer.lines):
            db.delete(old_line)
        db.flush()
        for row in new_transfer_lines:
            db.add(
                DepartmentSupplyTransferLine(
                    department_supply_transfer_id=transfer.id,
                    department_supply_order_line_id=row["department_supply_order_line_id"],
                    item_id=row["item_id"],
                    batch_number=row["batch_number"],
                    expiry_date=row["expiry_date"],
                    unit_name=row["unit_name"],
                    quantity=row["quantity"],
                    unit_cost=row["unit_cost"],
                )
            )
        db.flush()

        order_line_fulfilled = defaultdict(lambda: Decimal("0"))
        for row in new_transfer_lines:
            ol_id = row["department_supply_order_line_id"]
            if ol_id is not None:
                order_line_fulfilled[ol_id] += row["quantity"]
        for order_line_id, delta_base in order_line_fulfilled.items():
            ol = db.query(DepartmentSupplyOrderLine).filter(DepartmentSupplyOrderLine.id == order_line_id).first()
            if ol:
                per_one_base = InventoryService.convert_to_base_units(db, ol.item_id, 1.0, ol.unit_name)
                if per_one_base <= 0:
                    per_one_base = 1.0
                increment_line_units = Decimal(str(delta_base)) / Decimal(str(per_one_base))
                new_fulfilled = Decimal(str(ol.fulfilled_qty or 0)) + increment_line_units
                ol.fulfilled_qty = min(Decimal(str(ol.quantity)), new_fulfilled)

        transfer.status = "COMPLETED"

        receipt = DepartmentSupplyReceipt(
            company_id=company_id,
            branch_id=branch_id,
            department_store_id=transfer.department_store_id,
            department_supply_transfer_id=transfer.id,
            status="PENDING",
        )
        receipt.receipt_number = DocumentNumberService.get_next(db, company_id, branch_id, DOC_TYPE_DSR)
        db.add(receipt)
        db.flush()
        for row in new_transfer_lines:
            db.add(
                DepartmentSupplyReceiptLine(
                    department_supply_receipt_id=receipt.id,
                    item_id=row["item_id"],
                    batch_number=row["batch_number"],
                    expiry_date=row["expiry_date"],
                    quantity=row["quantity"],
                    unit_cost=row["unit_cost"],
                )
            )

        if transfer.department_supply_order_id:
            parent_order = (
                db.query(DepartmentSupplyOrder)
                .options(selectinload(DepartmentSupplyOrder.lines))
                .filter(DepartmentSupplyOrder.id == transfer.department_supply_order_id)
                .first()
            )
            if parent_order:
                _maybe_close_order(db, parent_order)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.exception("complete_department_supply_transfer failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    affected_items = list({e.item_id for e in ledger_entries})
    for item_id in affected_items:
        try:
            OrderBookService.check_and_add_to_order_book(
                db=db,
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                user_id=user.id,
                is_auto=True,
            )
        except Exception:
            logger.exception("Order-book check failed after department supply transfer item_id=%s", item_id)

    t = (
        db.query(DepartmentSupplyTransfer)
        .options(selectinload(DepartmentSupplyTransfer.lines))
        .filter(DepartmentSupplyTransfer.id == transfer.id)
        .first()
    )
    return _transfer_to_response(t, db)


@router.get("/receipts", response_model=List[DepartmentSupplyReceiptResponse])
def list_department_supply_receipts(
    branch_id: UUID = Query(...),
    department_store_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    ensure_user_has_branch_access(db, user.id, branch_id)
    q = db.query(DepartmentSupplyReceipt).options(selectinload(DepartmentSupplyReceipt.lines)).filter(
        DepartmentSupplyReceipt.company_id == company_id,
        DepartmentSupplyReceipt.branch_id == branch_id,
    )
    if department_store_id:
        q = q.filter(DepartmentSupplyReceipt.department_store_id == department_store_id)
    if status_filter:
        q = q.filter(DepartmentSupplyReceipt.status == status_filter)
    rows = q.order_by(DepartmentSupplyReceipt.created_at.desc()).all()
    return [_receipt_to_response(r, db) for r in rows]


@router.get("/receipts/{receipt_id}", response_model=DepartmentSupplyReceiptResponse)
def get_department_supply_receipt(
    receipt_id: UUID,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    r = (
        db.query(DepartmentSupplyReceipt)
        .options(selectinload(DepartmentSupplyReceipt.lines))
        .filter(DepartmentSupplyReceipt.id == receipt_id, DepartmentSupplyReceipt.company_id == company_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found")
    ensure_user_has_branch_access(db, user.id, r.branch_id)
    return _receipt_to_response(r, db)


@router.post("/receipts/{receipt_id}/receive", response_model=DepartmentSupplyReceiptResponse)
def confirm_department_supply_receipt(
    receipt_id: UUID,
    auth=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    receipt = (
        db.query(DepartmentSupplyReceipt)
        .options(selectinload(DepartmentSupplyReceipt.lines))
        .filter(DepartmentSupplyReceipt.id == receipt_id, DepartmentSupplyReceipt.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    ensure_user_has_branch_access(db, user.id, receipt.branch_id)
    if receipt.status == "RECEIVED":
        raise HTTPException(status_code=400, detail="Receipt already confirmed")
    if receipt.status != "PENDING":
        raise HTTPException(status_code=400, detail="Only PENDING receipts can be confirmed")
    if not receipt.lines:
        raise HTTPException(status_code=400, detail="Receipt has no lines")

    store_id = receipt.department_store_id
    try:
        for line in receipt.lines:
            qty = Decimal(str(line.quantity))
            if qty <= 0:
                continue
            _upsert_department_store_stock(db, store_id, line.item_id, qty)
            db.add(
                DepartmentStoreMovement(
                    company_id=company_id,
                    branch_id=receipt.branch_id,
                    store_id=store_id,
                    item_id=line.item_id,
                    movement_type="ISSUE_IN",
                    quantity_delta_base=qty,
                    reference_type="department_supply_receipt",
                    reference_id=receipt.id,
                    notes="Receipt from pharmacy transfer",
                    created_by=user.id,
                )
            )
        received_at = datetime.now(timezone.utc)
        receipt.status = "RECEIVED"
        receipt.received_at = received_at
        receipt.received_by = user.id
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("confirm_department_supply_receipt failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    r = (
        db.query(DepartmentSupplyReceipt)
        .options(selectinload(DepartmentSupplyReceipt.lines))
        .filter(DepartmentSupplyReceipt.id == receipt.id)
        .first()
    )
    return _receipt_to_response(r, db)
