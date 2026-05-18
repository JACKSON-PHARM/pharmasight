"""
Idempotent GL backfill from operational documents (never from projections/financial_events).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.accounting.coa_service import company_has_coa, provision_default_chart_of_accounts
from app.accounting.company_settings import ensure_default_cash_gl_mapping
from app.accounting.fiscal_period_service import provision_current_open_period
from app.accounting.posting.credit_note import post_gl_for_credit_note
from app.accounting.posting.customer_payment import post_gl_for_customer_payment
from app.accounting.posting.expense import post_gl_for_expense_approved
from app.accounting.posting.sales import post_gl_for_sales_invoice_batch
from app.accounting.posting.stock_adjustment import post_gl_for_stock_adjustment
from app.accounting.posting.supplier import (
    post_gl_for_supplier_invoice_batch,
    post_gl_for_supplier_payment,
)
from app.accounting.posting.types import PostingResult
from app.models.customer_financial import CustomerPayment
from app.models.expense import Expense
from app.models.inventory import InventoryLedger
from app.models.purchase import SupplierInvoice
from app.models.sale import CreditNote, SalesInvoice
from app.models.supplier_financial import SupplierPayment

_SALES_STATUSES = ("BATCHED", "PAID")


@dataclass
class BackfillCounters:
    attempted: int = 0
    posted: int = 0
    skipped_duplicate: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)

    def record(self, results: List[PostingResult] | PostingResult) -> None:
        if isinstance(results, PostingResult):
            results = [results]
        for r in results:
            self.attempted += 1
            if r.skipped_duplicate:
                self.skipped_duplicate += 1
            elif r.created:
                self.posted += 1
            else:
                self.failed += 1
                if r.message and len(self.errors) < 50:
                    self.errors.append(r.message[:500])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempted": self.attempted,
            "posted": self.posted,
            "skipped_duplicate": self.skipped_duplicate,
            "failed": self.failed,
            "errors_sample": self.errors[:10],
        }


def _date_filter(q, col, from_date: Optional[date], to_date: Optional[date]):
    if from_date is not None:
        q = q.filter(col >= from_date)
    if to_date is not None:
        q = q.filter(col <= to_date)
    return q


def ensure_accounting_ready_for_backfill(db: Session, company_id: UUID, as_of: date) -> None:
    if not company_has_coa(db, company_id):
        provision_default_chart_of_accounts(db, company_id)
    ensure_default_cash_gl_mapping(db, company_id)
    provision_current_open_period(db, company_id, as_of=as_of)


def backfill_company_gl(
    db: Session,
    company_id: UUID,
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    branch_id: Optional[UUID] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    as_of = to_date or date.today()
    if not dry_run:
        ensure_accounting_ready_for_backfill(db, company_id, as_of)

    summary: Dict[str, Any] = {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "from_date": str(from_date) if from_date else None,
        "to_date": str(to_date) if to_date else None,
        "dry_run": dry_run,
        "doctrine": "operational_gl_backfill_m1",
    }
    totals = BackfillCounters()

    def run_entity(label: str, fn) -> None:
        c = BackfillCounters()
        if not dry_run:
            fn(c)
        summary[label] = c.to_dict() if not dry_run else {"attempted": "dry_run"}
        totals.attempted += c.attempted
        totals.posted += c.posted
        totals.skipped_duplicate += c.skipped_duplicate
        totals.failed += c.failed
        totals.errors.extend(c.errors)

    def backfill_sales(c: BackfillCounters) -> None:
        q = db.query(SalesInvoice).filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.status.in_(_SALES_STATUSES),
        )
        q = _date_filter(q, SalesInvoice.invoice_date, from_date, to_date)
        if branch_id:
            q = q.filter(SalesInvoice.branch_id == branch_id)
        for inv in q.order_by(SalesInvoice.invoice_date.asc()).all():
            ledger = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.reference_type == "sales_invoice",
                    InventoryLedger.reference_id == inv.id,
                )
                .all()
            )
            c.record(
                post_gl_for_sales_invoice_batch(db, inv, ledger, posted_by=inv.batched_by or inv.created_by)
            )

    def backfill_supplier_invoices(c: BackfillCounters) -> None:
        q = db.query(SupplierInvoice).filter(
            SupplierInvoice.company_id == company_id,
            SupplierInvoice.status == "BATCHED",
        )
        q = _date_filter(q, SupplierInvoice.invoice_date, from_date, to_date)
        if branch_id:
            q = q.filter(SupplierInvoice.branch_id == branch_id)
        for inv in q.order_by(SupplierInvoice.invoice_date.asc()).all():
            c.record(post_gl_for_supplier_invoice_batch(db, inv, posted_by=inv.created_by))

    def backfill_credit_notes(c: BackfillCounters) -> None:
        q = (
            db.query(CreditNote)
            .options(selectinload(CreditNote.original_invoice))
            .filter(
                CreditNote.company_id == company_id,
                CreditNote.posting_status == "posted",
            )
        )
        q = _date_filter(q, CreditNote.credit_note_date, from_date, to_date)
        if branch_id:
            q = q.filter(CreditNote.branch_id == branch_id)
        for cn in q.order_by(CreditNote.credit_note_date.asc()).all():
            invoice = cn.original_invoice
            if not invoice:
                continue
            ledger = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.reference_type == "credit_note",
                    InventoryLedger.reference_id == cn.id,
                )
                .all()
            )
            c.record(
                post_gl_for_credit_note(
                    db, cn, invoice, ledger, posted_by=cn.created_by
                )
            )

    def backfill_customer_payments(c: BackfillCounters) -> None:
        q = db.query(CustomerPayment).filter(CustomerPayment.company_id == company_id)
        q = _date_filter(q, CustomerPayment.payment_date, from_date, to_date)
        if branch_id:
            q = q.filter(CustomerPayment.branch_id == branch_id)
        for p in q.order_by(CustomerPayment.payment_date.asc()).all():
            c.record(post_gl_for_customer_payment(db, p, posted_by=p.created_by))

    def backfill_supplier_payments(c: BackfillCounters) -> None:
        q = db.query(SupplierPayment).filter(SupplierPayment.company_id == company_id)
        q = _date_filter(q, SupplierPayment.payment_date, from_date, to_date)
        if branch_id:
            q = q.filter(SupplierPayment.branch_id == branch_id)
        for p in q.order_by(SupplierPayment.payment_date.asc()).all():
            c.record(post_gl_for_supplier_payment(db, p, posted_by=p.created_by))

    def backfill_expenses(c: BackfillCounters) -> None:
        q = db.query(Expense).filter(
            Expense.company_id == company_id,
            Expense.status == "approved",
        )
        q = _date_filter(q, Expense.expense_date, from_date, to_date)
        if branch_id:
            q = q.filter(Expense.branch_id == branch_id)
        for exp in q.order_by(Expense.expense_date.asc()).all():
            c.record(post_gl_for_expense_approved(db, exp, posted_by=exp.approved_by))

    def backfill_stock_adjustments(c: BackfillCounters) -> None:
        q = db.query(InventoryLedger).filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.reference_type == "MANUAL_ADJUSTMENT",
        )
        if branch_id:
            q = q.filter(InventoryLedger.branch_id == branch_id)
        if from_date or to_date:
            # use created_at date portion
            rows = q.all()
            for row in rows:
                d = row.created_at.date() if row.created_at else date.today()
                if from_date and d < from_date:
                    continue
                if to_date and d > to_date:
                    continue
                c.record(post_gl_for_stock_adjustment(db, row, posted_by=row.created_by))
        else:
            for row in q.order_by(InventoryLedger.created_at.asc()).all():
                c.record(post_gl_for_stock_adjustment(db, row, posted_by=row.created_by))

    if dry_run:
        counts = {}
        for label, model, col, extra in [
            ("sales_invoices", SalesInvoice, SalesInvoice.invoice_date, SalesInvoice.status.in_(_SALES_STATUSES)),
            ("supplier_invoices", SupplierInvoice, SupplierInvoice.invoice_date, SupplierInvoice.status == "BATCHED"),
            ("credit_notes", CreditNote, CreditNote.credit_note_date, CreditNote.posting_status == "posted"),
            ("customer_payments", CustomerPayment, CustomerPayment.payment_date, True),
            ("supplier_payments", SupplierPayment, SupplierPayment.payment_date, True),
            ("expenses", Expense, Expense.expense_date, Expense.status == "approved"),
        ]:
            q = db.query(model).filter(model.company_id == company_id)
            if extra is not True:
                q = q.filter(extra)
            q = _date_filter(q, col, from_date, to_date)
            if branch_id and hasattr(model, "branch_id"):
                q = q.filter(model.branch_id == branch_id)
            counts[label] = q.count()
        adj_q = db.query(InventoryLedger).filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.reference_type == "MANUAL_ADJUSTMENT",
        )
        if branch_id:
            adj_q = adj_q.filter(InventoryLedger.branch_id == branch_id)
        counts["stock_adjustments"] = adj_q.count()
        summary["dry_run_counts"] = counts
        summary["totals"] = totals.to_dict()
        return summary

    run_entity("sales_invoices", backfill_sales)
    run_entity("supplier_invoices", backfill_supplier_invoices)
    run_entity("credit_notes", backfill_credit_notes)
    run_entity("customer_payments", backfill_customer_payments)
    run_entity("supplier_payments", backfill_supplier_payments)
    run_entity("expenses", backfill_expenses)
    run_entity("stock_adjustments", backfill_stock_adjustments)

    summary["totals"] = totals.to_dict()
    return summary
