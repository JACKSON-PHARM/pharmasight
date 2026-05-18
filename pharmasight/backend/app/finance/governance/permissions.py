"""
Finance REBAC permission registry and legacy compatibility shim.

New finance endpoints MUST use explicit finance.* / wholesale.ar.* / hospital.* permissions.
reports.view is deprecated for finance; resolves_finance_permission() may honor it during migration.
"""
from __future__ import annotations

from typing import FrozenSet, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

# Canonical finance permission names (migration 133)
FINANCE_PERMISSION_NAMES: FrozenSet[str] = frozenset(
    {
        "finance.cashbook.view_branch",
        "finance.cashbook.view_company",
        "finance.cashbook.reconcile_branch",
        "finance.reports.operational",
        "finance.reports.management",
        "finance.reports.executive",
        "finance.reports.audit_read",
        "finance.vat.view_branch",
        "finance.vat.view_company",
        "finance.vat.export",
        "wholesale.ar.view",
        "wholesale.ar.collect",
        "wholesale.ar.credit_control",
        "hospital.billing.view",
        "hospital.billing.create",
        "hospital.billing.adjust",
        "hospital.insurance.view",
        "hospital.insurance.settle",
        "hospital.insurance.manage_providers",
        "retail.till.operate",
        "retail.till.reconcile",
        "finance.gl.view",
        "finance.gl.post",
        "finance.gl.period_close",
    }
)

# finance permission -> legacy permission names that satisfy it (compatibility window only)
LEGACY_FINANCE_PERMISSION_ALIASES: dict[str, Tuple[str, ...]] = {
    "finance.cashbook.view_branch": ("reports.view",),
    "finance.cashbook.view_company": ("reports.view",),  # E2+ will require explicit company scope
    "finance.cashbook.reconcile_branch": ("settings.edit",),
    "finance.reports.operational": ("reports.view",),
    "finance.reports.management": ("reports.view", "dashboard.view_gross_profit"),
    "finance.reports.executive": ("reports.view",),
    "finance.reports.audit_read": ("reports.view",),
    "finance.vat.view_branch": ("reports.view",),
    "finance.vat.view_company": ("reports.view",),
    "finance.vat.export": ("reports.view",),
    "wholesale.ar.view": ("reports.view", "customers.view"),
    "wholesale.ar.collect": ("customers.record_payment",),
    "wholesale.ar.credit_control": ("customers.manage_credit", "customers.view"),
    "hospital.billing.view": ("sales.view",),
    "hospital.billing.create": ("sales.create",),
    "hospital.billing.adjust": ("sales.edit",),
    "hospital.insurance.view": ("sales.view", "reports.view"),
    "hospital.insurance.settle": ("sales.edit",),
    "hospital.insurance.manage_providers": ("settings.edit",),
    "retail.till.operate": ("sales.create", "sales.view"),
    "retail.till.reconcile": ("settings.edit",),
    # GL permissions: no legacy alias — admin roles receive grants via migration 134
}


def _user_has_permission_scoped(
    db: Session,
    user_id: UUID,
    permission_name: str,
    branch_id: Optional[UUID] = None,
) -> bool:
    """True if user has permission globally or for the given branch (via role_permissions.branch_id)."""
    from app.models.user import UserBranchRole
    from app.models.permission import Permission, RolePermission

    perm = db.query(Permission).filter(Permission.name == permission_name).first()
    if not perm:
        return False

    role_ids = [
        r[0]
        for r in db.query(UserBranchRole.role_id)
        .filter(UserBranchRole.user_id == user_id)
        .distinct()
        .all()
    ]
    if not role_ids:
        return False

    q = db.query(RolePermission).filter(
        RolePermission.role_id.in_(role_ids),
        RolePermission.permission_id == perm.id,
    )
    if branch_id is not None:
        from sqlalchemy import or_

        q = q.filter(
            or_(
                RolePermission.branch_id.is_(None),
                RolePermission.branch_id == branch_id,
            )
        )
    else:
        q = q.filter(RolePermission.branch_id.is_(None))

    return q.first() is not None


def user_has_finance_permission(
    db: Session,
    user_id: UUID,
    permission_name: str,
    *,
    branch_id: Optional[UUID] = None,
) -> bool:
    """True if user holds the explicit finance permission (no legacy fallback)."""
    if permission_name not in FINANCE_PERMISSION_NAMES:
        return _user_has_permission_scoped(db, user_id, permission_name, branch_id)
    return _user_has_permission_scoped(db, user_id, permission_name, branch_id)


def resolves_finance_permission_with_source(
    db: Session,
    user_id: UUID,
    permission_name: str,
    *,
    branch_id: Optional[UUID] = None,
    allow_legacy: bool = True,
) -> tuple[bool, bool, Optional[str]]:
    """
    (granted, via_legacy_fallback, legacy_permission_name).

    Used by governance telemetry; prefer resolves_finance_permission() for boolean checks.
    """
    if user_has_finance_permission(db, user_id, permission_name, branch_id=branch_id):
        return True, False, None
    if not allow_legacy:
        return False, False, None
    for legacy_name in LEGACY_FINANCE_PERMISSION_ALIASES.get(permission_name, ()):
        if _user_has_permission_scoped(db, user_id, legacy_name, branch_id=branch_id):
            return True, True, legacy_name
    return False, False, None


def resolves_finance_permission(
    db: Session,
    user_id: UUID,
    permission_name: str,
    *,
    branch_id: Optional[UUID] = None,
    allow_legacy: bool = True,
) -> bool:
    """
    True if user may perform an action requiring permission_name.

    Checks explicit finance permission first, then legacy aliases when allow_legacy=True.
    """
    granted, _, _ = resolves_finance_permission_with_source(
        db,
        user_id,
        permission_name,
        branch_id=branch_id,
        allow_legacy=allow_legacy,
    )
    return granted


def resolves_any_finance_permission(
    db: Session,
    user_id: UUID,
    permission_names: Tuple[str, ...],
    *,
    branch_id: Optional[UUID] = None,
    allow_legacy: bool = True,
) -> bool:
    return any(
        resolves_finance_permission(
            db, user_id, name, branch_id=branch_id, allow_legacy=allow_legacy
        )
        for name in permission_names
    )
