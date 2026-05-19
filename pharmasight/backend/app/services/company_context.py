"""
Company org context (single shared DB).

Resolves organization from URL/query/header (`org` / legacy `tenant` subdomain) to
``tenants.company_id`` and scopes user lookup + effective company to that organization.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.company import Branch, Company
from app.models.tenant import Tenant
from app.models.user import User, UserBranchRole

logger = logging.getLogger(__name__)

ORG_SLUG_HEADER = "X-Company-Org"
LEGACY_TENANT_HEADER = "X-Tenant-Subdomain"


def normalize_org_slug(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().lower()
    if not s or s in ("__default__", "default", "null"):
        return None
    if not re.match(r"^[a-z0-9][a-z0-9\-]{0,98}[a-z0-9]$", s) and not re.match(r"^[a-z0-9]{1,100}$", s):
        return None
    return s[:100]


def org_slug_from_request(request: Request) -> Optional[str]:
    """Read org slug from headers, then query string (?org=, ?tenant=, ?subdomain=)."""
    for key in (ORG_SLUG_HEADER, LEGACY_TENANT_HEADER, "X-Company-Slug"):
        v = normalize_org_slug(request.headers.get(key))
        if v:
            return v
    try:
        qp = request.query_params
        for name in ("org", "tenant", "subdomain"):
            v = normalize_org_slug(qp.get(name))
            if v:
                return v
    except Exception:
        pass
    return None


def tenant_for_org_slug(master_db: Session, org_slug: str) -> Optional[Tenant]:
    slug = normalize_org_slug(org_slug)
    if not slug:
        return None
    return (
        master_db.query(Tenant)
        .filter(func.lower(Tenant.subdomain) == slug)
        .first()
    )


def company_ids_for_user(db: Session, user_id: UUID) -> List[UUID]:
    rows = (
        db.query(Branch.company_id)
        .join(UserBranchRole, UserBranchRole.branch_id == Branch.id)
        .filter(UserBranchRole.user_id == user_id)
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r and r[0]]


def user_has_company_access(db: Session, user_id: UUID, company_id: UUID) -> bool:
    return company_id in company_ids_for_user(db, user_id)


def find_user_for_company_login(
    db: Session,
    normalized_username: str,
    check_email: bool,
    company_id: UUID,
) -> Optional[User]:
    """Find active user by username/email only if assigned to a branch in ``company_id``."""
    base = (
        db.query(User)
        .join(UserBranchRole, UserBranchRole.user_id == User.id)
        .join(Branch, Branch.id == UserBranchRole.branch_id)
        .filter(
            Branch.company_id == company_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    user = base.filter(func.lower(func.trim(User.username)) == normalized_username).first()
    if not user and check_email:
        user = base.filter(func.lower(func.trim(User.email)) == normalized_username).first()
    return user


def get_effective_company_id_for_user(
    db: Session,
    user: User,
    *,
    preferred_company_id: Optional[UUID] = None,
) -> Optional[UUID]:
    """
    Resolve company for an authenticated user.

    Priority: explicit preferred (org context / JWT) when user has branch access;
    sole assigned company; legacy single-company database only.
    Does not return an arbitrary first company when multiple orgs exist.
    """
    assigned = company_ids_for_user(db, user.id)
    if preferred_company_id:
        pref = UUID(str(preferred_company_id)) if not isinstance(preferred_company_id, UUID) else preferred_company_id
        if pref in assigned:
            return pref
    if len(assigned) == 1:
        return assigned[0]
    if len(assigned) > 1:
        if preferred_company_id:
            pref = UUID(str(preferred_company_id)) if not isinstance(preferred_company_id, UUID) else preferred_company_id
            if pref in assigned:
                return pref
        return assigned[0]
    total = db.query(Company.id).count()
    if total == 1:
        row = db.query(Company.id).first()
        return row[0] if row else None
    return None


def preferred_company_id_from_request(request: Request, master_db: Session) -> Optional[UUID]:
    slug = org_slug_from_request(request)
    if not slug:
        return None
    tenant = tenant_for_org_slug(master_db, slug)
    if tenant and tenant.company_id:
        return tenant.company_id
    return None


def build_org_login_url(org_slug: str, *, base_url: Optional[str] = None) -> str:
    base = (base_url or settings.effective_erp_app_url or "").strip().rstrip("/")
    slug = normalize_org_slug(org_slug) or ""
    if not slug:
        return f"{base}/app#login" if base else "/app#login"
    if not base:
        return f"/app?org={slug}#login"
    return f"{base}/app?org={slug}#login"


def enrich_company_payload_with_org_context(
    company_payload: dict,
    master_db: Session,
    *,
    base_url: Optional[str] = None,
) -> dict:
    """
    Attach tenant subdomain + shareable ERP login URL for admin UI and emails.
    """
    company_id = company_payload.get("id")
    if not company_id:
        company_payload.setdefault("tenant_subdomain", None)
        company_payload.setdefault("org_slug", None)
        company_payload.setdefault("org_login_url", None)
        return company_payload
    try:
        cid = company_id if isinstance(company_id, UUID) else UUID(str(company_id))
    except (TypeError, ValueError):
        company_payload["tenant_subdomain"] = None
        company_payload["org_slug"] = None
        company_payload["org_login_url"] = None
        return company_payload

    tenant = master_db.query(Tenant).filter(Tenant.company_id == cid).first()
    if tenant and tenant.subdomain:
        slug = normalize_org_slug(tenant.subdomain) or str(tenant.subdomain).strip().lower()
        company_payload["tenant_subdomain"] = slug
        company_payload["org_slug"] = slug
        company_payload["org_login_url"] = build_org_login_url(slug, base_url=base_url)
    else:
        company_payload["tenant_subdomain"] = None
        company_payload["org_slug"] = None
        company_payload["org_login_url"] = None
    return company_payload


def org_bootstrap_payload(tenant: Tenant, company: Optional[Company]) -> dict:
    slug = normalize_org_slug(tenant.subdomain) or tenant.subdomain
    return {
        "org_slug": slug,
        "company_id": str(tenant.company_id) if tenant.company_id else None,
        "company_name": (company.name if company else None) or tenant.name,
        "login_url": build_org_login_url(slug),
    }
