"""
Platform Admin metrics: aggregated usage, health, and engagement.
Data sources: companies, branches, users, user_branch_roles, refresh_tokens (app DB).
No item-level inventory or transactional data; counts and aggregates only.
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, func

from app.models.company import Company, Branch
from app.models.user import User, UserBranchRole


def get_summary(db: Session) -> Dict[str, Any]:
    """
    High-level counts for dashboard cards.
    Source: companies, branches, users (deleted_at IS NULL), refresh_tokens (active + not expired).
    """
    companies_count = db.query(func.count(Company.id)).scalar() or 0
    branches_count = db.query(func.count(Branch.id)).filter(Branch.is_active.is_(True)).scalar() or 0
    users_count = (
        db.query(func.count(User.id))
        .filter(User.deleted_at.is_(None), User.is_active.is_(True))
        .scalar()
        or 0
    )
    # Active sessions = distinct users with at least one active refresh token (is_active and expires_at > now)
    try:
        r = db.execute(
            text(
                """
                SELECT COUNT(DISTINCT user_id) AS n
                FROM refresh_tokens
                WHERE is_active = TRUE AND expires_at > NOW()
                """
            )
        ).fetchone()
        active_sessions = r[0] if r else 0
    except Exception:
        active_sessions = 0
    return {
        "companies_count": companies_count,
        "branches_count": branches_count,
        "users_count": users_count,
        "active_sessions_now": active_sessions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_companies_list(
    db: Session,
    company_id: Optional[UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    List companies with aggregated branch count and user count.
    Optional filters: company_id (single), date_from/date_to (company created_at).
    """
    q = db.query(Company)
    if company_id:
        q = q.filter(Company.id == company_id)
    if date_from:
        q = q.filter(Company.created_at >= date_from)
    if date_to:
        q = q.filter(Company.created_at <= date_to)
    total = q.count()
    companies = q.order_by(Company.created_at.desc()).offset(offset).limit(limit).all()
    # Branch count per company (subquery or separate)
    branch_counts = (
        db.query(Branch.company_id, func.count(Branch.id).label("n"))
        .filter(Branch.is_active.is_(True))
        .group_by(Branch.company_id)
        .all()
    )
    bc_map = {str(cid): n for cid, n in branch_counts}
    # User count per company: users that have at least one UserBranchRole in a branch of that company
    user_counts_raw = (
        db.query(Branch.company_id, func.count(func.distinct(UserBranchRole.user_id)).label("n"))
        .join(UserBranchRole, UserBranchRole.branch_id == Branch.id)
        .join(User, User.id == UserBranchRole.user_id)
        .filter(User.deleted_at.is_(None), User.is_active.is_(True))
        .group_by(Branch.company_id)
        .all()
    )
    uc_map = {str(cid): n for cid, n in user_counts_raw}
    rows = []
    for c in companies:
        rows.append({
            "id": str(c.id),
            "name": c.name,
            "branch_count": bc_map.get(str(c.id), 0),
            "user_count": uc_map.get(str(c.id), 0),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return {
        "total": total,
        "companies": rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_branches_list(
    db: Session,
    company_id: Optional[UUID] = None,
    limit: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    List branches with company name. Optional company_id filter.
    last_activity: latest refresh_tokens.issued_at for any user with access to this branch
    (proxy for "last login/session from this branch"). Falls back to branch.updated_at if no tokens.
    """
    q = (
        db.query(Branch)
        .options(joinedload(Branch.company))
        .join(Company, Company.id == Branch.company_id)
    )
    if company_id:
        q = q.filter(Branch.company_id == company_id)
    total = q.count()
    branches = (
        q.filter(Branch.is_active.is_(True))
        .order_by(Branch.company_id, Branch.name)
        .offset(offset)
        .limit(limit)
        .all()
    )
    # Per-branch last activity: max(refresh_tokens.issued_at) for users who have access to that branch
    try:
        last_activity_rows = db.execute(
            text("""
                SELECT ubr.branch_id, MAX(rt.issued_at) AS last_activity
                FROM user_branch_roles ubr
                JOIN refresh_tokens rt ON rt.user_id = ubr.user_id
                WHERE rt.issued_at IS NOT NULL
                GROUP BY ubr.branch_id
            """)
        ).fetchall()
        last_activity_by_branch = {str(r[0]): r[1] for r in last_activity_rows}
    except Exception:
        last_activity_by_branch = {}
    rows = []
    for b in branches:
        last_ts = last_activity_by_branch.get(str(b.id))
        if last_ts is None and b.updated_at:
            last_ts = b.updated_at
        rows.append({
            "id": str(b.id),
            "company_id": str(b.company_id),
            "company_name": b.company.name if b.company else None,
            "name": b.name,
            "code": b.code,
            "is_active": b.is_active,
            "last_activity": last_ts.isoformat() if last_ts else None,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        })
    rows.sort(
        key=lambda r: (
            r.get("last_activity") is not None,
            r.get("last_activity") or "",
        ),
        reverse=True,
    )
    return {
        "total": total,
        "branches": rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_active_users_metrics(db: Session) -> Dict[str, Any]:
    """
    Active user counts from refresh_tokens.
    - active_now: distinct user_id with is_active and expires_at > now
    - active_last_24h: distinct user_id with issued_at in last 24h (or token still valid)
    - active_last_7d: distinct user_id with issued_at in last 7d
    """
    try:
        now = datetime.now(timezone.utc)
        r_now = db.execute(
            text(
                """
                SELECT COUNT(DISTINCT user_id) FROM refresh_tokens
                WHERE is_active = TRUE AND expires_at > :now
                """
            ),
            {"now": now},
        ).fetchone()
        active_now = r_now[0] if r_now else 0
        t24 = now - timedelta(hours=24)
        r_24 = db.execute(
            text(
                """
                SELECT COUNT(DISTINCT user_id) FROM refresh_tokens
                WHERE issued_at >= :t24 OR (is_active = TRUE AND expires_at > :now)
                """
            ),
            {"t24": t24, "now": now},
        ).fetchone()
        active_last_24h = r_24[0] if r_24 else 0
        t7d = now - timedelta(days=7)
        r_7d = db.execute(
            text(
                """
                SELECT COUNT(DISTINCT user_id) FROM refresh_tokens
                WHERE issued_at >= :t7d
                """
            ),
            {"t7d": t7d},
        ).fetchone()
        active_last_7d = r_7d[0] if r_7d else 0
    except Exception:
        active_now = active_last_24h = active_last_7d = 0
    return {
        "active_now": active_now,
        "active_last_24h": active_last_24h,
        "active_last_7d": active_last_7d,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_usage_by_company(db: Session) -> List[Dict[str, Any]]:
    """
    Usability measures per company.
    - active_users_now: users with a currently valid refresh token.
    - active_users_7d: users with refresh activity in the last 7 days.
    - login_events_7d / total_login_events: captured platform login events.
    - request_count_24h: API request volume captured by request middleware.
    """
    try:
        rows = db.execute(
            text(
                """
                WITH session_metrics AS (
                    SELECT
                        b.company_id,
                        COUNT(DISTINCT rt.user_id) FILTER (
                            WHERE rt.is_active = TRUE AND rt.expires_at > NOW()
                        ) AS active_users_now,
                        COUNT(DISTINCT rt.user_id) FILTER (
                            WHERE rt.issued_at >= NOW() - INTERVAL '7 days'
                        ) AS active_users_7d,
                        MAX(rt.issued_at) AS last_session_at
                    FROM branches b
                    JOIN user_branch_roles ubr ON ubr.branch_id = b.id
                    JOIN refresh_tokens rt ON rt.user_id = ubr.user_id
                    GROUP BY b.company_id
                ),
                event_metrics AS (
                    SELECT
                        company_id,
                        COUNT(*) FILTER (
                            WHERE event_type = 'user_login'
                              AND created_at >= NOW() - INTERVAL '7 days'
                        ) AS login_events_7d,
                        COUNT(*) FILTER (WHERE event_type = 'user_login') AS total_login_events,
                        MAX(created_at) FILTER (WHERE event_type = 'user_login') AS last_login_event_at
                    FROM platform_usage_events
                    GROUP BY company_id
                ),
                request_metrics AS (
                    SELECT
                        company_id,
                        SUM(request_count) AS request_count_24h,
                        MAX(last_seen_at) AS last_request_at
                    FROM platform_usage_counters
                    WHERE hour_start >= NOW() - INTERVAL '24 hours'
                    GROUP BY company_id
                )
                SELECT
                    c.id AS company_id,
                    c.name AS company_name,
                    COALESCE(sm.active_users_now, 0) AS active_users_now,
                    COALESCE(sm.active_users_7d, 0) AS active_users_7d,
                    COALESCE(em.login_events_7d, 0) AS login_events_7d,
                    COALESCE(em.total_login_events, 0) AS total_login_events,
                    COALESCE(rm.request_count_24h, 0) AS request_count_24h,
                    GREATEST(
                        COALESCE(sm.last_session_at, 'epoch'::timestamptz),
                        COALESCE(em.last_login_event_at, 'epoch'::timestamptz),
                        COALESCE(rm.last_request_at, 'epoch'::timestamptz)
                    ) AS last_seen_at
                FROM companies c
                LEFT JOIN session_metrics sm ON sm.company_id = c.id
                LEFT JOIN event_metrics em ON em.company_id = c.id
                LEFT JOIN request_metrics rm ON rm.company_id = c.id
                ORDER BY last_seen_at DESC NULLS LAST, active_users_7d DESC, request_count_24h DESC, c.name
                """
            )
        ).fetchall()
        return [
            {
                "company_id": str(r[0]),
                "company_name": r[1],
                "active_sessions": r[2] or 0,
                "active_users_now": r[2] or 0,
                "active_users_7d": r[3] or 0,
                "login_events_7d": r[4] or 0,
                "total_login_events": r[5] or 0,
                "request_count_24h": r[6] or 0,
                "last_seen_at": None if not r[7] or str(r[7]).startswith("1970-01-01") else r[7].isoformat(),
            }
            for r in rows
        ]
    except Exception:
        return []


def get_recent_platform_events(db: Session, limit: int = 25) -> Dict[str, Any]:
    """Recent signup/login/user-created events. Metadata only; no client business data."""
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    e.event_type,
                    e.company_id,
                    COALESCE(e.company_name, c.name) AS company_name,
                    e.actor_name,
                    e.actor_email,
                    e.metadata,
                    e.created_at
                FROM platform_usage_events e
                LEFT JOIN companies c ON c.id = e.company_id
                ORDER BY e.created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(int(limit or 25), 100))},
        ).fetchall()
        events = [
            {
                "event_type": r[0],
                "company_id": str(r[1]) if r[1] else None,
                "company_name": r[2],
                "actor_name": r[3],
                "actor_email": r[4],
                "metadata": dict(r[5] or {}),
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
    except Exception:
        events = []
    return {
        "events": events,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_signup_metrics(db: Session, days: int = 30) -> Dict[str, Any]:
    """Client signup and company-user creation counts."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days or 30), 365)))
    try:
        row = db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE event_type = 'client_signup') AS client_signups,
                    COUNT(*) FILTER (WHERE event_type = 'company_user_created') AS users_created,
                    COUNT(DISTINCT company_id) FILTER (WHERE event_type = 'user_login') AS companies_active
                FROM platform_usage_events
                WHERE created_at >= :since
                """
            ),
            {"since": since},
        ).fetchone()
        series_rows = db.execute(
            text(
                """
                SELECT created_at::date AS day, COUNT(*) AS signups
                FROM platform_usage_events
                WHERE event_type = 'client_signup' AND created_at >= :since
                GROUP BY created_at::date
                ORDER BY day
                """
            ),
            {"since": since},
        ).fetchall()
        series = [{"date": str(r[0]), "signups": r[1] or 0} for r in series_rows]
        client_signups = row[0] if row else 0
        users_created = row[1] if row else 0
        companies_active = row[2] if row else 0
    except Exception:
        client_signups = users_created = companies_active = 0
        series = []
    return {
        "days": days,
        "client_signups": client_signups,
        "users_created": users_created,
        "companies_active": companies_active,
        "series": series,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_health(db: Session) -> Dict[str, Any]:
    """
    Basic health: DB connectivity and server time.
    Uptime can be added via app-state start time if needed.
    """
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    return {
        "database_connected": db_ok,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "status": "healthy" if db_ok else "degraded",
    }


def get_active_users_timeseries(db: Session, days: int = 14) -> Dict[str, Any]:
    """
    Daily active users (distinct user_id per day from refresh_tokens.issued_at).
    Source: refresh_tokens. Used for line/area charts.
    """
    try:
        rows = db.execute(
            text(
                """
                SELECT (issued_at AT TIME ZONE 'UTC')::date AS day, COUNT(DISTINCT user_id) AS dau
                FROM refresh_tokens
                WHERE issued_at >= :since
                GROUP BY (issued_at AT TIME ZONE 'UTC')::date
                ORDER BY day
                """
            ),
            {"since": datetime.now(timezone.utc) - timedelta(days=days)},
        ).fetchall()
        series = [{"date": str(r[0]), "active_users": r[1]} for r in rows]
    except Exception:
        series = []
    return {
        "days": days,
        "series": series,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_request_volume(db: Session, hours: int = 24) -> Dict[str, Any]:
    """Aggregated API request volume by hour and company."""
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(int(hours or 24), 24 * 30)))
    try:
        by_hour_rows = db.execute(
            text(
                """
                SELECT hour_start, SUM(request_count) AS requests,
                       SUM(total_duration_ms)::float / NULLIF(SUM(request_count), 0) AS avg_ms
                FROM platform_usage_counters
                WHERE hour_start >= :since
                GROUP BY hour_start
                ORDER BY hour_start
                """
            ),
            {"since": since},
        ).fetchall()
        by_company_rows = db.execute(
            text(
                """
                SELECT c.id, c.name, SUM(p.request_count) AS requests,
                       MAX(p.last_seen_at) AS last_seen_at,
                       SUM(p.total_duration_ms)::float / NULLIF(SUM(p.request_count), 0) AS avg_ms
                FROM platform_usage_counters p
                JOIN companies c ON c.id = p.company_id
                WHERE p.hour_start >= :since
                GROUP BY c.id, c.name
                ORDER BY requests DESC, c.name
                LIMIT 50
                """
            ),
            {"since": since},
        ).fetchall()
        endpoint_rows = db.execute(
            text(
                """
                SELECT endpoint_group, SUM(request_count) AS requests
                FROM platform_usage_counters
                WHERE hour_start >= :since
                GROUP BY endpoint_group
                ORDER BY requests DESC
                LIMIT 12
                """
            ),
            {"since": since},
        ).fetchall()
        by_hour = [
            {
                "hour": r[0].isoformat() if r[0] else None,
                "requests": int(r[1] or 0),
                "avg_response_time_ms": round(float(r[2] or 0), 1),
            }
            for r in by_hour_rows
        ]
        by_company = [
            {
                "company_id": str(r[0]),
                "company_name": r[1],
                "requests": int(r[2] or 0),
                "last_seen_at": r[3].isoformat() if r[3] else None,
                "avg_response_time_ms": round(float(r[4] or 0), 1),
            }
            for r in by_company_rows
        ]
        by_endpoint = [{"endpoint_group": r[0], "requests": int(r[1] or 0)} for r in endpoint_rows]
        total_requests = sum(item["requests"] for item in by_hour)
        avg_response_time_ms = (
            round(sum((item["avg_response_time_ms"] * item["requests"]) for item in by_hour) / total_requests, 1)
            if total_requests
            else None
        )
    except Exception:
        by_hour = []
        by_company = []
        by_endpoint = []
        total_requests = 0
        avg_response_time_ms = None
    return {
        "hours": hours,
        "total_requests": total_requests,
        "avg_response_time_ms": avg_response_time_ms,
        "by_hour": by_hour,
        "by_company": by_company,
        "by_endpoint": by_endpoint,
        "peak_concurrent_users": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
