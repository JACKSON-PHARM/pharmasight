"""Chart of accounts provisioning and resolution."""
from __future__ import annotations

from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.constants import DEFAULT_COA_TEMPLATE
from app.models.accounting import ChartOfAccount


def company_has_coa(db: Session, company_id: UUID) -> bool:
    return (
        db.query(ChartOfAccount.id)
        .filter(ChartOfAccount.company_id == company_id, ChartOfAccount.is_active.is_(True))
        .first()
        is not None
    )


def provision_default_chart_of_accounts(db: Session, company_id: UUID) -> int:
    """Idempotent: seed standard control accounts for a company."""
    if company_has_coa(db, company_id):
        return 0
    created = 0
    for code, name, category, control_role, normal_balance in DEFAULT_COA_TEMPLATE:
        db.add(
            ChartOfAccount(
                company_id=company_id,
                code=code,
                name=name,
                category=category,
                control_role=control_role,
                is_control_account=True,
                normal_balance=normal_balance,
                is_active=True,
            )
        )
        created += 1
    db.flush()
    if created > 0:
        from app.accounting.company_settings import ensure_default_cash_gl_mapping

        ensure_default_cash_gl_mapping(db, company_id)
    return created


def resolve_control_account(db: Session, company_id: UUID, control_role: str) -> ChartOfAccount:
    row = (
        db.query(ChartOfAccount)
        .filter(
            ChartOfAccount.company_id == company_id,
            ChartOfAccount.control_role == control_role,
            ChartOfAccount.is_active.is_(True),
        )
        .first()
    )
    if not row:
        provision_default_chart_of_accounts(db, company_id)
        row = (
            db.query(ChartOfAccount)
            .filter(
                ChartOfAccount.company_id == company_id,
                ChartOfAccount.control_role == control_role,
                ChartOfAccount.is_active.is_(True),
            )
            .first()
        )
    if not row:
        raise ValueError(f"Missing control account {control_role} for company {company_id}")
    return row


def control_account_map(db: Session, company_id: UUID) -> Dict[str, ChartOfAccount]:
    provision_default_chart_of_accounts(db, company_id)
    rows = (
        db.query(ChartOfAccount)
        .filter(
            ChartOfAccount.company_id == company_id,
            ChartOfAccount.control_role.isnot(None),
            ChartOfAccount.is_active.is_(True),
        )
        .all()
    )
    return {r.control_role: r for r in rows if r.control_role}
