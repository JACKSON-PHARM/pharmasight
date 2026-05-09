"""Operational audit logging for KRA control-plane actions."""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.kra_audit_event import KraAuditEvent


class KraAuditService:
    @staticmethod
    def log_event(
        db: Session,
        *,
        company_id: UUID,
        event_type: str,
        event_status: str = "info",
        message: str | None = None,
        branch_id: Optional[UUID] = None,
        actor_user_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        db.add(
            KraAuditEvent(
                company_id=company_id,
                branch_id=branch_id,
                actor_user_id=actor_user_id,
                event_type=(event_type or "").strip()[:80] or "unknown",
                event_status=(event_status or "info").strip()[:30] or "info",
                message=(message or "").strip()[:4000] or None,
                metadata_json=metadata or None,
            )
        )
