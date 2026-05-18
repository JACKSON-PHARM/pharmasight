"""
Append-only finance governance audit telemetry (E2.5).

Never raises to callers; never blocks request handling on logging failure.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, FrozenSet, Optional, Sequence
from uuid import UUID

from app.finance.governance.request_context import (
    get_finance_correlation_id,
    get_finance_endpoint,
)

logger = logging.getLogger("pharmasight.finance.governance")

# Canonical event names
FINANCE_ACCESS_DENIED = "finance_access_denied"
FINANCE_SCOPE_DENIED = "finance_scope_denied"
FINANCE_CLASSIFICATION_DENIED = "finance_classification_denied"
FINANCE_PERMISSION_GRANTED = "finance_permission_granted"
FINANCE_AUDIT_SCOPE_USED = "finance_audit_scope_used"
FINANCE_EXECUTIVE_SCOPE_USED = "finance_executive_scope_used"
FINANCE_COMPANY_SCOPE_USED = "finance_company_scope_used"
DEPRECATED_PERMISSION_FALLBACK_USED = "deprecated_permission_fallback_used"

ALL_TELEMETRY_EVENTS: frozenset[str] = frozenset(
    {
        FINANCE_ACCESS_DENIED,
        FINANCE_SCOPE_DENIED,
        FINANCE_CLASSIFICATION_DENIED,
        FINANCE_PERMISSION_GRANTED,
        FINANCE_AUDIT_SCOPE_USED,
        FINANCE_EXECUTIVE_SCOPE_USED,
        FINANCE_COMPANY_SCOPE_USED,
        DEPRECATED_PERMISSION_FALLBACK_USED,
    }
)


def _uuid_list(ids: Optional[FrozenSet[UUID]]) -> list[str]:
    if not ids:
        return []
    return [str(x) for x in sorted(ids, key=str)]


@dataclass(frozen=True)
class FinanceGovernanceTelemetryPayload:
    event: str
    user_id: str
    company_id: str
    timestamp: str
    endpoint: Optional[str] = None
    permission: Optional[str] = None
    required_classification: Optional[str] = None
    resolved_scope: Optional[str] = None
    max_classification: Optional[str] = None
    requested_branch_id: Optional[str] = None
    allowed_branch_ids: list[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    registry_id: Optional[str] = None
    detail: Optional[str] = None
    legacy_permission: Optional[str] = None

    def to_log_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and v != []}


def emit_finance_governance_event(
    event: str,
    *,
    user_id: UUID,
    company_id: UUID,
    permission: Optional[str] = None,
    required_classification: Optional[str] = None,
    resolved_scope: Optional[str] = None,
    max_classification: Optional[str] = None,
    requested_branch_id: Optional[UUID] = None,
    allowed_branch_ids: Optional[FrozenSet[UUID]] = None,
    endpoint: Optional[str] = None,
    correlation_id: Optional[str] = None,
    registry_id: Optional[str] = None,
    detail: Optional[str] = None,
    legacy_permission: Optional[str] = None,
) -> None:
    """Fire-and-forget governance telemetry (swallows all logging errors)."""
    if event not in ALL_TELEMETRY_EVENTS:
        return
    try:
        payload = FinanceGovernanceTelemetryPayload(
            event=event,
            user_id=str(user_id),
            company_id=str(company_id),
            timestamp=datetime.now(timezone.utc).isoformat(),
            endpoint=endpoint or get_finance_endpoint(),
            permission=permission,
            required_classification=required_classification,
            resolved_scope=resolved_scope,
            max_classification=max_classification,
            requested_branch_id=str(requested_branch_id) if requested_branch_id else None,
            allowed_branch_ids=_uuid_list(allowed_branch_ids),
            correlation_id=correlation_id or get_finance_correlation_id(),
            registry_id=registry_id,
            detail=detail,
            legacy_permission=legacy_permission,
        )
        line = json.dumps(payload.to_log_dict(), default=str)
        if event.endswith("_denied"):
            logger.warning(line)
        else:
            logger.info(line)
    except Exception:
        logger.debug("finance governance telemetry suppressed", exc_info=True)


def emit_scope_usage_signals(
    *,
    user_id: UUID,
    company_id: UUID,
    visibility_scope: str,
    max_classification: str,
    allowed_branch_ids: FrozenSet[UUID],
    permission: Optional[str],
    required_classification: Optional[str],
    registry_id: Optional[str] = None,
) -> None:
    """Emit positive scope/classification usage signals after successful authorization."""
    common = dict(
        user_id=user_id,
        company_id=company_id,
        permission=permission,
        required_classification=required_classification,
        resolved_scope=visibility_scope,
        max_classification=max_classification,
        allowed_branch_ids=allowed_branch_ids,
        registry_id=registry_id,
    )
    if visibility_scope == "AUDIT_READ":
        emit_finance_governance_event(FINANCE_AUDIT_SCOPE_USED, **common)
    if visibility_scope == "COMPANY":
        emit_finance_governance_event(FINANCE_COMPANY_SCOPE_USED, **common)
    if max_classification == "executive":
        emit_finance_governance_event(FINANCE_EXECUTIVE_SCOPE_USED, **common)
