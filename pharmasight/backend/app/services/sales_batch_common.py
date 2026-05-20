"""Shared helpers for POS sales batch (operational + reconciliation)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.settings import CompanySetting
from app.services.pricing_service import PricingService

SNAPSHOT_VS_LEDGER_WARN_THRESHOLD = Decimal("0.01")


def total_cost_from_allocations(allocations: list) -> Decimal:
    total = Decimal("0")
    for a in allocations or []:
        qty = Decimal(str(a.get("quantity", 0)))
        uc = Decimal(str(a.get("unit_cost", 0)))
        total += qty * uc
    return total


def _get_company_setting_decimal(db: Session, company_id: UUID, key: str) -> Decimal | None:
    row = (
        db.query(CompanySetting)
        .filter(CompanySetting.company_id == company_id, CompanySetting.key == key)
        .first()
    )
    if not row or row.value is None:
        return None
    try:
        return Decimal(str(row.value))
    except Exception:
        return None


def user_has_sell_below_min_margin(db: Session, user_id: UUID, branch_id: UUID) -> bool:
    from app.models import Permission, RolePermission, UserBranchRole, UserRole

    perm = db.query(Permission).filter(Permission.name == "sales.sell_below_min_margin").first()
    if not perm:
        return False
    ubr = (
        db.query(UserBranchRole)
        .join(UserRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user_id, UserBranchRole.branch_id == branch_id)
        .first()
    )
    if not ubr:
        return False
    rp = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == ubr.role_id, RolePermission.permission_id == perm.id)
        .first()
    )
    return rp is not None


def sustainable_min_margin_pct(db: Session, company_id: UUID) -> Decimal | None:
    v = _get_company_setting_decimal(db, company_id, "sustainable_min_margin_pct")
    if v is None:
        return None
    if v < 0:
        return Decimal("0")
    if v > 100:
        return Decimal("100")
    return v
