"""Balance sheet from authoritative GL."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.reports.profit_and_loss import build_profit_and_loss
from app.models.accounting import ChartOfAccount, GlJournalEntry, GlJournalLine

Q2 = Decimal("0.01")


def _category_balances(
    db: Session,
    *,
    company_id: UUID,
    as_of_date: date,
    branch_id: Optional[UUID],
) -> Dict[str, Decimal]:
    q = (
        db.query(
            ChartOfAccount.category,
            func.coalesce(func.sum(GlJournalLine.debit), 0),
            func.coalesce(func.sum(GlJournalLine.credit), 0),
        )
        .join(GlJournalLine, GlJournalLine.account_id == ChartOfAccount.id)
        .join(GlJournalEntry, GlJournalEntry.id == GlJournalLine.journal_entry_id)
        .filter(
            GlJournalEntry.company_id == company_id,
            GlJournalEntry.status == "POSTED",
            GlJournalEntry.posting_date <= as_of_date,
            ChartOfAccount.company_id == company_id,
            ChartOfAccount.category.in_(("ASSET", "LIABILITY", "EQUITY")),
        )
    )
    if branch_id is not None:
        q = q.filter(GlJournalLine.branch_id == branch_id)
    out: Dict[str, Decimal] = {"ASSET": Decimal("0"), "LIABILITY": Decimal("0"), "EQUITY": Decimal("0")}
    for cat, deb, cred in q.group_by(ChartOfAccount.category).all():
        d, c = Decimal(str(deb or 0)), Decimal(str(cred or 0))
        if cat == "ASSET":
            out["ASSET"] = (d - c).quantize(Q2, rounding=ROUND_HALF_UP)
        elif cat == "LIABILITY":
            out["LIABILITY"] = (c - d).quantize(Q2, rounding=ROUND_HALF_UP)
        elif cat == "EQUITY":
            out["EQUITY"] = (c - d).quantize(Q2, rounding=ROUND_HALF_UP)
    return out


def build_balance_sheet(
    db: Session,
    *,
    company_id: UUID,
    as_of_date: date,
    branch_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    cats = _category_balances(db, company_id=company_id, as_of_date=as_of_date, branch_id=branch_id)

    # Current-year net income through as_of (simplified retained earnings plug)
    year_start = date(as_of_date.year, 1, 1)
    pnl = build_profit_and_loss(
        db,
        company_id=company_id,
        from_date=year_start,
        to_date=as_of_date,
        branch_id=branch_id,
    )
    current_year_income = Decimal(str(pnl["net_income"]))
    retained_equity = (cats["EQUITY"] + current_year_income).quantize(Q2, rounding=ROUND_HALF_UP)

    assets = cats["ASSET"]
    liabilities = cats["LIABILITY"]
    liabilities_and_equity = (liabilities + retained_equity).quantize(Q2, rounding=ROUND_HALF_UP)
    delta = (assets - liabilities_and_equity).quantize(Q2, rounding=ROUND_HALF_UP)

    return {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "as_of_date": str(as_of_date),
        "doctrine": "gl_authoritative_m1",
        "assets": assets,
        "liabilities": liabilities,
        "equity_per_gl": cats["EQUITY"],
        "current_year_net_income": current_year_income,
        "retained_equity_computed": retained_equity,
        "liabilities_and_equity": liabilities_and_equity,
        "balance_delta": delta,
        "balanced": abs(delta) <= Decimal("0.05"),
        "sections": [
            {"label": "Assets", "amount": assets},
            {"label": "Liabilities", "amount": liabilities},
            {"label": "Equity (GL accounts)", "amount": cats["EQUITY"]},
            {"label": "Current year net income (P&L YTD)", "amount": current_year_income},
            {"label": "Total liabilities + equity", "amount": liabilities_and_equity},
        ],
    }
