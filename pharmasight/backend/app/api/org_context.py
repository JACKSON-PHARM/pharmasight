"""Public organization context (org slug → company) for login URLs."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.database_master import get_master_db
from app.models.company import Company
from app.services.company_context import org_bootstrap_payload, tenant_for_org_slug
from app.services.tenant_registry_service import ensure_tenant_row_for_company

router = APIRouter()


@router.get("/org/{org_slug}/bootstrap")
def org_bootstrap(org_slug: str, master_db: Session = Depends(get_master_db)):
    """
    Resolve organization login context from ``tenants.subdomain`` (no auth).

    Used by the SPA before login and for shareable org URLs: ``/app?org=<slug>#login``.
    """
    tenant = tenant_for_org_slug(master_db, org_slug)
    if not tenant or not tenant.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    app_db = SessionLocal()
    try:
        company = app_db.query(Company).filter(Company.id == tenant.company_id).first()
        if not company:
            tenant = ensure_tenant_row_for_company(master_db, UUID(str(tenant.company_id)))
            company = app_db.query(Company).filter(Company.id == tenant.company_id).first()
        return org_bootstrap_payload(tenant, company)
    finally:
        app_db.close()
