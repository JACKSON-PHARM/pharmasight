"""
Impersonation audit logging. PLATFORM_ADMIN-only; every impersonation is logged.
Uses app DB (same as companies/users). No business logic changes.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Table created by migration 070_admin_impersonation_log.sql
TABLE = "admin_impersonation_log"


def log_impersonation_start(
    db: Session,
    admin_identifier: str,
    company_id: UUID,
    user_id: UUID,
    client_ip: Optional[str] = None,
    reason: Optional[str] = None,
) -> UUID:
    """
    Insert a row into admin_impersonation_log. Returns the new row id.
    Call when PLATFORM_ADMIN starts an impersonation session.
    """
    from uuid import uuid4
    row_id = uuid4()
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            INSERT INTO admin_impersonation_log
            (id, admin_identifier, company_id, user_id, started_at, client_ip, reason, created_at)
            VALUES (:id, :admin_identifier, :company_id, :user_id, :started_at, :client_ip, :reason, :created_at)
            """
        ),
        {
            "id": str(row_id),
            "admin_identifier": admin_identifier,
            "company_id": str(company_id),
            "user_id": str(user_id),
            "started_at": now,
            "client_ip": (client_ip or "")[:45],
            "reason": reason or None,
            "created_at": now,
        },
    )
    db.commit()
    logger.info(
        "Impersonation started: admin=%s company_id=%s user_id=%s ip=%s",
        admin_identifier[:20] if admin_identifier else "",
        company_id,
        user_id,
        client_ip,
    )
    return row_id


def log_impersonation_end(
    db: Session,
    log_id: UUID,
) -> None:
    """Set ended_at for an impersonation log row. Optional; call when session ends."""
    db.execute(
        text(
            "UPDATE admin_impersonation_log SET ended_at = :ended_at WHERE id = :id"
        ),
        {"id": str(log_id), "ended_at": datetime.now(timezone.utc)},
    )
    db.commit()
