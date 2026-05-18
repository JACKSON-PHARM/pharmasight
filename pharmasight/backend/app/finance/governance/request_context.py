"""
Request-scoped metadata for finance governance telemetry (contextvars).
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_correlation_id: ContextVar[Optional[str]] = ContextVar("finance_correlation_id", default=None)
_endpoint: ContextVar[Optional[str]] = ContextVar("finance_endpoint", default=None)


def set_finance_request_context(
    *,
    endpoint: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> None:
    if endpoint is not None:
        _endpoint.set(endpoint)
    if correlation_id is not None:
        _correlation_id.set(correlation_id)


def get_finance_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def get_finance_endpoint() -> Optional[str]:
    return _endpoint.get()


def bind_fastapi_request(request) -> None:
    """Extract correlation id and route from a FastAPI/Starlette request."""
    correlation_id = (
        request.headers.get("X-Request-ID")
        or request.headers.get("X-Correlation-ID")
        or getattr(request.state, "correlation_id", None)
        or getattr(request.state, "request_id", None)
    )
    endpoint = None
    route = request.scope.get("route")
    if route is not None:
        endpoint = getattr(route, "path", None) or str(route)
    set_finance_request_context(endpoint=endpoint, correlation_id=correlation_id)
