"""Transactional outbox helpers for KRA execution events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.kra_event_outbox import KraEventOutbox
from app.models.item import Item
from app.models.sale import SalesInvoice


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class KraOutboxService:
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
                KraEventOutbox.processing_status.in_(("pending", "retry")),
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
    def mark_processed(db: Session, row: KraEventOutbox) -> None:
        now = datetime.now(timezone.utc)
        row.processing_status = "processed"
        row.processed_at = now
        row.leased_until = None
        row.lease_owner = None
        row.last_error = None
        row.updated_at = now
        db.flush()

    @staticmethod
    def mark_retry(db: Session, row: KraEventOutbox, *, error: str) -> None:
        now = datetime.now(timezone.utc)
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
