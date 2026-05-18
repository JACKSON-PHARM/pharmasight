"""P&L from authoritative GL."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.accounting import ChartOfAccount, GlJournalEntry, GlJournalLine

Q2 = Decimal("0.01")


def build_profit_and_loss(
    db: Session,
    *,
    company_id: UUID,
    from_date: date,
    to_date: date,
    branch_id: Optional[UUID] = None,
) -> Dict[str, Any]:
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
            GlJournalEntry.posting_date >= from_date,
            GlJournalEntry.posting_date <= to_date,
            ChartOfAccount.company_id == company_id,
        )
    )
    if branch_id is not None:
        q = q.filter(GlJournalLine.branch_id == branch_id)
    rows = q.group_by(ChartOfAccount.category).all()

    revenue = Decimal("0")
    cogs = Decimal("0")
    expense = Decimal("0")
    for cat, deb, cred in rows:
        d, c = Decimal(str(deb or 0)), Decimal(str(cred or 0))
        if cat == "REVENUE":
            revenue += c - d
        elif cat == "COGS":
            cogs += d - c
        elif cat == "EXPENSE":
            expense += d - c

    revenue = revenue.quantize(Q2, rounding=ROUND_HALF_UP)
    cogs = cogs.quantize(Q2, rounding=ROUND_HALF_UP)
    expense = expense.quantize(Q2, rounding=ROUND_HALF_UP)
    gross_profit = (revenue - cogs).quantize(Q2, rounding=ROUND_HALF_UP)
    net_income = (gross_profit - expense).quantize(Q2, rounding=ROUND_HALF_UP)

    return {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "from_date": str(from_date),
        "to_date": str(to_date),
        "doctrine": "gl_authoritative_m1",
        "revenue": revenue,
        "cost_of_sales": cogs,
        "gross_profit": gross_profit,
        "operating_expenses": expense,
        "net_income": net_income,
    }
