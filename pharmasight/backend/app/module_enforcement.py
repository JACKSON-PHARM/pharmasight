"""
Company-scoped module gating (single DB, company_id only).

Usage in routes:
    from app.module_enforcement import require_module

    @router.get("/example")
    def example(auth: Tuple[User, Session] = Depends(require_module("opd"))):
        user, db = auth
        ...

Pharmacy is enabled by default when no row exists (backward compatible).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_effective_company_id_for_user
from app.models.company_module import CompanyModule
from app.models.user import User
from app.module_metadata import get_core_modules

# Module name stored/compared lowercase. Missing row => enabled only for this key.
DEFAULT_ENABLED_IF_NO_ROW = "pharmacy"

# Used when the `modules` metadata table is empty or unavailable (align with migration 085 seed).
_FALLBACK_LICENSEABLE_MODULES: List[Tuple[str, str]] = [
    ("pharmacy", "business"),
    ("inventory", "business"),
    ("finance", "business"),
    ("procurement", "business"),
    ("pos", "business"),
    ("billing", "business"),
    ("clinic", "clinical"),
    ("patients", "clinical"),
    ("opd", "clinical"),
    ("prescriptions", "clinical"),
    ("lab", "clinical"),
    ("radiology", "clinical"),
    ("ipd", "clinical"),
    ("emr", "clinical"),
]


def _normalize_module_name(module_name: str) -> str:
    return (module_name or "").strip().lower()


def is_module_enabled_for_company(
    db: Session,
    company_id: UUID,
    module_name: str,
) -> bool:
    """
    True if the company may use this module.

    - Core modules are always enabled (implicit platform modules; derived from modules.is_core).
    - If a row exists: use is_enabled.
    - If no row: pharmacy is treated as enabled; all other modules are disabled.
    """
    normalized = _normalize_module_name(module_name)
    if not normalized:
        return False

    if normalized in get_core_modules(db):
        return True

    row = (
        db.query(CompanyModule)
        .filter(
            CompanyModule.company_id == company_id,
            CompanyModule.module_name == normalized,
        )
        .first()
    )
    if row is not None:
        return bool(row.is_enabled)
    return normalized == DEFAULT_ENABLED_IF_NO_ROW


def get_company_module_license_catalog(db: Session, company_id: UUID) -> List[Dict[str, Any]]:
    """
    All licenseable (non-core) modules for admin UIs, with effective enabled state.

    Rows come from the global ``modules`` table (is_core = false). When that table is empty,
    uses a static fallback list. ``enabled`` matches :func:`is_module_enabled_for_company`.
    """
    core = get_core_modules(db)
    meta_rows: List[Tuple[Any, Any]] = []
    try:
        fetched = db.execute(
            text(
                """
                SELECT name, category
                FROM modules
                WHERE COALESCE(is_core, false) = false
                ORDER BY
                    CASE LOWER(COALESCE(category, ''))
                        WHEN 'business' THEN 1
                        WHEN 'clinical' THEN 2
                        ELSE 3
                    END,
                    LOWER(name)
                """
            )
        ).fetchall()
        if fetched:
            meta_rows = [(r[0], r[1]) for r in fetched if r and r[0]]
    except Exception:
        meta_rows = []

    if not meta_rows:
        meta_rows = list(_FALLBACK_LICENSEABLE_MODULES)

    out: List[Dict[str, Any]] = []
    for name_raw, cat_raw in meta_rows:
        name = str(name_raw or "").strip().lower()
        if not name or name in core:
            continue
        category = str(cat_raw or "business").strip().lower() or "business"
        enabled = is_module_enabled_for_company(db, company_id, name)
        row = (
            db.query(CompanyModule)
            .filter(CompanyModule.company_id == company_id, CompanyModule.module_name == name)
            .first()
        )
        out.append(
            {
                "name": name,
                "category": category,
                "enabled": enabled,
                "has_company_row": row is not None,
            }
        )
    return out


def require_module(module_name: str) -> Callable[..., Tuple[User, Session]]:
    """
    FastAPI dependency factory: require an enabled company module.

    Resolves company_id from the authenticated user (branch assignments).
    Raises 403 if the module is not enabled for that company.
    """

    def _dependency(
        user_db: Tuple[User, Session] = Depends(get_current_user),
    ) -> Tuple[User, Session]:
        user, db = user_db
        company_id = get_effective_company_id_for_user(db, user)
        if company_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot resolve company for module access",
            )
        if not is_module_enabled_for_company(db, company_id, module_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Module '{module_name}' is not enabled for this company",
            )
        return user_db

    return _dependency
