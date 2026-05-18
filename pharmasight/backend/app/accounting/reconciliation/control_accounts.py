"""
Control account reconciliation — operational subledgers vs GL (authoritative).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.company_settings import opening_cash_for_branch
from app.accounting.constants import (
    CONTROL_AP,
    CONTROL_AR,
    CONTROL_CASH,
    CONTROL_INVENTORY,
)
from app.accounting.coa_service import control_account_map
from app.accounting.inventory_valuation import branch_inventory_valuation
from app.models.accounting import ChartOfAccount, GlJournalEntry, GlJournalLine
from app.models.cashbook import CashbookEntry
from app.models.customer_financial import CustomerLedgerEntry
from app.models.supplier_financial import SupplierLedgerEntry

RECON_TOLERANCE = Decimal("0.05")
Q2 = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return v.quantize(Q2, rounding=ROUND_HALF_UP)


def gl_control_balance(
    db: Session,
    *,
    company_id: UUID,
    account_id: UUID,
    branch_id: Optional[UUID],
    as_of_date: date,
) -> Decimal:
    q = (
        db.query(
            func.coalesce(func.sum(GlJournalLine.debit), 0),
            func.coalesce(func.sum(GlJournalLine.credit), 0),
        )
        .join(GlJournalEntry, GlJournalEntry.id == GlJournalLine.journal_entry_id)
        .filter(
            GlJournalEntry.company_id == company_id,
            GlJournalEntry.status == "POSTED",
            GlJournalEntry.posting_date <= as_of_date,
            GlJournalLine.account_id == account_id,
        )
    )
    if branch_id is not None:
        q = q.filter(GlJournalLine.branch_id == branch_id)
    row = q.first()
    if not row:
        return Decimal("0")
    deb, cred = Decimal(str(row[0] or 0)), Decimal(str(row[1] or 0))
    return _q(deb - cred)


def ar_subledger_balance(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    as_of_date: date,
) -> Decimal:
    q = db.query(
        func.coalesce(func.sum(CustomerLedgerEntry.debit), 0)
        - func.coalesce(func.sum(CustomerLedgerEntry.credit), 0)
    ).filter(
        CustomerLedgerEntry.company_id == company_id,
        CustomerLedgerEntry.date <= as_of_date,
    )
    if branch_id is not None:
        q = q.filter(CustomerLedgerEntry.branch_id == branch_id)
    return _q(Decimal(str(q.scalar() or 0)))


def ap_subledger_balance(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    as_of_date: date,
) -> Decimal:
    q = db.query(
        func.coalesce(func.sum(SupplierLedgerEntry.debit), 0)
        - func.coalesce(func.sum(SupplierLedgerEntry.credit), 0)
    ).filter(
        SupplierLedgerEntry.company_id == company_id,
        SupplierLedgerEntry.date <= as_of_date,
    )
    if branch_id is not None:
        q = q.filter(SupplierLedgerEntry.branch_id == branch_id)
    return _q(Decimal(str(q.scalar() or 0)))


def cashbook_derived_balance(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    as_of_date: date,
) -> Decimal:
    opening = opening_cash_for_branch(db, company_id, branch_id)
    inflow = (
        db.query(func.coalesce(func.sum(CashbookEntry.amount), 0))
        .filter(
            CashbookEntry.company_id == company_id,
            CashbookEntry.branch_id == branch_id,
            CashbookEntry.date <= as_of_date,
            CashbookEntry.type == "inflow",
        )
        .scalar()
    )
    outflow = (
        db.query(func.coalesce(func.sum(CashbookEntry.amount), 0))
        .filter(
            CashbookEntry.company_id == company_id,
            CashbookEntry.branch_id == branch_id,
            CashbookEntry.date <= as_of_date,
            CashbookEntry.type == "outflow",
        )
        .scalar()
    )
    return _q(opening + Decimal(str(inflow or 0)) - Decimal(str(outflow or 0)))


def _status_for_delta(delta: Decimal, warnings: List[str]) -> str:
    if abs(delta) <= RECON_TOLERANCE:
        return "PASS" if not warnings else "PASS_WITH_WARNINGS"
    return "FAIL"


def build_control_reconciliation(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    as_of_date: date,
) -> Dict[str, Any]:
    accounts = control_account_map(db, company_id)
    controls: List[Dict[str, Any]] = []
    hard_fail = False

    def add_control(
        role: str,
        label: str,
        subledger: Decimal,
        gl: Decimal,
        warnings: Optional[List[str]] = None,
    ) -> None:
        nonlocal hard_fail
        warnings = warnings or []
        delta = _q(subledger - gl)
        status = _status_for_delta(delta, warnings)
        if status == "FAIL":
            hard_fail = True
        controls.append(
            {
                "control_role": role,
                "label": label,
                "subledger_balance": subledger,
                "gl_balance": gl,
                "delta": delta,
                "status": status,
                "warnings": warnings,
            }
        )

    ar_acct = accounts.get(CONTROL_AR)
    if ar_acct:
        sub = ar_subledger_balance(db, company_id=company_id, branch_id=branch_id, as_of_date=as_of_date)
        gl = gl_control_balance(
            db, company_id=company_id, account_id=ar_acct.id, branch_id=branch_id, as_of_date=as_of_date
        )
        add_control(CONTROL_AR, "Accounts Receivable", sub, gl)

    ap_acct = accounts.get(CONTROL_AP)
    if ap_acct:
        sub = ap_subledger_balance(db, company_id=company_id, branch_id=branch_id, as_of_date=as_of_date)
        gl = gl_control_balance(
            db, company_id=company_id, account_id=ap_acct.id, branch_id=branch_id, as_of_date=as_of_date
        )
        add_control(CONTROL_AP, "Accounts Payable", sub, gl)

    inv_acct = accounts.get(CONTROL_INVENTORY)
    if inv_acct and branch_id is not None:
        sub = branch_inventory_valuation(db, company_id=company_id, branch_id=branch_id, as_of_date=as_of_date)
        gl = gl_control_balance(
            db, company_id=company_id, account_id=inv_acct.id, branch_id=branch_id, as_of_date=as_of_date
        )
        warnings = []
        if sub == 0 and gl != 0:
            warnings.append("Operational valuation is zero but GL inventory balance is non-zero")
        add_control(CONTROL_INVENTORY, "Inventory", sub, gl, warnings)

    cash_acct = accounts.get(CONTROL_CASH)
    if cash_acct and branch_id is not None:
        sub = cashbook_derived_balance(db, company_id=company_id, branch_id=branch_id, as_of_date=as_of_date)
        gl = gl_control_balance(
            db, company_id=company_id, account_id=cash_acct.id, branch_id=branch_id, as_of_date=as_of_date
        )
        warnings = []
        if opening_cash_for_branch(db, company_id, branch_id) == 0 and sub != gl:
            warnings.append(
                "Set company_settings accounting_opening_cash_by_branch for opening cash if legacy balance expected"
            )
        add_control(CONTROL_CASH, "Cash and Bank", sub, gl, warnings)

    overall = "PASS"
    if hard_fail:
        overall = "FAIL"
    elif any(c["status"] == "PASS_WITH_WARNINGS" for c in controls):
        overall = "PASS_WITH_WARNINGS"

    return {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "as_of_date": str(as_of_date),
        "doctrine": "gl_control_reconciliation_m1",
        "tolerance": str(RECON_TOLERANCE),
        "overall_status": overall,
        "controls": controls,
    }


def reconciliation_allows_period_close(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    as_of_date: date,
) -> tuple[bool, str]:
    """Returns (allowed, message). FAIL blocks close."""
    report = build_control_reconciliation(
        db, company_id=company_id, branch_id=branch_id, as_of_date=as_of_date
    )
    if report["overall_status"] == "FAIL":
        return False, "Control reconciliation FAIL — resolve before period close"
    return True, report["overall_status"]
