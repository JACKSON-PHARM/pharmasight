"""
Wire constitutional commercial transactions to sales invoices (Layer 2 — Phase B).

Lifecycle hooks are best-effort: failures are logged and do not block sales/KRA.
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.commercial_transaction_state import TransactionState
from app.models.commercial_transaction import CommercialTransaction
from app.models.sale import SalesInvoice
from app.services.invoice_workflow_policy import get_invoice_workflow_type_for_branch
from app.services.transaction_state_engine import (
    TransactionStateError,
    TransitionActor,
    TransitionContext,
    create_commercial_transaction,
    current_state,
    transition_transaction,
)

logger = logging.getLogger(__name__)

SPINE_ORDER: List[TransactionState] = [
    TransactionState.DRAFT,
    TransactionState.OPERATIONALLY_COMPLETE,
    TransactionState.COMMERCIALLY_COMPLETE,
    TransactionState.BILLING_ACCEPTED,
    TransactionState.FISCAL_READY,
    TransactionState.FISCAL_EXTERNALIZED,
]


def get_commercial_transaction_for_invoice(
    db: Session,
    sales_invoice_id: UUID,
) -> Optional[CommercialTransaction]:
    return (
        db.query(CommercialTransaction)
        .filter(CommercialTransaction.sales_invoice_id == sales_invoice_id)
        .order_by(CommercialTransaction.created_at.asc())
        .first()
    )


def get_or_create_for_sales_invoice(
    db: Session,
    invoice: SalesInvoice,
    *,
    actor_user_id: Optional[UUID] = None,
) -> CommercialTransaction:
    existing = get_commercial_transaction_for_invoice(db, invoice.id)
    if existing:
        return existing
    actor = TransitionActor(user_id=actor_user_id or invoice.created_by, role="system")
    return create_commercial_transaction(
        db,
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        sales_invoice_id=invoice.id,
        actor=actor,
    )


def _advance_along_spine(
    db: Session,
    tx: CommercialTransaction,
    *,
    target_max: TransactionState,
    actor: TransitionActor,
    basis_prefix: str,
    extra_context: Optional[dict] = None,
) -> None:
    cur = current_state(tx)
    try:
        start_idx = SPINE_ORDER.index(cur)
        end_idx = SPINE_ORDER.index(target_max)
    except ValueError:
        logger.debug(
            "commercial_transaction_lifecycle: skip spine advance from non-spine state %s",
            cur.value,
        )
        return
    if end_idx <= start_idx:
        return
    for target in SPINE_ORDER[start_idx + 1 : end_idx + 1]:
        try:
            transition_transaction(
                db,
                tx,
                target,
                actor,
                TransitionContext(
                    basis=f"{basis_prefix}:{target.value}",
                    extra=extra_context,
                ),
            )
        except TransactionStateError as exc:
            logger.info(
                "commercial_transaction_lifecycle: stopped at %s -> %s (%s)",
                cur.value,
                target.value,
                exc,
            )
            return


def on_sales_invoice_created(
    db: Session,
    invoice: SalesInvoice,
    *,
    actor_user_id: Optional[UUID] = None,
) -> CommercialTransaction:
    """Create linked commercial transaction in DRAFT when a sales invoice is born."""
    return get_or_create_for_sales_invoice(db, invoice, actor_user_id=actor_user_id)


def on_sales_invoice_batched(
    db: Session,
    invoice: SalesInvoice,
    *,
    batched_by: UUID,
) -> None:
    """
    Record constitutional progress when pharmacy batch commits stock.

    RETAIL_COUNTER: retail fast path through BILLING_ACCEPTED (pharmacy owns commercial truth).
    ENCOUNTER_CONSOLIDATED: operational completion only; billing acceptance remains future work.
    """
    wf = get_invoice_workflow_type_for_branch(db, invoice.branch_id)
    tx = get_or_create_for_sales_invoice(db, invoice, actor_user_id=batched_by)
    actor = TransitionActor(user_id=batched_by, role="pharmacy")

    if wf == "RETAIL_COUNTER":
        _advance_along_spine(
            db,
            tx,
            target_max=TransactionState.BILLING_ACCEPTED,
            actor=actor,
            basis_prefix="retail_batch",
        )
        return

    if wf == "ENCOUNTER_CONSOLIDATED":
        _advance_along_spine(
            db,
            tx,
            target_max=TransactionState.OPERATIONALLY_COMPLETE,
            actor=TransitionActor(user_id=batched_by, role="pharmacy_inventory"),
            basis_prefix="encounter_batch_stock_commit",
        )
        # TODO(ENCOUNTER_CONSOLIDATED): COMMERCIALLY_COMPLETE / BILLING_ACCEPTED via billing office only.


def on_kra_submit_success(
    db: Session,
    invoice: SalesInvoice,
    *,
    actor_user_id: Optional[UUID] = None,
) -> None:
    """After regulator acknowledgment — advance to FISCAL_EXTERNALIZED."""
    tx = get_or_create_for_sales_invoice(
        db,
        invoice,
        actor_user_id=actor_user_id,
    )
    actor = TransitionActor(user_id=actor_user_id, role="fiscal_submitter")
    _advance_along_spine(
        db,
        tx,
        target_max=TransactionState.FISCAL_EXTERNALIZED,
        actor=actor,
        basis_prefix="kra_submit_success",
    )


def on_invoice_payment_recorded(
    db: Session,
    invoice: SalesInvoice,
    *,
    paid_by: UUID,
) -> None:
    """Parallel settlement spine — does not imply fiscal externalization."""
    tx = get_commercial_transaction_for_invoice(db, invoice.id)
    if not tx:
        return
    cur = current_state(tx)
    if cur in (TransactionState.SETTLEMENT_ACTIVE, TransactionState.SETTLEMENT_CLOSED):
        return
    if cur not in (
        TransactionState.BILLING_ACCEPTED,
        TransactionState.FISCAL_READY,
        TransactionState.FISCAL_EXTERNALIZED,
    ):
        return
    try:
        transition_transaction(
            db,
            tx,
            TransactionState.SETTLEMENT_ACTIVE,
            TransitionActor(user_id=paid_by, role="cashier"),
            TransitionContext(basis="invoice_payment_recorded"),
        )
    except TransactionStateError as exc:
        logger.info(
            "commercial_transaction_lifecycle: settlement_active skipped for invoice %s: %s",
            invoice.id,
            exc,
        )


def constitutional_state_for_invoice(
    db: Session,
    sales_invoice_id: UUID,
) -> Optional[str]:
    tx = get_commercial_transaction_for_invoice(db, sales_invoice_id)
    if not tx:
        return None
    return current_state(tx).value
