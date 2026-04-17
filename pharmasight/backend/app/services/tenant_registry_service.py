"""
Infra tenant registry (master ``tenants``) kept in sync with ``companies.id`` (Option B).

- ``create_and_commit_registry_tenant`` / ``reserve_unique_subdomain``: used when provisioning
  new organizations (same code path as demo, admin tenant create, onboarding).
- ``ensure_tenant_row_for_company``: repairs legacy rows where ``companies`` exists without ``tenants``.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.company import Company
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


def slug_base_for_company_name(name: str) -> str:
    s = (name or "organization").strip().lower()
    s = re.sub(r"[^a-z0-9\-_]+", "-", s).strip("-")
    return (s[:42] if s else "org") or "org"


def reserve_unique_subdomain(master_db: Session, base_slug: str, company_id: UUID) -> str:
    """Return a ``tenants.subdomain`` value not yet used on ``master_db`` (stable suffix from company id)."""
    base = (base_slug or "org").strip().lower()[:50] or "org"
    suffix = str(company_id).replace("-", "")[:10]
    candidate = f"{base}-{suffix}"[:100]
    n = 0
    while master_db.query(Tenant).filter(Tenant.subdomain == candidate).first():
        n += 1
        candidate = f"{base}-{suffix}-{n}"[:100]
    return candidate


def create_and_commit_registry_tenant(
    master_db: Session,
    *,
    company_id: UUID,
    company_name: str,
    admin_email: str,
    subdomain: str,
    database_url: str,
    database_name: Optional[str] = None,
    admin_full_name: Optional[str] = None,
    phone: Optional[str] = None,
    admin_user_id: Optional[UUID] = None,
    status: str = "trial",
    plan_type: str = "paid",
    is_provisioned: bool = True,
    provisioned_at: Optional[datetime] = None,
) -> Tenant:
    """
    Insert (or return existing) master ``Tenant`` for ``company_id`` and **commit** ``master_db``.

    Idempotent on ``company_id``. Retries on subdomain ``IntegrityError``.
    """
    existing = master_db.query(Tenant).filter(Tenant.company_id == company_id).first()
    if existing:
        return existing

    admin_email_norm = (admin_email or "").strip() or f"registry+{company_id}@internal.pharmasight.invalid"
    if len(admin_email_norm) > 255:
        admin_email_norm = admin_email_norm[:255]

    prov_at = provisioned_at if provisioned_at is not None else datetime.now(timezone.utc)
    db_name = database_name or f"pharmasight_{subdomain[:50]}"

    tenant = Tenant(
        company_id=company_id,
        name=(company_name or "Organization")[:255],
        subdomain=subdomain[:100],
        admin_email=admin_email_norm,
        admin_full_name=admin_full_name,
        phone=phone,
        admin_user_id=admin_user_id,
        database_name=db_name,
        database_url=database_url,
        is_provisioned=is_provisioned,
        provisioned_at=prov_at if is_provisioned else None,
        status=status,
        plan_type=plan_type,
    )

    def _commit_one(t: Tenant) -> Tenant:
        master_db.add(t)
        master_db.commit()
        master_db.refresh(t)
        return t

    try:
        out = _commit_one(tenant)
        logger.info(
            "Created tenant registry row: tenant_id=%s company_id=%s subdomain=%s",
            out.id,
            company_id,
            out.subdomain,
        )
        return out
    except IntegrityError:
        master_db.rollback()
        again = master_db.query(Tenant).filter(Tenant.company_id == company_id).first()
        if again:
            return again
        base = slug_base_for_company_name(company_name)
        fallback_sub = f"{base}-{uuid.uuid4().hex[:12]}"[:100]
        tenant2 = Tenant(
            company_id=company_id,
            name=(company_name or "Organization")[:255],
            subdomain=fallback_sub,
            admin_email=admin_email_norm,
            admin_full_name=admin_full_name,
            phone=phone,
            admin_user_id=admin_user_id,
            database_name=database_name or f"pharmasight_{fallback_sub[:50]}",
            database_url=database_url,
            is_provisioned=is_provisioned,
            provisioned_at=prov_at if is_provisioned else None,
            status=status,
            plan_type=plan_type,
        )
        out = _commit_one(tenant2)
        logger.warning(
            "Created tenant registry row after subdomain collision retry: tenant_id=%s company_id=%s",
            out.id,
            company_id,
        )
        return out


def ensure_tenant_row_for_company(master_db: Session, company_id: UUID) -> Tenant:
    """
    Return the tenant row for ``company_id``, creating a minimal registry row if missing.

    - Idempotent and safe under concurrency (unique violations → re-select).
    - Commits on ``master_db`` when a new row is inserted so subsequent requests see it.
    """
    existing = master_db.query(Tenant).filter(Tenant.company_id == company_id).first()
    if existing:
        return existing

    app_db = SessionLocal()
    try:
        company = app_db.query(Company).filter(Company.id == company_id).first()
    finally:
        app_db.close()

    if company is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    app_url = (settings.database_connection_string or "").strip()
    if not app_url:
        raise RuntimeError("DATABASE_URL is not configured; cannot provision tenant registry row")

    base = slug_base_for_company_name(company.name or "organization")
    subdomain = reserve_unique_subdomain(master_db, base, company_id)

    tenant = create_and_commit_registry_tenant(
        master_db,
        company_id=company_id,
        company_name=company.name or "Organization",
        admin_email=(company.email or "").strip() or f"registry+{company_id}@internal.pharmasight.invalid",
        subdomain=subdomain,
        database_url=app_url,
        database_name=f"pharmasight_{subdomain[:50]}",
        status="active",
    )
    logger.info(
        "Linked master tenant registry to existing company: tenant_id=%s company_id=%s subdomain=%s",
        tenant.id,
        company_id,
        tenant.subdomain,
    )
    return tenant


# Back-compat for imports that used the private name
_slug_base = slug_base_for_company_name
