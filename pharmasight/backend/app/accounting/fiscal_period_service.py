"""Fiscal period resolution and provisioning."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.accounting import FiscalPeriod


def _month_bounds(d: date) -> tuple[date, date]:
    last = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 1), date(d.year, d.month, last)


def _period_name(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def ensure_open_period_for_date(db: Session, company_id: UUID, posting_date: date) -> FiscalPeriod:
    """Return OPEN fiscal period containing posting_date; create month if missing."""
    start, end = _month_bounds(posting_date)
    name = _period_name(posting_date)
    period = (
        db.query(FiscalPeriod)
        .filter(FiscalPeriod.company_id == company_id, FiscalPeriod.name == name)
        .first()
    )
    if not period:
        period = FiscalPeriod(
            company_id=company_id,
            name=name,
            start_date=start,
            end_date=end,
            status="OPEN",
        )
        db.add(period)
        db.flush()
    if period.status == "CLOSED":
        raise ValueError(f"Fiscal period {period.name} is closed")
    if posting_date < period.start_date or posting_date > period.end_date:
        raise ValueError(f"Posting date {posting_date} outside period {period.name}")
    return period


def provision_current_open_period(db: Session, company_id: UUID, *, as_of: Optional[date] = None) -> FiscalPeriod:
    return ensure_open_period_for_date(db, company_id, as_of or date.today())


def ensure_company_accounting_ready(db: Session, company_id: UUID, posting_date: date) -> FiscalPeriod:
    from app.accounting.coa_service import provision_default_chart_of_accounts

    provision_default_chart_of_accounts(db, company_id)
    return ensure_open_period_for_date(db, company_id, posting_date)


def close_fiscal_period(
    db: Session,
    *,
    company_id: UUID,
    period_id: UUID,
    closed_by: UUID,
    close_notes: str | None = None,
    branch_id_for_recon: UUID | None = None,
) -> FiscalPeriod:
    """
    Close a fiscal period after control reconciliation passes (branch-scoped if provided).
    """
    from datetime import datetime, timezone

    from app.accounting.reconciliation.control_accounts import reconciliation_allows_period_close

    period = (
        db.query(FiscalPeriod)
        .filter(FiscalPeriod.id == period_id, FiscalPeriod.company_id == company_id)
        .first()
    )
    if not period:
        raise ValueError("Fiscal period not found")
    if period.status == "CLOSED":
        return period

    allowed, msg = reconciliation_allows_period_close(
        db,
        company_id=company_id,
        branch_id=branch_id_for_recon,
        as_of_date=period.end_date,
    )
    if not allowed:
        raise ValueError(msg)

    period.status = "CLOSED"
    period.closed_at = datetime.now(timezone.utc)
    period.closed_by = closed_by
    period.close_notes = close_notes
    db.flush()
    return period
