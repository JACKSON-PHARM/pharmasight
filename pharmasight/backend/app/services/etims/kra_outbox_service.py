"""Transactional outbox helpers for KRA execution events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID, uuid4, uuid5

from sqlalchemy.orm import Session

from app.models.kra_event_outbox import KraEventOutbox
from app.models.inventory import InventoryLedger
from app.models.item import Item
from app.models.item import ItemBranchKraSync
from app.models.sale import SalesInvoice
from app.services.etims.kra_stock_push_service import _stock_io_tax_ty_cd_for_item

# Stable namespace for deterministic aggregate_id (coalesce pending ledger-align jobs per branch+item).
_STOCK_LEDGER_ALIGN_NAMESPACE = UUID("918320b5-7b82-4d01-86de-8384059a3e89")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class KraOutboxService:
    @staticmethod
    def upsert_item_branch_sync_status(
        db: Session,
        *,
        company_id: UUID,
        item_id: UUID,
        branch_id: UUID,
        status: str,
        retry_count: int | None = None,
        last_error: str | None = None,
        http_status: int | None = None,
        kra_result_cd: str | None = None,
        kra_result_msg: str | None = None,
        response_payload_json: Dict[str, Any] | None = None,
        synced_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
    ) -> ItemBranchKraSync:
        row = (
            db.query(ItemBranchKraSync)
            .filter(
                ItemBranchKraSync.item_id == item_id,
                ItemBranchKraSync.branch_id == branch_id,
            )
            .first()
        )
        if not row:
            row = ItemBranchKraSync(
                company_id=company_id,
                item_id=item_id,
                branch_id=branch_id,
            )
            db.add(row)
        row.status = (status or "pending")[:30]
        if retry_count is not None:
            row.retry_count = max(int(retry_count), 0)
        if last_error is not None:
            row.last_error = (last_error or "")[:4000] or None
        elif (status or "").strip().lower() == "synced":
            # Clear stale error text when a branch row transitions to synced.
            row.last_error = None
        if http_status is not None:
            row.http_status = int(http_status)
        if kra_result_cd is not None:
            row.kra_result_cd = (kra_result_cd or "")[:32] or None
        if kra_result_msg is not None:
            row.kra_result_msg = (kra_result_msg or "")[:4000] or None
        if response_payload_json is not None:
            row.response_payload_json = response_payload_json
        if synced_at is not None:
            row.synced_at = synced_at
        if last_attempt_at is not None:
            row.last_attempt_at = last_attempt_at
        db.flush()
        return row

    @staticmethod
    def build_sale_completed_snapshot(invoice: SalesInvoice) -> Dict[str, Any]:
        return {
            "invoice": {
                "id": str(invoice.id),
                "company_id": str(invoice.company_id),
                "branch_id": str(invoice.branch_id),
                "invoice_no": invoice.invoice_no,
                "invoice_date": str(invoice.invoice_date),
                "status": invoice.status,
                "submission_status": invoice.submission_status,
                "payment_mode": invoice.payment_mode,
                "payment_status": invoice.payment_status,
                "total_exclusive": str(invoice.total_exclusive or 0),
                "vat_amount": str(invoice.vat_amount or 0),
                "total_inclusive": str(invoice.total_inclusive or 0),
                "customer_name": invoice.customer_name,
                "customer_pin": invoice.customer_pin,
                "batched_at": _iso(getattr(invoice, "batched_at", None)),
                "created_at": _iso(getattr(invoice, "created_at", None)),
            },
            "items": [
                {
                    "sales_invoice_item_id": str(line.id),
                    "item_id": str(line.item_id),
                    "item_name": line.item_name,
                    "item_code": line.item_code,
                    "unit_name": line.unit_name,
                    "quantity": str(line.quantity or 0),
                    "unit_price_exclusive": str(line.unit_price_exclusive or 0),
                    "line_total_exclusive": str(line.line_total_exclusive or 0),
                    "line_total_inclusive": str(line.line_total_inclusive or 0),
                    "vat_rate": str(line.vat_rate or 0),
                    "vat_amount": str(line.vat_amount or 0),
                    "vat_cat_cd": getattr(line, "vat_cat_cd", None),
                    "tax_ty_cd": getattr(line, "tax_ty_cd", None),
                    "item_cls_cd": getattr(line, "item_cls_cd", None),
                    "pkg_unit_cd": getattr(line, "pkg_unit_cd", None),
                    "qty_unit_cd": getattr(line, "qty_unit_cd", None),
                }
                for line in list(invoice.items or [])
            ],
        }

    @staticmethod
    def enqueue_sale_completed(
        db: Session,
        *,
        invoice: SalesInvoice,
        source: str,
        max_attempts: int = 12,
    ) -> KraEventOutbox:
        existing = (
            db.query(KraEventOutbox)
            .filter(
                KraEventOutbox.event_type == "sale.completed",
                KraEventOutbox.aggregate_id == invoice.id,
            )
            .first()
        )
        if existing:
            return existing
        row = KraEventOutbox(
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            aggregate_type="sales_invoice",
            aggregate_id=invoice.id,
            event_type="sale.completed",
            payload_json={
                "version": 1,
                "source": source,
                "snapshot_created_at": datetime.now(timezone.utc).isoformat(),
                "snapshot": KraOutboxService.build_sale_completed_snapshot(invoice),
            },
            processing_status="pending",
            max_attempts=max_attempts,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def build_item_updated_snapshot(item: Item) -> Dict[str, Any]:
        return {
            "item": {
                "id": str(item.id),
                "company_id": str(item.company_id),
                "sku": item.sku,
                "name": item.name,
                "is_active": bool(item.is_active),
                "vat_category": item.vat_category,
                "vat_rate": str(item.vat_rate or 0),
                "kra_item_cls_cd": item.kra_item_cls_cd,
                "kra_pkg_unit_cd": item.kra_pkg_unit_cd,
                "kra_qty_unit_cd": item.kra_qty_unit_cd,
                "kra_tax_ty_cd": item.kra_tax_ty_cd,
                "updated_at": _iso(getattr(item, "updated_at", None)),
            }
        }

    @staticmethod
    def enqueue_item_updated(
        db: Session,
        *,
        item: Item,
        branch_id: UUID,
        source: str,
        max_attempts: int = 12,
    ) -> KraEventOutbox:
        row = KraEventOutbox(
            company_id=item.company_id,
            branch_id=branch_id,
            aggregate_type="item",
            aggregate_id=item.id,
            event_type="item.updated",
            payload_json={
                "version": 1,
                "source": source,
                "snapshot_created_at": datetime.now(timezone.utc).isoformat(),
                "snapshot": KraOutboxService.build_item_updated_snapshot(item),
            },
            processing_status="pending",
            max_attempts=max_attempts,
        )
        db.add(row)
        db.flush()
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=item.company_id,
            item_id=item.id,
            branch_id=branch_id,
            status="pending",
            last_error=None,
            last_attempt_at=datetime.now(timezone.utc),
        )
        return row

    @staticmethod
    def enqueue_inventory_stock_in(
        db: Session,
        *,
        ledger: InventoryLedger,
        source: str,
        max_attempts: int = 12,
    ) -> KraEventOutbox | None:
        """One durable job per ledger row: ``insertStockIO`` + ``saveStockMaster`` on worker."""
        existing = (
            db.query(KraEventOutbox)
            .filter(
                KraEventOutbox.event_type == "inventory.stock_in",
                KraEventOutbox.aggregate_id == ledger.id,
                KraEventOutbox.processing_status.in_(("pending", "retry", "processing")),
            )
            .first()
        )
        if existing:
            return existing
        item_for_payload = (
            db.query(Item)
            .filter(Item.id == ledger.item_id, Item.company_id == ledger.company_id)
            .first()
        )
        kra_item_code_snap: str | None = None
        insert_stock_tax_ty_snap: str | None = None
        if item_for_payload:
            kra_item_code_snap = str(getattr(item_for_payload, "kra_item_code", None) or "").strip().upper() or None
            insert_stock_tax_ty_snap = _stock_io_tax_ty_cd_for_item(item_for_payload)
        row = KraEventOutbox(
            company_id=ledger.company_id,
            branch_id=ledger.branch_id,
            aggregate_type="inventory_ledger",
            aggregate_id=ledger.id,
            event_type="inventory.stock_in",
            payload_json={
                "version": 1,
                "source": source,
                "ledger_id": str(ledger.id),
                "transaction_type": ledger.transaction_type,
                "quantity_delta": str(ledger.quantity_delta),
                "item_id": str(ledger.item_id),
                "kra_item_code": kra_item_code_snap,
                "insert_stock_tax_ty_cd": insert_stock_tax_ty_snap,
                "reference_type": ledger.reference_type,
                "document_number": ledger.document_number,
            },
            processing_status="pending",
            max_attempts=max_attempts,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def stable_aggregate_id_for_stock_ledger_align(*, branch_id: UUID, item_id: UUID) -> UUID:
        return uuid5(_STOCK_LEDGER_ALIGN_NAMESPACE, f"{branch_id}:{item_id}")

    @staticmethod
    def enqueue_inventory_stock_ledger_align(
        db: Session,
        *,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        source: str,
        max_attempts: int = 12,
        debounce_seconds: int | None = None,
    ) -> KraEventOutbox | None:
        """
        Queue ``saveStockMaster`` from current PharmaSight ledger (no insertStockIO).

        Coalesces: one pending/retry row per (branch_id, item_id) by stable aggregate_id; refreshes
        ``available_at`` when debounce_seconds > 0 so bursts collapse into a single KRA post.
        If another row is already ``processing``, enqueues a separate row (random aggregate_id) so
        new movements are not lost while the worker holds the lease.
        """
        from app.config import settings

        stable_id = KraOutboxService.stable_aggregate_id_for_stock_ledger_align(
            branch_id=branch_id, item_id=item_id
        )
        deb = debounce_seconds
        if deb is None:
            deb = max(int(getattr(settings, "KRA_STOCK_LEDGER_SYNC_DEBOUNCE_SECONDS", 2) or 0), 0)

        existing = (
            db.query(KraEventOutbox)
            .filter(
                KraEventOutbox.event_type == "inventory.stock_ledger_align",
                KraEventOutbox.aggregate_id == stable_id,
                KraEventOutbox.processing_status.in_(("pending", "retry")),
            )
            .first()
        )
        now = datetime.now(timezone.utc)
        if existing:
            pl = existing.payload_json if isinstance(existing.payload_json, dict) else {}
            prev_src = str(pl.get("source") or "").strip()
            merged_src = f"{prev_src},{source}".strip(",") if prev_src else source
            existing.payload_json = {**pl, "source": merged_src[:2000]}
            if deb > 0:
                existing.available_at = now + timedelta(seconds=deb)
            existing.updated_at = now
            db.flush()
            return existing

        in_flight = (
            db.query(KraEventOutbox)
            .filter(
                KraEventOutbox.event_type == "inventory.stock_ledger_align",
                KraEventOutbox.aggregate_id == stable_id,
                KraEventOutbox.processing_status == "processing",
            )
            .first()
        )
        agg_id = uuid4() if in_flight else stable_id

        row = KraEventOutbox(
            company_id=company_id,
            branch_id=branch_id,
            aggregate_type="item_branch_stock",
            aggregate_id=agg_id,
            event_type="inventory.stock_ledger_align",
            payload_json={
                "version": 1,
                "source": (source or "")[:500],
                "item_id": str(item_id),
            },
            processing_status="pending",
            max_attempts=max_attempts,
            available_at=now + timedelta(seconds=deb) if deb > 0 else now,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def claim_events(
        db: Session,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> List[KraEventOutbox]:
        now = datetime.now(timezone.utc)
        rows = (
            db.query(KraEventOutbox)
            .filter(
                KraEventOutbox.processing_status.in_(("pending", "retry", "processing")),
                KraEventOutbox.available_at <= now,
                (KraEventOutbox.leased_until.is_(None) | (KraEventOutbox.leased_until < now)),
            )
            .order_by(KraEventOutbox.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        leased_until = now + timedelta(seconds=max(lease_seconds, 10))
        for row in rows:
            row.processing_status = "processing"
            row.lease_owner = worker_id
            row.leased_until = leased_until
            row.updated_at = now
        db.flush()
        return rows

    @staticmethod
    def mark_processed(db: Session, row: KraEventOutbox, *, skip_reason: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        row.processing_status = "processed"
        row.processed_at = now
        row.leased_until = None
        row.lease_owner = None
        if skip_reason:
            row.last_error = (skip_reason.strip()[:4000]) or None
        else:
            row.last_error = None
        row.updated_at = now
        db.flush()

    @staticmethod
    def mark_retry(db: Session, row: KraEventOutbox, *, error: str) -> None:
        now = datetime.now(timezone.utc)
        err_text = (error or "").strip().lower()
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.last_error = (error or "unknown")[:4000]
        row.last_error_at = now
        row.leased_until = None
        row.lease_owner = None
        row.updated_at = now
        if row.attempt_count >= int(row.max_attempts or 12):
            row.processing_status = "dead_letter"
            row.available_at = now
        else:
            row.processing_status = "retry"
            # saveItem itemCd sequence recovery is deterministic; retry quickly with corrected suffix.
            if "invalid itemcd sequence" in err_text or "expected sequence ending with" in err_text:
                backoff_sec = 1
            else:
                backoff_sec = min(900, (2 ** min(row.attempt_count, 8)))
            row.available_at = now + timedelta(seconds=backoff_sec)
        db.flush()

    @staticmethod
    def reset_for_requeue(db: Session, row: KraEventOutbox) -> None:
        now = datetime.now(timezone.utc)
        row.processing_status = "pending"
        row.attempt_count = 0
        row.available_at = now
        row.leased_until = None
        row.lease_owner = None
        row.last_error = None
        row.last_error_at = None
        row.processed_at = None
        row.updated_at = now
        db.flush()
