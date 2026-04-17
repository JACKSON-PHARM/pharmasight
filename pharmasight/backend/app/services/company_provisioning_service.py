"""
Single entry point for creating an app ``Company`` + HQ ``Branch`` + master ``Tenant`` (Option B).

The app DB and master DB may be different physical databases, so this uses:
  1) One committed transaction on ``app_db`` (company + branch + default branch settings).
  2) A committed registry row on ``master_db``.

If step (2) fails after step (1) succeeds, we best-effort delete the new company so callers
are not left with an unregistered organization. (True single-DB two-phase commit is not used.)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.company import Branch, Company
from app.models.tenant import Tenant
from app.services.branch_settings_service import ensure_default_branch_settings
from app.services.tenant_registry_service import (
    create_and_commit_registry_tenant,
    reserve_unique_subdomain,
    slug_base_for_company_name,
)

logger = logging.getLogger(__name__)


@dataclass
class HQBranchSpec:
    name: str = "Head Office"
    code: str = "HQ"
    is_hq: bool = True
    phone: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True


def delete_company_by_id_best_effort(company_id: UUID) -> None:
    """Remove a company (cascades branches) after a failed registry step."""
    app = SessionLocal()
    try:
        c = app.query(Company).filter(Company.id == company_id).first()
        if c:
            app.delete(c)
            app.commit()
    except Exception:
        app.rollback()
        logger.exception("Failed to roll back app company after registry failure: company_id=%s", company_id)
    finally:
        app.close()


def create_company_with_hq_branch_and_registry(
    app_db: Session,
    master_db: Session,
    *,
    company_kwargs: Dict[str, Any],
    admin_email: str,
    hq: Optional[HQBranchSpec] = None,
    admin_full_name: Optional[str] = None,
    tenant_phone: Optional[str] = None,
    tenant_subdomain: Optional[str] = None,
    tenant_subdomain_base: Optional[str] = None,
    tenant_status: str = "trial",
    tenant_plan_type: str = "paid",
) -> Tuple[Company, Branch, Tenant]:
    """
    Create ``Company`` + HQ ``Branch`` on ``app_db``, commit, then create master ``Tenant``.

    ``tenant_subdomain``: caller-reserved unique subdomain (e.g. demo / admin tenant API).
    If omitted, a unique subdomain is allocated from ``tenant_subdomain_base`` or company name.
    """
    hq = hq or HQBranchSpec()
    app_url = (settings.database_connection_string or "").strip()
    if not app_url:
        raise RuntimeError("DATABASE_URL is not configured; cannot create tenant registry row")

    company = Company(**company_kwargs)
    app_db.add(company)
    app_db.flush()

    branch = Branch(
        company_id=company.id,
        name=hq.name,
        code=hq.code,
        address=hq.address,
        phone=hq.phone,
        is_active=hq.is_active,
        is_hq=hq.is_hq,
    )
    app_db.add(branch)
    app_db.flush()
    ensure_default_branch_settings(app_db, branch.id)
    app_db.commit()
    app_db.refresh(company)
    app_db.refresh(branch)

    if tenant_subdomain:
        subdomain = tenant_subdomain[:100]
    else:
        base = tenant_subdomain_base or slug_base_for_company_name(company.name or "organization")
        subdomain = reserve_unique_subdomain(master_db, base, company.id)

    try:
        tenant = create_and_commit_registry_tenant(
            master_db,
            company_id=company.id,
            company_name=company.name or "Organization",
            admin_email=admin_email,
            subdomain=subdomain,
            database_url=app_url,
            database_name=f"pharmasight_{subdomain[:50]}",
            admin_full_name=admin_full_name,
            phone=tenant_phone,
            admin_user_id=None,
            status=tenant_status,
            plan_type=tenant_plan_type,
        )
        return company, branch, tenant
    except Exception:
        delete_company_by_id_best_effort(company.id)
        raise
