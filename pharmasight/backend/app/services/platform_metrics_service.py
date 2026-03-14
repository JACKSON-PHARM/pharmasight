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
    last_activity: not stored in schema; returned as null (extend with activity_log table later).
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
    rows = []
    for b in branches:
        rows.append({
            "id": str(b.id),
            "company_id": str(b.company_id),
            "company_name": b.company.name if b.company else None,
            "name": b.name,
            "code": b.code,
            "is_active": b.is_active,
            "last_activity": None,  # No activity log in schema; add migration + logging to populate
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        })
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
    Sessions (active refresh tokens) per company.
    Join refresh_tokens -> user_branch_roles -> branches -> company.
    """
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    c.id AS company_id,
                    c.name AS company_name,
                    COUNT(DISTINCT rt.user_id) AS active_sessions,
                    COUNT(rt.id) AS total_token_count
                FROM companies c
                LEFT JOIN branches b ON b.company_id = c.id AND b.is_active = TRUE
                LEFT JOIN user_branch_roles ubr ON ubr.branch_id = b.id
                LEFT JOIN refresh_tokens rt ON rt.user_id = ubr.user_id
                    AND rt.is_active = TRUE AND rt.expires_at > NOW()
                GROUP BY c.id, c.name
                ORDER BY active_sessions DESC, c.name
                """
            )
        ).fetchall()
        return [
            {
                "company_id": str(r[0]),
                "company_name": r[1],
                "active_sessions": r[2] or 0,
                "total_token_count": r[3] or 0,
            }
            for r in rows
        ]
    except Exception:
        return []


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
