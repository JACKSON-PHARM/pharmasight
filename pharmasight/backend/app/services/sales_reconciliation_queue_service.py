"""
Durable reconciliation state for batched sales (operational commit → async FEFO/ledger/GL).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import SalesReconciliationQueue, SalesInvoice

logger = logging.getLogger(__name__)

STATE_OPERATIONALLY_POSTED = "OPERATIONALLY_POSTED"
STATE_INVENTORY_ALLOCATED = "INVENTORY_ALLOCATED"
STATE_FINANCIALLY_POSTED = "FINANCIALLY_POSTED"
STATE_FULLY_RECONCILED = "FULLY_RECONCILED"
STATE_FAILED_RETRY_PENDING = "FAILED_RETRY_PENDING"


def enqueue_operational_posted(db: Session, invoice: SalesInvoice) -> SalesReconciliationQueue:
    """Create or refresh queue row after operational batch commit (idempotent per invoice)."""
    row = (
        db.query(SalesReconciliationQueue)
        .filter(SalesReconciliationQueue.sales_invoice_id == invoice.id)
        .first()
    )
    now = datetime.now(timezone.utc)
    if row:
        if row.state == STATE_FULLY_RECONCILED:
            return row
        row.state = STATE_OPERATIONALLY_POSTED
        row.operational_posted_at = row.operational_posted_at or now
        row.last_error = None
        return row
    row = SalesReconciliationQueue(
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        sales_invoice_id=invoice.id,
        state=STATE_OPERATIONALLY_POSTED,
        operational_posted_at=now,
    )
    db.add(row)
    db.flush()
    return row


def mark_inventory_allocated(db: Session, invoice_id: UUID) -> None:
    row = (
        db.query(SalesReconciliationQueue)
        .filter(SalesReconciliationQueue.sales_invoice_id == invoice_id)
        .first()
    )
    if not row:
        return
    now = datetime.now(timezone.utc)
    row.state = STATE_INVENTORY_ALLOCATED
    row.inventory_allocated_at = now
    row.last_error = None


def mark_financially_posted(db: Session, invoice_id: UUID) -> None:
    row = (
        db.query(SalesReconciliationQueue)
        .filter(SalesReconciliationQueue.sales_invoice_id == invoice_id)
        .first()
    )
    if not row:
        return
    now = datetime.now(timezone.utc)
    row.state = STATE_FINANCIALLY_POSTED
    row.financially_posted_at = now


def mark_fully_reconciled(db: Session, invoice_id: UUID) -> None:
    row = (
        db.query(SalesReconciliationQueue)
        .filter(SalesReconciliationQueue.sales_invoice_id == invoice_id)
        .first()
    )
    if not row:
        return
    now = datetime.now(timezone.utc)
    row.state = STATE_FULLY_RECONCILED
    row.fully_reconciled_at = now
    row.last_error = None


def mark_reconciliation_failed(db: Session, invoice_id: UUID, error: str) -> None:
    row = (
        db.query(SalesReconciliationQueue)
        .filter(SalesReconciliationQueue.sales_invoice_id == invoice_id)
        .first()
    )
    if not row:
        return
    row.state = STATE_FAILED_RETRY_PENDING
    row.attempt_count = (row.attempt_count or 0) + 1
    row.last_error = (error or "")[:2000]
