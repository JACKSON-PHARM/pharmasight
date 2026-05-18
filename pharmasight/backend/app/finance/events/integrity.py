"""
Lineage integrity verification (E4) — read-only gap detection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.events.registry import build_idempotency_key, get_event_spec
from app.models.financial_event import FinancialEvent
from app.models.sale import SalesInvoice
from app.models.customer_financial import CustomerPayment
from app.models.purchase import SupplierInvoice
from app.models.supplier_financial import SupplierPayment
from app.models.expense import Expense


@dataclass(frozen=True)
class IntegrityFinding:
    code: str
    severity: str
    source_entity_type: str
    source_entity_id: UUID
    branch_id: Optional[UUID]
    expected_event_type: str
    expected_idempotency_key: str
    message: str


def _event_exists(db: Session, company_id: UUID, idempotency_key: str) -> bool:
    return (
        db.query(FinancialEvent.id)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.idempotency_key == idempotency_key,
        )
        .first()
        is not None
    )


def verify_company_lineage(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID] = None,
    since: Optional[date] = None,
    limit: int = 500,
) -> List[IntegrityFinding]:
    findings: List[IntegrityFinding] = []

    inv_q = db.query(SalesInvoice).filter(
        SalesInvoice.company_id == company_id,
        SalesInvoice.status.in_(["BATCHED", "PAID"]),
        SalesInvoice.customer_id.isnot(None),
    )
    if branch_id:
        inv_q = inv_q.filter(SalesInvoice.branch_id == branch_id)
    if since:
        inv_q = inv_q.filter(SalesInvoice.invoice_date >= since)
    for inv in inv_q.limit(limit).all():
        bal = Decimal(str(inv.balance if inv.balance is not None else inv.total_inclusive or 0))
        if bal <= 0:
            continue
        spec = get_event_spec("receivable_accrued")
        key = build_idempotency_key(spec, source_entity_id=str(inv.id))
        if not _event_exists(db, company_id, key):
            findings.append(
                IntegrityFinding(
                    code="missing_receivable_accrued",
                    severity="warning",
                    source_entity_type="sales_invoice",
                    source_entity_id=inv.id,
                    branch_id=inv.branch_id,
                    expected_event_type="receivable_accrued",
                    expected_idempotency_key=key,
                    message="Batched customer invoice with balance has no receivable_accrued event",
                )
            )

    pay_q = db.query(CustomerPayment).filter(CustomerPayment.company_id == company_id)
    if branch_id:
        pay_q = pay_q.filter(CustomerPayment.branch_id == branch_id)
    if since:
        pay_q = pay_q.filter(CustomerPayment.payment_date >= since)
    for pay in pay_q.limit(limit).all():
        if Decimal(str(pay.amount or 0)) <= 0:
            continue
        spec = get_event_spec("cash_received")
        key = build_idempotency_key(spec, source_entity_id=str(pay.id))
        if not _event_exists(db, company_id, key):
            findings.append(
                IntegrityFinding(
                    code="missing_cash_received",
                    severity="warning",
                    source_entity_type="customer_payment",
                    source_entity_id=pay.id,
                    branch_id=pay.branch_id,
                    expected_event_type="cash_received",
                    expected_idempotency_key=key,
                    message="Customer payment has no cash_received event",
                )
            )

    si_q = db.query(SupplierInvoice).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.status == "BATCHED",
    )
    if branch_id:
        si_q = si_q.filter(SupplierInvoice.branch_id == branch_id)
    if since:
        si_q = si_q.filter(SupplierInvoice.invoice_date >= since)
    for si in si_q.limit(limit).all():
        if Decimal(str(si.total_inclusive or 0)) <= 0:
            continue
        spec = get_event_spec("payable_recognized")
        key = build_idempotency_key(spec, source_entity_id=str(si.id))
        if not _event_exists(db, company_id, key):
            findings.append(
                IntegrityFinding(
                    code="missing_payable_recognized",
                    severity="warning",
                    source_entity_type="supplier_invoice",
                    source_entity_id=si.id,
                    branch_id=si.branch_id,
                    expected_event_type="payable_recognized",
                    expected_idempotency_key=key,
                    message="Batched supplier invoice has no payable_recognized event",
                )
            )

    sp_q = db.query(SupplierPayment).filter(SupplierPayment.company_id == company_id)
    if branch_id:
        sp_q = sp_q.filter(SupplierPayment.branch_id == branch_id)
    if since:
        sp_q = sp_q.filter(SupplierPayment.payment_date >= since)
    for sp in sp_q.limit(limit).all():
        if Decimal(str(sp.amount or 0)) <= 0:
            continue
        spec = get_event_spec("cash_paid")
        key = build_idempotency_key(spec, source_entity_id=str(sp.id))
        if not _event_exists(db, company_id, key):
            findings.append(
                IntegrityFinding(
                    code="missing_cash_paid",
                    severity="warning",
                    source_entity_type="supplier_payment",
                    source_entity_id=sp.id,
                    branch_id=sp.branch_id,
                    expected_event_type="cash_paid",
                    expected_idempotency_key=key,
                    message="Supplier payment has no cash_paid event",
                )
            )

    ex_q = db.query(Expense).filter(
        Expense.company_id == company_id,
        Expense.status == "approved",
    )
    if branch_id:
        ex_q = ex_q.filter(Expense.branch_id == branch_id)
    if since:
        ex_q = ex_q.filter(Expense.expense_date >= since)
    for ex in ex_q.limit(limit).all():
        spec = get_event_spec("expense_recognized")
        key = build_idempotency_key(spec, source_entity_id=str(ex.id))
        if not _event_exists(db, company_id, key):
            findings.append(
                IntegrityFinding(
                    code="missing_expense_recognized",
                    severity="warning",
                    source_entity_type="expense",
                    source_entity_id=ex.id,
                    branch_id=ex.branch_id,
                    expected_event_type="expense_recognized",
                    expected_idempotency_key=key,
                    message="Approved expense has no expense_recognized event",
                )
            )

    invalid_reversals = (
        db.query(FinancialEvent)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.reversal_of_event_id.isnot(None),
        )
        .limit(limit)
        .all()
    )
    for ev in invalid_reversals:
        parent = (
            db.query(FinancialEvent)
            .filter(FinancialEvent.id == ev.reversal_of_event_id, FinancialEvent.company_id == company_id)
            .first()
        )
        if not parent:
            findings.append(
                IntegrityFinding(
                    code="orphan_reversal",
                    severity="error",
                    source_entity_type=ev.source_entity_type,
                    source_entity_id=ev.source_entity_id,
                    branch_id=ev.branch_id,
                    expected_event_type=ev.event_type,
                    expected_idempotency_key=ev.idempotency_key,
                    message="Reversal references missing parent event",
                )
            )

    return findings
