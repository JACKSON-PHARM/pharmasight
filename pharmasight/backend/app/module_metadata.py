"""
Module metadata lookup (core/business/clinical) backed by the `modules` table.

This avoids duplicating core/biz/clinical classification in Python constants.
"""

from __future__ import annotations

from typing import Optional, Set, List, Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Process-local cache. Module metadata is assumed global (not company-scoped).
_CORE_MODULES_CACHE: Optional[Set[str]] = None


def get_module_category(db: Session, module_name: str) -> Optional[str]:
    """
    Return module category from the `modules` table.

    Expected values: 'core' | 'business' | 'clinical'
    """
    if not module_name:
        return None
    normalized = str(module_name).strip().lower()
    if not normalized:
        return None

    try:
        row = db.execute(
            text("SELECT category FROM modules WHERE name = :name LIMIT 1"),
            {"name": normalized},
        ).first()
    except Exception:
        return None
    if not row:
        return None
    return row[0]


def get_core_modules(db: Session) -> Set[str]:
    """
    Return all module names where modules.is_core = true.
    """
    global _CORE_MODULES_CACHE
    if _CORE_MODULES_CACHE is not None:
        return set(_CORE_MODULES_CACHE)

    try:
        rows = db.execute(text("SELECT name FROM modules WHERE is_core = true")).fetchall()
        _CORE_MODULES_CACHE = {str(r[0] or "").strip().lower() for r in rows if r and r[0] is not None}
        _CORE_MODULES_CACHE.discard("")
        return set(_CORE_MODULES_CACHE)
    except Exception:
        # Safety fallback if the metadata migration hasn't been applied yet.
        # Once `085_modules_metadata_seed.sql` is deployed, this path should not be hit.
        _CORE_MODULES_CACHE = {
            "management",
            "settings",
            "users",
            "roles",
            "reports",
            "dashboard",
            "notifications",
            "audit_logs",
        }
        return set(_CORE_MODULES_CACHE)


def get_module_order(db: Session) -> List[str]:
    """
    Return a stable module order derived from `modules` table.
    Core first, then business, then clinical, then alphabetical.
    """
    try:
        rows = db.execute(
            text(
                """
                SELECT name, category
                FROM modules
                ORDER BY
                    CASE category
                        WHEN 'core' THEN 1
                        WHEN 'business' THEN 2
                        WHEN 'clinical' THEN 3
                        ELSE 4
                    END,
                    LOWER(name)
                """
            )
        ).fetchall()
    except Exception:
        # Backward compatible ordering when metadata table isn't present yet.
        return [
            "management",
            "settings",
            "users",
            "roles",
            "reports",
            "dashboard",
            "notifications",
            "audit_logs",
            "pharmacy",
            "clinic",
            "lab",
            "billing",
            "finance",
        ]
    out: List[str] = []
    for r in rows:
        if not r or r[0] is None:
            continue
        out.append(str(r[0]).strip().lower())
    return out



