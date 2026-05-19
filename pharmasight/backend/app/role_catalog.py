"""
Canonical company roles and module-access templates (RBAC).

- Company assignable roles use stable ``role_name`` slugs (e.g. super_admin, admin).
- ``platform_super_admin`` is reserved for SightOps platform ops (not assignable in company Settings).
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, List, Optional, Set

# Top-bar module switcher slugs (must have permissions.modules.<slug>).
LICENSEABLE_MODULE_SLUGS: tuple[str, ...] = (
    "pharmacy",
    "inventory",
    "finance",
    "procurement",
    "pos",
    "billing",
    "wholesale",
    "clinic",
    "patients",
    "opd",
    "prescriptions",
    "lab",
    "radiology",
    "ipd",
    "emr",
    "management",
)

# Names that collapse to the same canonical role (before merge migration).
ROLE_NAME_ALIASES: Dict[str, str] = {
    "super admin": "super_admin",
    "super_admin": "super_admin",
    "superadmin": "super_admin",
    "Super Admin": "super_admin",
    "administrator": "admin",
    "owner": "admin",
}

NON_ASSIGNABLE_ROLE_KEYS: FrozenSet[str] = frozenset({"platform_super_admin"})

CANONICAL_ROLES: Dict[str, Dict[str, str]] = {
    "super_admin": {
        "display_label": "Super Admin",
        "description": "Full access: all modules and all actions (create, edit, delete).",
    },
    "admin": {
        "display_label": "Administrator",
        "description": "All modules; can view and update but not create new records (company settings excepted).",
    },
    "pharmacist": {
        "display_label": "Pharmacist",
        "description": "Pharmacy, inventory, sales, and purchases.",
    },
    "cashier": {
        "display_label": "Cashier",
        "description": "Pharmacy POS / sales only.",
    },
    "procurement": {
        "display_label": "Procurement",
        "description": "Purchasing and inventory receiving.",
    },
    "auditor": {
        "display_label": "Auditor",
        "description": "Stock take and read-only operational views.",
    },
    "counter": {
        "display_label": "Counter",
        "description": "Stock-take counting sessions only.",
    },
    "viewer": {
        "display_label": "Viewer",
        "description": "Read-only across assigned modules.",
    },
    "platform_super_admin": {
        "display_label": "Platform Super Admin",
        "description": "SightOps internal — cross-company platform console (not for company staff).",
    },
}


def normalize_role_key(role_name: Optional[str]) -> str:
    raw = (role_name or "").strip()
    if not raw:
        return ""
    if raw in ROLE_NAME_ALIASES:
        return ROLE_NAME_ALIASES[raw]
    slug = raw.lower().replace(" ", "_").replace("-", "_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return ROLE_NAME_ALIASES.get(slug, slug)


def is_assignable_role(role_name: Optional[str]) -> bool:
    key = normalize_role_key(role_name)
    return bool(key) and key not in NON_ASSIGNABLE_ROLE_KEYS


def display_label_for_role(role_name: Optional[str]) -> str:
    key = normalize_role_key(role_name)
    meta = CANONICAL_ROLES.get(key)
    if meta:
        return meta["display_label"]
    return (role_name or key or "Role").strip()


def description_for_role(role_name: Optional[str]) -> Optional[str]:
    key = normalize_role_key(role_name)
    meta = CANONICAL_ROLES.get(key)
    return meta["description"] if meta else None


def module_permission_names(slugs: Optional[Iterable[str]] = None) -> List[str]:
    use = slugs if slugs is not None else LICENSEABLE_MODULE_SLUGS
    return [f"modules.{s}" for s in use]


def permission_names_for_super_admin(all_permission_names: Iterable[str]) -> List[str]:
    return sorted(set(all_permission_names))


def permission_names_for_admin(all_permission_names: Iterable[str]) -> List[str]:
    """All modules; view/edit/update; no create (except settings.view for navigation)."""
    out: Set[str] = set()
    for name in all_permission_names:
        n = (name or "").strip()
        if not n:
            continue
        if n.startswith("modules."):
            out.add(n)
            continue
        if n.endswith(".create"):
            continue
        if ".create" in n and n.split(".")[-1] == "create":
            continue
        # action column style
        if n.endswith(".delete"):
            out.add(n)
            continue
        out.add(n)
    # Ensure management module visible for admins
    out.add("modules.management")
    out.update(module_permission_names())
    return sorted(out)


def permission_names_for_pharmacist(all_permission_names: Iterable[str]) -> List[str]:
    prefixes = (
        "sales.",
        "purchases.",
        "inventory.",
        "items.",
        "orders.",
        "quotations.",
        "reports.",
        "order_book.",
        "stock_take.",
        "suppliers.",
    )
    mods = ("pharmacy", "inventory", "management")
    return _filter_permissions(all_permission_names, prefixes=prefixes, module_slugs=mods)


def permission_names_for_cashier(all_permission_names: Iterable[str]) -> List[str]:
    allow = {
        "sales.view",
        "sales.view_own",
        "sales.view_all",
        "sales.create",
        "items.view",
        "dashboard.view_sales",
        "dashboard.view_items",
    }
    return _filter_permissions(
        all_permission_names,
        explicit=allow,
        module_slugs=("pharmacy", "management"),
    )


def permission_names_for_procurement(all_permission_names: Iterable[str]) -> List[str]:
    prefixes = ("purchases.", "inventory.", "items.view", "suppliers.", "reports.view")
    return _filter_permissions(
        all_permission_names, prefixes=prefixes, module_slugs=("pharmacy", "inventory", "management")
    )


def permission_names_for_viewer(all_permission_names: Iterable[str]) -> List[str]:
    out: Set[str] = set(module_permission_names(("management",)))
    for name in all_permission_names:
        n = (name or "").strip()
        if not n or n.startswith("modules."):
            continue
        if ".view" in n or n.endswith(".view") or "view_" in n:
            out.add(n)
        if n.startswith("dashboard."):
            out.add(n)
    return sorted(out)


def permission_names_for_auditor(all_permission_names: Iterable[str]) -> List[str]:
    prefixes = ("stock_take.", "inventory.view", "items.view", "reports.view")
    return _filter_permissions(
        all_permission_names, prefixes=prefixes, module_slugs=("pharmacy", "management")
    )


def permission_names_for_counter(all_permission_names: Iterable[str]) -> List[str]:
    prefixes = ("stock_take.",)
    return _filter_permissions(
        all_permission_names, prefixes=prefixes, module_slugs=("pharmacy", "management")
    )


def template_permission_names(role_key: str, all_permission_names: Iterable[str]) -> Optional[List[str]]:
    key = normalize_role_key(role_key)
    names = list(all_permission_names)
    if key == "super_admin":
        return permission_names_for_super_admin(names)
    if key == "admin":
        return permission_names_for_admin(names)
    if key == "pharmacist":
        return permission_names_for_pharmacist(names)
    if key == "cashier":
        return permission_names_for_cashier(names)
    if key == "procurement":
        return permission_names_for_procurement(names)
    if key == "viewer":
        return permission_names_for_viewer(names)
    if key == "auditor":
        return permission_names_for_auditor(names)
    if key == "counter":
        return permission_names_for_counter(names)
    return None


def _filter_permissions(
    all_permission_names: Iterable[str],
    *,
    prefixes: tuple[str, ...] = (),
    explicit: Optional[Set[str]] = None,
    module_slugs: tuple[str, ...] = (),
) -> List[str]:
    out: Set[str] = set()
    if module_slugs:
        out.update(module_permission_names(module_slugs))
    for name in all_permission_names:
        n = (name or "").strip()
        if not n:
            continue
        if explicit and n in explicit:
            out.add(n)
            continue
        if prefixes and any(n.startswith(p) for p in prefixes):
            out.add(n)
    return sorted(out)
