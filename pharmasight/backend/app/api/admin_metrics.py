"""
Platform Admin Dashboard metrics API.

All endpoints require PLATFORM_ADMIN (get_current_admin). Data is aggregated only;
no item-level inventory or sensitive transactional data. Rate limited.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.rate_limit import limiter
from app.services.platform_metrics_service import (
    get_summary,
    get_companies_list,
    get_branches_list,
    get_active_users_metrics,
    get_active_users_timeseries,
    get_usage_by_company,
    get_health,
)

router = APIRouter()


def _parse_date(s: Optional[str], default_offset_days: Optional[int] = None):
    """Parse ISO date string or return None; if default_offset_days, return now - offset."""
    if s:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if default_offset_days is not None:
        return datetime.now(timezone.utc) - timedelta(days=default_offset_days)
    return None


@router.get("/metrics/summary")
@limiter.limit("30/minute")
def metrics_summary(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(get_current_admin),
):
    """
    High-level counts: companies, branches, users, active sessions (now).
    PLATFORM_ADMIN only. Aggregated; no sensitive data.
    """
    return get_summary(db)


@router.get("/metrics/companies")
@limiter.limit("30/minute")
def metrics_companies(
    request: Request,
    db: Session = Depends(get_db),
    company_id: Optional[UUID] = Query(None, description="Filter by company"),
    date_from: Optional[str] = Query(None, description="ISO date, filter companies created on or after"),
    date_to: Optional[str] = Query(None, description="ISO date, filter companies created on or before"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: None = Depends(get_current_admin),
):
    """
    List companies with branch_count and user_count. Optional filters.
    PLATFORM_ADMIN only.
    """
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    return get_companies_list(db, company_id=company_id, date_from=df, date_to=dt, limit=limit, offset=offset)


@router.get("/metrics/branches")
@limiter.limit("30/minute")
def metrics_branches(
    request: Request,
    db: Session = Depends(get_db),
    company_id: Optional[UUID] = Query(None, description="Filter by company"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: None = Depends(get_current_admin),
):
    """
    List branches with company name. last_activity not in schema (null); extend with activity log to populate.
    PLATFORM_ADMIN only.
    """
    return get_branches_list(db, company_id=company_id, limit=limit, offset=offset)


@router.get("/metrics/active-users")
@limiter.limit("30/minute")
def metrics_active_users(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(get_current_admin),
):
    """
    Active user counts: now (sessions with valid refresh token), last 24h, last 7d.
    Source: refresh_tokens. PLATFORM_ADMIN only.
    """
    return get_active_users_metrics(db)


@router.get("/metrics/active-users/timeseries")
@limiter.limit("30/minute")
def metrics_active_users_timeseries(
    request: Request,
    db: Session = Depends(get_db),
    days: int = Query(14, ge=1, le=90),
    _admin: None = Depends(get_current_admin),
):
    """
    Daily active users over time (for charts). Source: refresh_tokens.issued_at.
    PLATFORM_ADMIN only.
    """
    return get_active_users_timeseries(db, days=days)


@router.get("/metrics/usage-by-company")
@limiter.limit("30/minute")
def metrics_usage_by_company(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(get_current_admin),
):
    """
    Active sessions and token count per company. For billing/usage trends.
    PLATFORM_ADMIN only.
    """
    data = get_usage_by_company(db)
    return {"companies": data, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/metrics/health")
@limiter.limit("60/minute")
def metrics_health(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(get_current_admin),
):
    """
    System health: DB connectivity, server time. PLATFORM_ADMIN only.
    """
    return get_health(db)


@router.get("/metrics/errors")
@limiter.limit("30/minute")
def metrics_errors(
    request: Request,
    _admin: None = Depends(get_current_admin),
):
    """
    Placeholder: failed API calls, exceptions, auth failures.
    No error log table yet; integrate with APM or add middleware + table to populate.
    Returns empty structure for dashboard compatibility.
    """
    return {
        "by_endpoint": [],
        "by_company": [],
        "auth_failures_24h": 0,
        "server_errors_24h": 0,
        "message": "Integrate with error logging or APM to populate.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics/request-volume")
@limiter.limit("30/minute")
def metrics_request_volume(
    request: Request,
    _admin: None = Depends(get_current_admin),
):
    """
    Placeholder: API request volume per company/branch per hour, peak concurrent users.
    Add middleware + metrics table to record requests; then aggregate here.
    Returns empty structure for dashboard compatibility.
    """
    return {
        "by_hour": [],
        "by_company": [],
        "peak_concurrent_users": 0,
        "avg_response_time_ms": None,
        "message": "Add request logging middleware to populate.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
