"""
Controlled financial event backfill (E5).

Lineage reconstruction — preserves occurred_at, policy pack, classification, and idempotency.
Never mutates existing events. Never stores authoritative balances.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.finance.events.branch_policy import resolve_policy_pack_for_branch
from app.finance.events.correlation import correlation_group_for_backfill_run
from app.finance.events.hooks import (
    on_customer_payment_financial_event,
    on_expense_approved_financial_event,
    on_insurance_claim_financial_event,
    on_insurance_settlement_financial_event,
    on_sales_invoice_batched_financial_event,
    on_supplier_invoice_batched_financial_event,
    on_supplier_payment_financial_event,
)
from app.finance.doctrine.backfill import BACKFILL_INVARIANTS
from app.models.customer_financial import CustomerPayment
from app.models.expense import Expense
from app.models.finance_backfill import FinanceBackfillRun
from app.models.insurance_financial import InsuranceClaim, InsuranceSettlement
from app.models.purchase import SupplierInvoice
from app.models.sale import SalesInvoice
from app.models.supplier_financial import SupplierPayment

logger = logging.getLogger("pharmasight.finance.backfill")


@dataclass(frozen=True)
class BackfillOutcome:
    run_id: UUID
    status: str
    events_created: int
    events_duplicate: int
    events_failed: int


def _in_date_range(d: date, start: date, end: date) -> bool:
    return start <= d <= end


def run_controlled_backfill(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    actor_user_id: Optional[UUID] = None,
    event_types_filter: Optional[Sequence[str]] = None,
) -> BackfillOutcome:
    if date_from > date_to:
        raise ValueError("date_from must be <= date_to")

    pack = resolve_policy_pack_for_branch(db, company_id=company_id, branch_id=branch_id)
    run_id = uuid4()
    correlation = correlation_group_for_backfill_run(run_id)

    run = FinanceBackfillRun(
        id=run_id,
        company_id=company_id,
        branch_id=branch_id,
        correlation_group=correlation,
        policy_pack_id=pack.pack_id,
        date_from=date_from,
        date_to=date_to,
        event_types_filter=list(event_types_filter) if event_types_filter else None,
        status="running",
        actor_user_id=actor_user_id,
        detail_json={
            "doctrine": sorted(BACKFILL_INVARIANTS),
            "no_smart_recomputation": True,
            "preserve_occurred_at": True,
        },
    )
    db.add(run)
    db.flush()

    created = duplicate = failed = 0

    def _count(result: EmitResult) -> None:
        nonlocal created, duplicate, failed
        if result == EmitResult.CREATED:
            created += 1
        elif result == EmitResult.DUPLICATE:
            duplicate += 1
        else:
            failed += 1

    try:
        _backfill_sales_invoices(db, company_id, branch_id, date_from, date_to, pack.pack_id, _count)
        _backfill_customer_payments(db, company_id, branch_id, date_from, date_to, _count)
        _backfill_supplier_invoices(db, company_id, branch_id, date_from, date_to, _count)
        _backfill_supplier_payments(db, company_id, branch_id, date_from, date_to, _count)
        _backfill_expenses(db, company_id, branch_id, date_from, date_to, _count)
        _backfill_insurance_claims(db, company_id, branch_id, date_from, date_to, _count)
        _backfill_insurance_settlements(db, company_id, branch_id, date_from, date_to, _count)

        run.status = "completed"
        run.events_created = created
        run.events_duplicate = duplicate
        run.events_failed = failed
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("backfill run failed run_id=%s", run_id)
        run.status = "failed"
        run.detail_json = {"error": str(exc)[:2000]}
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise

    return BackfillOutcome(
        run_id=run_id,
        status=run.status,
        events_created=created,
        events_duplicate=duplicate,
        events_failed=failed,
    )


def _backfill_sales_invoices(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    pack_id: str,
    count_fn,
) -> None:
    rows = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.invoice_date >= date_from,
            SalesInvoice.invoice_date <= date_to,
        )
        .all()
    )
    for inv in rows:
        on_sales_invoice_batched_financial_event(db, inv)


def _backfill_customer_payments(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    count_fn,
) -> None:
    rows = (
        db.query(CustomerPayment)
        .filter(
            CustomerPayment.company_id == company_id,
            CustomerPayment.branch_id == branch_id,
            CustomerPayment.payment_date >= date_from,
            CustomerPayment.payment_date <= date_to,
        )
        .all()
    )
    for p in rows:
        on_customer_payment_financial_event(db, p)


def _backfill_supplier_invoices(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    count_fn,
) -> None:
    rows = (
        db.query(SupplierInvoice)
        .filter(
            SupplierInvoice.company_id == company_id,
            SupplierInvoice.branch_id == branch_id,
            SupplierInvoice.invoice_date >= date_from,
            SupplierInvoice.invoice_date <= date_to,
        )
        .all()
    )
    for inv in rows:
        on_supplier_invoice_batched_financial_event(db, inv)


def _backfill_supplier_payments(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    count_fn,
) -> None:
    rows = (
        db.query(SupplierPayment)
        .filter(
            SupplierPayment.company_id == company_id,
            SupplierPayment.branch_id == branch_id,
            SupplierPayment.payment_date >= date_from,
            SupplierPayment.payment_date <= date_to,
        )
        .all()
    )
    for p in rows:
        on_supplier_payment_financial_event(db, p)


def _backfill_expenses(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    count_fn,
) -> None:
    rows = (
        db.query(Expense)
        .filter(
            Expense.company_id == company_id,
            Expense.branch_id == branch_id,
            Expense.expense_date >= date_from,
            Expense.expense_date <= date_to,
            Expense.status == "approved",
        )
        .all()
    )
    for e in rows:
        on_expense_approved_financial_event(db, e)


def _backfill_insurance_claims(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    count_fn,
) -> None:
    rows = (
        db.query(InsuranceClaim)
        .filter(
            InsuranceClaim.company_id == company_id,
            InsuranceClaim.branch_id == branch_id,
        )
        .all()
    )
    for claim in rows:
        if claim.submitted_at:
            d = claim.submitted_at.date() if hasattr(claim.submitted_at, "date") else date_from
            if _in_date_range(d, date_from, date_to):
                on_insurance_claim_financial_event(db, claim, lifecycle_status=claim.status)


def _backfill_insurance_settlements(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    date_from: date,
    date_to: date,
    count_fn,
) -> None:
    rows = (
        db.query(InsuranceSettlement)
        .filter(
            InsuranceSettlement.company_id == company_id,
            InsuranceSettlement.branch_id == branch_id,
            InsuranceSettlement.settlement_date >= date_from,
            InsuranceSettlement.settlement_date <= date_to,
        )
        .all()
    )
    for s in rows:
        on_insurance_settlement_financial_event(db, s)
