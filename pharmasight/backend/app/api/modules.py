from __future__ import annotations

from typing import Dict, List, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user
from app.dependencies import get_effective_company_id_for_user
from app.module_metadata import get_core_modules, get_module_order
from app.models.user import User
from app.models.company_module import CompanyModule
from app.module_registry import get_user_modules

router = APIRouter(prefix="/modules", tags=["Modules"])

# Roles that should see every module the company has licensed (module switcher UX).
_COMPANY_ADMIN_ROLE_NAMES = frozenset({"admin", "owner", "super admin"})
# Permission fallbacks when role naming differs but user is effectively org admin.
_COMPANY_ADMIN_PERMISSIONS = frozenset({"users.edit", "admin.manage_company"})


def _user_should_see_all_licensed_modules(db: Session, user_id: UUID) -> bool:
    """
    Company admins often lack explicit clinic./lab.* permission rows; infer full module visibility
    from admin-style roles or core admin permissions so Enterprise licensing surfaces in the UI.
    """
    from app.models.user import UserBranchRole, UserRole
    from app.models.permission import Permission, RolePermission

    role_rows = (
        db.query(UserRole.role_name)
        .join(UserBranchRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user_id)
        .distinct()
        .all()
    )
    names = {(str(r[0] or "").strip().lower()) for r in (role_rows or []) if r and r[0]}
    if names & _COMPANY_ADMIN_ROLE_NAMES:
        return True

    hit = (
        db.query(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserBranchRole, UserBranchRole.role_id == RolePermission.role_id)
        .filter(UserBranchRole.user_id == user_id)
        .filter(Permission.name.in_(tuple(_COMPANY_ADMIN_PERMISSIONS)))
        .first()
    )
    return hit is not None


def _modules_visible_ordered(db: Session, allowed: set[str]) -> List[str]:
    """Stable order from DB metadata, intersected with allowed names."""
    allowed_lc = {str(x).strip().lower() for x in allowed if x}
    ordered = [str(m).strip().lower() for m in get_module_order(db) if str(m).strip().lower() in allowed_lc]
    extra = sorted([m for m in allowed_lc if m not in ordered])
    return ordered + extra


@router.get("/me", response_model=Dict[str, List[str]])
def get_my_modules(user_db: Tuple[User, Session] = Depends(get_current_user)):
    """
    UI-only module visibility for the authenticated user.
    This endpoint does NOT enforce access; it only reports what modules the UI may show.

    Company admins (admin / owner / super admin roles, or users.edit / admin.manage_company)
    receive every module in (core ∪ company licensed rows). Other users still use the
    permission-derived module list intersected with that set.
    """
    user, db = user_db
    user_rbac_modules = get_user_modules(db, user.id) or []

    company_id = get_effective_company_id_for_user(db, user)
    if company_id is None:
        # Without a resolved tenant/company, fall back to core modules only.
        allowed = set(get_core_modules(db))
        allowed = {str(x).strip().lower() for x in allowed if x}
        if _user_should_see_all_licensed_modules(db, user.id):
            return {"modules": _modules_visible_ordered(db, allowed)}
        filtered = [str(m).strip().lower() for m in user_rbac_modules if str(m).strip().lower() in allowed]
        return {"modules": filtered}

    # Licensed business/clinical modules from company_modules.
    rows = (
        db.query(CompanyModule.module_name)
        .filter(CompanyModule.company_id == company_id, CompanyModule.is_enabled.is_(True))
        .all()
    )
    licensed_modules = {str(r[0] or "").strip().lower() for r in (rows or []) if r and r[0]}

    # Backward compatibility: if there's no explicit pharmacy row, treat pharmacy as enabled.
    pharmacy_row = (
        db.query(CompanyModule.id)
        .filter(CompanyModule.company_id == company_id, CompanyModule.module_name == "pharmacy")
        .first()
    )
    if pharmacy_row is None:
        licensed_modules.add("pharmacy")

    allowed = set(get_core_modules(db)) | licensed_modules
    allowed = {str(x).strip().lower() for x in allowed if x}

    if _user_should_see_all_licensed_modules(db, user.id):
        return {"modules": _modules_visible_ordered(db, allowed)}

    # Intersection: RBAC-derived modules AND (core ∪ licensed)
    filtered: List[str] = []
    for m in user_rbac_modules:
        if str(m).strip().lower() in allowed:
            filtered.append(str(m).strip().lower())

    return {"modules": filtered}

