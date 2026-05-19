"""
Provision access and search snapshots when a new branch is created.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Set
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.company import Branch
from app.models.user import UserBranchRole, UserRole
from app.services.snapshot_refresh_service import SnapshotRefreshService

logger = logging.getLogger(__name__)

_PRIVILEGED_ROLE_NAMES = frozenset({"owner", "admin", "super admin", "administrator", "manager"})


def _ensure_user_branch_role(
    db: Session,
    *,
    user_id: UUID,
    branch_id: UUID,
    role_id: UUID,
) -> bool:
    """Insert UserBranchRole if missing. Returns True if a row was added."""
    exists = (
        db.query(UserBranchRole.id)
        .filter(
            UserBranchRole.user_id == user_id,
            UserBranchRole.branch_id == branch_id,
        )
        .first()
    )
    if exists:
        return False
    db.add(UserBranchRole(user_id=user_id, branch_id=branch_id, role_id=role_id))
    return True


def _role_id_for_user_in_company(
    db: Session,
    user_id: UUID,
    company_id: UUID,
    *,
    fallback_role_id: UUID,
) -> UUID:
    """Prefer owner/admin role in company; else copy role from any branch in company."""
    privileged = (
        db.query(UserBranchRole.role_id)
        .join(Branch, UserBranchRole.branch_id == Branch.id)
        .join(UserRole, UserBranchRole.role_id == UserRole.id)
        .filter(
            UserBranchRole.user_id == user_id,
            Branch.company_id == company_id,
            func.lower(UserRole.role_name).in_(tuple(_PRIVILEGED_ROLE_NAMES)),
        )
        .first()
    )
    if privileged:
        return privileged[0]
    any_role = (
        db.query(UserBranchRole.role_id)
        .join(Branch, UserBranchRole.branch_id == Branch.id)
        .filter(UserBranchRole.user_id == user_id, Branch.company_id == company_id)
        .first()
    )
    return any_role[0] if any_role else fallback_role_id


def _admin_fallback_role_id(db: Session) -> Optional[UUID]:
    for name in ("admin", "owner"):
        row = db.query(UserRole.id).filter(UserRole.role_name == name).first()
        if row:
            return row[0]
    return None


def _normalize_role_name(name: Optional[str]) -> str:
    return (name or "").strip().lower()


def _user_has_permission_in_company(
    db: Session, user_id: UUID, company_id: UUID, permission_name: str
) -> bool:
    from app.models.permission import Permission, RolePermission

    return (
        db.query(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserBranchRole, UserBranchRole.role_id == RolePermission.role_id)
        .join(Branch, UserBranchRole.branch_id == Branch.id)
        .filter(
            UserBranchRole.user_id == user_id,
            Branch.company_id == company_id,
            Permission.name == permission_name,
        )
        .first()
        is not None
    )


def user_can_list_all_company_branches(
    db: Session, user_id: UUID, company_id: UUID
) -> bool:
    """True if user may list every branch in the company (admin / settings UI)."""
    if _user_has_permission_in_company(db, user_id, company_id, "settings.edit"):
        return True
    return user_is_company_privileged(db, user_id, company_id)


def hq_branch_for_company(db: Session, company_id: UUID) -> Optional[Branch]:
    """HQ branch for company, else first branch by name."""
    hq = (
        db.query(Branch)
        .filter(Branch.company_id == company_id, Branch.is_hq.is_(True))
        .order_by(Branch.name)
        .first()
    )
    if hq:
        return hq
    return (
        db.query(Branch)
        .filter(Branch.company_id == company_id)
        .order_by(Branch.name)
        .first()
    )


def _default_staff_role_id(db: Session) -> Optional[UUID]:
    """Prefer operational roles for auto HQ assignment; admin only as last resort."""
    for name in ("cashier", "staff", "sales", "pharmacist", "dispenser", "manager"):
        row = db.query(UserRole.id).filter(func.lower(UserRole.role_name) == name).first()
        if row:
            return row[0]
    return _admin_fallback_role_id(db)


def ensure_user_assigned_to_company_hq(
    db: Session,
    user_id: UUID,
    company_id: UUID,
    *,
    commit: bool = False,
) -> bool:
    """
    If the user has no branch assignment in this company, grant access to the HQ branch
    (or the company's first branch) with a default staff role. Admins may reassign later.
    Returns True when a new UserBranchRole row was added.
    """
    if branch_ids_assigned_to_user(db, user_id, company_id):
        return False
    branch = hq_branch_for_company(db, company_id)
    if not branch:
        logger.warning(
            "ensure_user_assigned_to_company_hq: no branch for company_id=%s user_id=%s",
            company_id,
            user_id,
        )
        return False
    role_id = _default_staff_role_id(db)
    if role_id is None:
        logger.warning("ensure_user_assigned_to_company_hq: no roles in DB")
        return False
    added = _ensure_user_branch_role(
        db, user_id=user_id, branch_id=branch.id, role_id=role_id
    )
    if added:
        if commit:
            db.commit()
        logger.info(
            "Auto-assigned user to HQ branch user_id=%s company_id=%s branch_id=%s role_id=%s",
            user_id,
            company_id,
            branch.id,
            role_id,
        )
    return added


def branch_ids_assigned_to_user(
    db: Session, user_id: UUID, company_id: UUID
) -> List[UUID]:
    rows = (
        db.query(UserBranchRole.branch_id)
        .join(Branch, UserBranchRole.branch_id == Branch.id)
        .filter(UserBranchRole.user_id == user_id, Branch.company_id == company_id)
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def branches_visible_to_user(
    db: Session,
    user_id: UUID,
    company_id: UUID,
    *,
    include_all_company_branches: bool = False,
) -> List[Branch]:
    """
    Branches the user may see in pickers.
    Default: only branches with a user_branch_roles row.
    include_all_company_branches: every branch in company (admins / settings.edit).
    """
    base = db.query(Branch).filter(Branch.company_id == company_id)
    if include_all_company_branches:
        if not user_can_list_all_company_branches(db, user_id, company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to list all company branches",
            )
        return base.order_by(Branch.name).all()
    assigned_ids = branch_ids_assigned_to_user(db, user_id, company_id)
    if not assigned_ids:
        return []
    return base.filter(Branch.id.in_(assigned_ids)).order_by(Branch.name).all()


def user_has_branch_access(db: Session, user_id: UUID, branch_id: UUID) -> bool:
    return (
        db.query(UserBranchRole.id)
        .filter(
            UserBranchRole.user_id == user_id,
            UserBranchRole.branch_id == branch_id,
        )
        .first()
        is not None
    )


def user_is_company_privileged(db: Session, user_id: UUID, company_id: UUID) -> bool:
    """Owner/admin/manager on any branch in the company."""
    rows = (
        db.query(UserRole.role_name)
        .join(UserBranchRole, UserBranchRole.role_id == UserRole.id)
        .join(Branch, UserBranchRole.branch_id == Branch.id)
        .filter(UserBranchRole.user_id == user_id, Branch.company_id == company_id)
        .all()
    )
    return any(_normalize_role_name(r[0]) in _PRIVILEGED_ROLE_NAMES for r in rows)


def ensure_user_branch_access_or_grant(
    db: Session,
    user_id: UUID,
    branch_id: UUID,
) -> None:
    """
    Require branch access. Company-privileged users are auto-assigned to the branch
    (lazy repair for branches created before provisioning ran).
    """
    if user_has_branch_access(db, user_id, branch_id):
        return
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")
    if user_is_company_privileged(db, user_id, branch.company_id):
        fallback_role_id = _admin_fallback_role_id(db)
        if fallback_role_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this branch",
            )
        role_id = _role_id_for_user_in_company(
            db, user_id, branch.company_id, fallback_role_id=fallback_role_id
        )
        added = _ensure_user_branch_role(
            db, user_id=user_id, branch_id=branch_id, role_id=role_id
        )
        if added:
            db.commit()
        logger.info(
            "Lazy-granted branch access user=%s branch=%s role_id=%s",
            user_id,
            branch_id,
            role_id,
        )
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied to this branch",
    )


def provision_new_branch(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    created_by_user_id: UUID,
) -> None:
    """
    After Branch insert: grant branch access to creator and company admins/owners,
    and enqueue item_branch_snapshot refresh for the new branch.
    """
    fallback_role_id = _admin_fallback_role_id(db)
    if fallback_role_id is None:
        logger.warning(
            "provision_new_branch: no admin/owner role in DB; skipping UserBranchRole grants"
        )
    else:
        creator_role_id = _role_id_for_user_in_company(
            db,
            created_by_user_id,
            company_id,
            fallback_role_id=fallback_role_id,
        )
        _ensure_user_branch_role(
            db,
            user_id=created_by_user_id,
            branch_id=branch_id,
            role_id=creator_role_id,
        )

        privileged_user_ids: Set[UUID] = {
            row[0]
            for row in (
                db.query(UserBranchRole.user_id)
                .join(Branch, UserBranchRole.branch_id == Branch.id)
                .join(UserRole, UserBranchRole.role_id == UserRole.id)
                .filter(
                    Branch.company_id == company_id,
                    func.lower(UserRole.role_name).in_(tuple(_PRIVILEGED_ROLE_NAMES)),
                )
                .distinct()
                .all()
            )
        }
        for uid in privileged_user_ids:
            if uid == created_by_user_id:
                continue
            role_id = _role_id_for_user_in_company(
                db, uid, company_id, fallback_role_id=fallback_role_id
            )
            _ensure_user_branch_role(
                db, user_id=uid, branch_id=branch_id, role_id=role_id
            )

    try:
        SnapshotRefreshService.bulk_refresh_branch_sync(db, company_id, branch_id)
        logger.info(
            "provision_new_branch: bulk snapshot refresh completed branch=%s",
            branch_id,
        )
    except Exception as e:
        logger.warning(
            "provision_new_branch: bulk snapshot failed branch=%s (%s); enqueueing",
            branch_id,
            e,
        )
        SnapshotRefreshService.enqueue_branch_refresh(
            db, company_id, branch_id, reason="new_branch"
        )
