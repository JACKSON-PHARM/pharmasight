"""List and resolve GL posting failures (soft-fail audit trail)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.accounting import GlPostingFailure

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def failure_to_dict(row: GlPostingFailure) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "branch_id": str(row.branch_id) if row.branch_id else None,
        "source_type": row.source_type,
        "source_id": str(row.source_id),
        "posting_kind": row.posting_kind,
        "idempotency_key": row.idempotency_key,
        "error_message": row.error_message,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_gl_posting_failures(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID] = None,
    unresolved_only: bool = True,
    source_type: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> Dict[str, Any]:
    limit = min(max(1, limit), MAX_LIMIT)
    offset = max(0, offset)

    q = db.query(GlPostingFailure).filter(GlPostingFailure.company_id == company_id)
    if branch_id is not None:
        q = q.filter(GlPostingFailure.branch_id == branch_id)
    if unresolved_only:
        q = q.filter(GlPostingFailure.resolved_at.is_(None))
    if source_type:
        q = q.filter(GlPostingFailure.source_type == source_type.strip())

    total = q.count()
    rows = (
        q.order_by(GlPostingFailure.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    unresolved_count = (
        db.query(GlPostingFailure)
        .filter(
            GlPostingFailure.company_id == company_id,
            GlPostingFailure.resolved_at.is_(None),
        )
        .count()
    )

    return {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "unresolved_only": unresolved_only,
        "total_matching": total,
        "unresolved_count": unresolved_count,
        "limit": limit,
        "offset": offset,
        "items": [failure_to_dict(r) for r in rows],
    }


def resolve_gl_posting_failure(
    db: Session,
    *,
    company_id: UUID,
    failure_id: UUID,
) -> GlPostingFailure:
    row = (
        db.query(GlPostingFailure)
        .filter(
            GlPostingFailure.id == failure_id,
            GlPostingFailure.company_id == company_id,
        )
        .first()
    )
    if not row:
        raise ValueError("Posting failure not found")
    if row.resolved_at is None:
        row.resolved_at = datetime.now(timezone.utc)
        db.flush()
    return row
