"""
Declarative finance guard wrappers (E2.5) — syntactic sugar only.

Delegates to resolve_finance_access_context + assert_finance_access; no alternate logic.
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request

from app.dependencies import get_current_user, get_tenant_db
from app.finance.governance.access_context import FinanceAccessContext
from app.finance.governance.context import resolve_finance_access_context
from app.finance.governance.enforcement import assert_finance_access
from app.finance.governance.registry import get_governance_spec
from app.finance.governance.request_context import bind_fastapi_request


def finance_guard(
    registry_id: str,
    *,
    branch_id_param: Optional[str] = "branch_id",
):
    """
    FastAPI dependency factory keyed by FINANCE_GOVERNANCE_REGISTRY.

    Injects FinanceAccessContext after successful authorization.
    """

    spec = get_governance_spec(registry_id)

    def _dependency(
        request: Request,
        user_db=Depends(get_current_user),
        db=Depends(get_tenant_db),
    ) -> FinanceAccessContext:
        bind_fastapi_request(request)
        user, _session = user_db
        company_id = getattr(request.state, "effective_company_id", None)
        if company_id is None:
            raise HTTPException(status_code=400, detail="Company context not available")
        ctx = resolve_finance_access_context(user, db, company_id)
        branch_id: Optional[UUID] = None
        if branch_id_param and branch_id_param in request.path_params:
            branch_id = UUID(str(request.path_params[branch_id_param]))
        elif branch_id_param:
            raw = request.query_params.get(branch_id_param)
            if raw:
                branch_id = UUID(str(raw))
        assert_finance_access(
            ctx,
            spec.classification,
            db,
            branch_id=branch_id,
            permission=spec.permission,
            registry_id=registry_id,
        )
        return ctx

    return _dependency


def finance_guard_handler(registry_id: str) -> Callable:
    """Decorator for sync handlers that already receive (request, user, db, ...)."""

    spec = get_governance_spec(registry_id)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is not None:
                bind_fastapi_request(request)
            return fn(*args, **kwargs)

        wrapper.__finance_guard_registry_id__ = registry_id  # type: ignore[attr-defined]
        wrapper.__finance_guard_spec__ = spec  # type: ignore[attr-defined]
        return wrapper

    return decorator
