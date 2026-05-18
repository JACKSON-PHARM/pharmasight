"""
Central finance authorization enforcement (E2.5).

All paths delegate here — resolve_finance_access_context() remains the sole resolver.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.finance.governance.classification import classification_allows, normalize_classification
from app.finance.governance.access_context import FinanceAccessContext
from app.finance.governance.permissions import resolves_finance_permission_with_source
from app.finance.governance.query_scope import ensure_branch_in_allowed
from app.finance.governance.registry import FinanceEndpointGovernanceSpec, get_governance_spec
from app.finance.governance.telemetry import (
    DEPRECATED_PERMISSION_FALLBACK_USED,
    FINANCE_ACCESS_DENIED,
    FINANCE_CLASSIFICATION_DENIED,
    FINANCE_PERMISSION_GRANTED,
    FINANCE_SCOPE_DENIED,
    emit_finance_governance_event,
    emit_scope_usage_signals,
)


def _telemetry_base(ctx: FinanceAccessContext, **kwargs):
    return dict(
        user_id=ctx.user_id,
        company_id=ctx.company_id,
        resolved_scope=ctx.visibility_scope,
        max_classification=ctx.max_classification,
        allowed_branch_ids=ctx.allowed_branch_ids,
        **kwargs,
    )


def assert_finance_access(
    ctx: FinanceAccessContext,
    classification: str,
    db: Session,
    *,
    branch_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    permission: Optional[str] = None,
    registry_id: Optional[str] = None,
) -> None:
    """
    Enforce classification, permission, branch/department scope with governance telemetry.

    registry_id: optional key into FINANCE_GOVERNANCE_REGISTRY for audit metadata.
    """
    spec: Optional[FinanceEndpointGovernanceSpec] = None
    if registry_id:
        spec = get_governance_spec(registry_id)
        if permission is None:
            permission = spec.permission
        classification = spec.classification

    required_cls = normalize_classification(classification)
    reg = registry_id or (spec.registry_id if spec else None)

    if not classification_allows(ctx.max_classification, required_cls):
        emit_finance_governance_event(
            FINANCE_CLASSIFICATION_DENIED,
            **_telemetry_base(
                ctx,
                permission=permission,
                required_classification=required_cls,
                requested_branch_id=branch_id,
                registry_id=reg,
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient data classification clearance",
        )

    if permission:
        granted, via_legacy, legacy_name = resolves_finance_permission_with_source(
            db, ctx.user_id, permission, branch_id=branch_id
        )
        if not granted:
            emit_finance_governance_event(
                FINANCE_ACCESS_DENIED,
                **_telemetry_base(
                    ctx,
                    permission=permission,
                    required_classification=required_cls,
                    requested_branch_id=branch_id,
                    registry_id=reg,
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission {permission} required",
            )
        if via_legacy:
            emit_finance_governance_event(
                DEPRECATED_PERMISSION_FALLBACK_USED,
                **_telemetry_base(
                    ctx,
                    permission=permission,
                    required_classification=required_cls,
                    requested_branch_id=branch_id,
                    registry_id=reg,
                    legacy_permission=legacy_name,
                ),
            )
        else:
            emit_finance_governance_event(
                FINANCE_PERMISSION_GRANTED,
                **_telemetry_base(
                    ctx,
                    permission=permission,
                    required_classification=required_cls,
                    requested_branch_id=branch_id,
                    registry_id=reg,
                ),
            )

    if branch_id is not None:
        try:
            ensure_branch_in_allowed(branch_id, ctx.allowed_branch_ids)
        except HTTPException:
            emit_finance_governance_event(
                FINANCE_SCOPE_DENIED,
                **_telemetry_base(
                    ctx,
                    permission=permission,
                    required_classification=required_cls,
                    requested_branch_id=branch_id,
                    registry_id=reg,
                ),
            )
            raise

    if department_id is not None:
        if ctx.allowed_department_ids is not None and department_id not in ctx.allowed_department_ids:
            emit_finance_governance_event(
                FINANCE_SCOPE_DENIED,
                **_telemetry_base(
                    ctx,
                    permission=permission,
                    required_classification=required_cls,
                    registry_id=reg,
                    detail="department_denied",
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this department",
            )

    emit_scope_usage_signals(
        user_id=ctx.user_id,
        company_id=ctx.company_id,
        visibility_scope=ctx.visibility_scope,
        max_classification=ctx.max_classification,
        allowed_branch_ids=ctx.allowed_branch_ids,
        permission=permission,
        required_classification=required_cls,
        registry_id=reg,
    )
