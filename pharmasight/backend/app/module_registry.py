"""
Module registry and UI visibility helpers.

This layer is READ-ONLY and meant for frontend experience (feature visibility),
not for API enforcement. Enforcement remains in route dependencies.
"""

from __future__ import annotations

from typing import Iterable, List
from uuid import UUID

from sqlalchemy.orm import Session


# Permission→module mapping heuristics (UI-only).
# Keep conservative: only emit modules we can infer from existing permission names.
_PERMISSION_PREFIX_TO_MODULE: list[tuple[str, str]] = [
    ("clinic.", "clinic"),
    # Pharmacy (core POS + inventory)
    ("sales.", "pharmacy"),
    ("purchases.", "pharmacy"),
    ("inventory.", "pharmacy"),
    ("items.", "pharmacy"),
    ("suppliers.", "pharmacy"),
    ("orders.", "pharmacy"),
    ("quotations.", "pharmacy"),
    ("reports.", "pharmacy"),
    ("order_book.", "pharmacy"),
    ("stock_take.", "pharmacy"),
    # Finance (OPEX + cashbook tracking)
    ("expenses.", "finance"),
    ("cashbook.", "finance"),
    # Management (settings + users/roles)
    ("settings.", "management"),
    ("users.", "management"),
    ("dashboard.", "management"),
]

_PERMISSION_NAME_TO_MODULE: dict[str, str] = {
    # Some projects use non-prefix permissions; keep explicit overrides here.
    "purchases.manage": "pharmacy",  # aggregate permission introduced for pharmacy UI
    "inventory.manage": "pharmacy",
    "inventory.adjust": "pharmacy",
}


def _modules_from_permissions(
    permission_names: Iterable[str],
    module_order: List[str],
) -> list[str]:
    enabled: set[str] = set()
    for name in permission_names:
        if not name:
            continue
        m = _PERMISSION_NAME_TO_MODULE.get(name)
        if m:
            enabled.add(m)
            continue
        for prefix, module in _PERMISSION_PREFIX_TO_MODULE:
            if name.startswith(prefix):
                enabled.add(module)
                break
    # Stable ordering for frontend derived from modules table
    ordered = [m for m in module_order if m in enabled]
    remaining = sorted([m for m in enabled if m not in ordered])
    return ordered + remaining


def get_user_modules(db: Session, user_id: UUID) -> List[str]:
    """
    Return modules that should be visible to the user in the UI.

    Rules:
    - Derived from existing RBAC assignments (user_branch_roles -> role_permissions -> permissions)
    - No new schema / no enforcement side-effects
    - Fast: single query to fetch distinct permission names for the user
    """
    from app.models.user import UserBranchRole
    from app.models.permission import Permission, RolePermission

    rows = (
        db.query(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserBranchRole, UserBranchRole.role_id == RolePermission.role_id)
        .filter(UserBranchRole.user_id == user_id)
        .distinct()
        .all()
    )
    perm_names = [r[0] for r in (rows or []) if r and r[0]]
    from app.module_metadata import get_module_order

    module_order = get_module_order(db)
    return _modules_from_permissions(perm_names, module_order)

