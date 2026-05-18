"""Trial balance from authoritative GL only."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.accounting import ChartOfAccount, GlJournalEntry, GlJournalLine

Q2 = Decimal("0.01")


def build_trial_balance(
    db: Session,
    *,
    company_id: UUID,
    as_of_date: date,
    branch_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    q = (
        db.query(
            ChartOfAccount.id,
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.category,
            ChartOfAccount.normal_balance,
            func.coalesce(func.sum(GlJournalLine.debit), 0).label("period_debit"),
            func.coalesce(func.sum(GlJournalLine.credit), 0).label("period_credit"),
        )
        .join(GlJournalLine, GlJournalLine.account_id == ChartOfAccount.id)
        .join(GlJournalEntry, GlJournalEntry.id == GlJournalLine.journal_entry_id)
        .filter(
            GlJournalEntry.company_id == company_id,
            GlJournalEntry.status == "POSTED",
            GlJournalEntry.posting_date <= as_of_date,
            ChartOfAccount.company_id == company_id,
            ChartOfAccount.is_active.is_(True),
        )
    )
    if branch_id is not None:
        q = q.filter(GlJournalLine.branch_id == branch_id)
    rows = (
        q.group_by(
            ChartOfAccount.id,
            ChartOfAccount.code,
            ChartOfAccount.name,
            ChartOfAccount.category,
            ChartOfAccount.normal_balance,
        )
        .order_by(ChartOfAccount.code.asc())
        .all()
    )

    lines: List[Dict[str, Any]] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for r in rows:
        pd = Decimal(str(r.period_debit or 0)).quantize(Q2, rounding=ROUND_HALF_UP)
        pc = Decimal(str(r.period_credit or 0)).quantize(Q2, rounding=ROUND_HALF_UP)
        net = pd - pc
        total_debit += pd
        total_credit += pc
        lines.append(
            {
                "account_id": str(r.id),
                "code": r.code,
                "name": r.name,
                "category": r.category,
                "normal_balance": r.normal_balance,
                "debit": pd,
                "credit": pc,
                "net_balance": net,
            }
        )

    delta = total_debit - total_credit
    return {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "as_of_date": str(as_of_date),
        "doctrine": "gl_authoritative_m1",
        "lines": lines,
        "totals": {
            "debit": total_debit,
            "credit": total_credit,
            "delta": delta,
        },
        "balanced": abs(delta) <= Decimal("0.01"),
    }
