"""Tenant-scoped KRA execution activation (vs deployment/infrastructure toggles)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Company


def company_kra_execution_enabled(db: Session, company_id: UUID) -> bool:
    """True when this company may enqueue and process KRA outbox work."""
    row = db.query(Company).filter(Company.id == company_id).first()
    return bool(row and getattr(row, "kra_enabled", False))
