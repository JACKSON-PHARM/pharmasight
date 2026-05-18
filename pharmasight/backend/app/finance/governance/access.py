"""
Unified finance access checks (E2.5).

All paths: resolve_finance_access_context() -> assert_finance_access() via assert_access().
"""
from __future__ import annotations

from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.finance.governance.access_context import FinanceAccessContext
from app.finance.governance.context import assert_access, resolve_finance_access_context
from app.finance.governance.registry import get_governance_spec
from app.finance.governance.report_context import ReportContext
from app.models import Branch, User


def parse_branch_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value).strip())
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid branch UUID",
        )


def resolve_finance_branch_id(
    ctx: FinanceAccessContext,
    db: Session,
    *,
    branch_id_query: Optional[UUID] = None,
    x_branch_id: Optional[str] = None,
    classification: str,
    permission: str,
    registry_id: Optional[str] = None,
    required: bool = True,
) -> UUID:
    """Resolve branch from query or header; enforce via context + assert_access."""
    branch_id_final = branch_id_query or parse_branch_uuid(x_branch_id)
    if not branch_id_final:
        if required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="branch_id (or X-Branch-ID header) is required",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Branch context is required",
        )
    branch = (
        db.query(Branch)
        .filter(Branch.id == branch_id_final, Branch.company_id == ctx.company_id)
        .first()
    )
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found",
        )
    assert_access(
        ctx,
        classification,
        db,
        branch_id=branch_id_final,
        permission=permission,
        registry_id=registry_id,
    )
    return branch_id_final


def require_finance_branch(
    db: Session,
    user: User,
    company_id: UUID,
    permission: str,
    classification: str,
    *,
    branch_id_query: Optional[UUID] = None,
    x_branch_id: Optional[str] = None,
    registry_id: Optional[str] = None,
) -> Tuple[FinanceAccessContext, UUID]:
    """Resolve context, assert permission + classification, return (ctx, branch_id)."""
    if registry_id:
        spec = get_governance_spec(registry_id)
        permission = spec.permission
        classification = spec.classification
    ctx = resolve_finance_access_context(user, db, company_id)
    branch_id_final = resolve_finance_branch_id(
        ctx,
        db,
        branch_id_query=branch_id_query,
        x_branch_id=x_branch_id,
        classification=classification,
        permission=permission,
        registry_id=registry_id,
        required=True,
    )
    return ctx, branch_id_final


def guard_finance_report_access(
    db: Session,
    user: User,
    company_id: UUID,
    permission: str,
    classification: str,
    *,
    branch_id: Optional[UUID] = None,
    registry_id: Optional[str] = None,
) -> ReportContext:
    """Resolve context for optional-branch finance reports; returns ReportContext."""
    if registry_id:
        spec = get_governance_spec(registry_id)
        permission = spec.permission
        classification = spec.classification
    ctx = resolve_finance_access_context(user, db, company_id)
    assert_access(
        ctx,
        classification,
        db,
        branch_id=branch_id,
        permission=permission,
        registry_id=registry_id,
    )
    scope = ctx.resolve_branch_query_scope(branch_id)
    if not scope.is_safe_to_query:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No branch visibility for this report",
        )
    return ReportContext.from_access(ctx)


def deny_unless_finance_permission(
    db: Session,
    user: User,
    company_id: UUID,
    permission: str,
    classification: str,
    *,
    branch_id: Optional[UUID] = None,
    registry_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> FinanceAccessContext:
    if registry_id:
        spec = get_governance_spec(registry_id)
        permission = spec.permission
        classification = spec.classification
    ctx = resolve_finance_access_context(user, db, company_id)
    try:
        assert_access(
            ctx,
            classification,
            db,
            branch_id=branch_id,
            permission=permission,
            registry_id=registry_id,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN and detail:
            raise HTTPException(status_code=exc.status_code, detail=detail) from exc
        raise
    return ctx


def guard_finance_branch_query_param(
    db: Session,
    *,
    user: User,
    company_id: UUID,
    permission: str,
    classification: str,
    branch_id: Optional[UUID],
    registry_id: Optional[str] = None,
) -> ReportContext:
    return guard_finance_report_access(
        db,
        user,
        company_id,
        permission,
        classification,
        branch_id=branch_id,
        registry_id=registry_id,
    )
