"""
Admin Platform Licensing API.

These endpoints are intended for `admin.html` platform operators authenticated via `/api/admin/auth/login`
admin_token. This is separate from the RBAC-gated `/api/platform-admin/*` routes, which require an app user
with `platform_super_admin`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database_master import get_master_db
from app.dependencies import get_current_admin, get_tenant_db
from app.config import is_supabase_owner_email, settings
from app.models.company import Company
from app.models.tenant import Tenant
from app.models.company import Branch, BranchEtimsCredentials
from app.models.company_module import CompanyModule
from app.module_enforcement import get_company_module_license_catalog
from app.utils.company_plan_limits import (
    company_branch_limit,
    company_product_limit,
    company_trial_expires_effective,
    company_user_limit,
    sync_demo_plan_slug_with_subscription_status,
)
from app.module_metadata import get_core_modules
from app.services.etims.branch_credentials import effective_etims_environment, get_cmc_key_plain, get_oauth_username_password
from app.services.etims.constants import SELECT_INIT_OSDC_PATH
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials, find_etims_result_cd
from app.services.etims.etims_oauth_client import get_access_token
from app.schemas.tenant import TenantInviteCreate, TenantInviteResponse
from app.services.tenant_invite_service import create_tenant_invite, list_tenant_invites

import requests

router = APIRouter(prefix="/platform-licensing", tags=["Platform Licensing (Admin)"])
logger = logging.getLogger(__name__)


class PlatformCompanyResponse(BaseModel):
    id: UUID
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    portal_upgrade_whatsapp: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    is_active: bool = True
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    trial_expires_at: Optional[datetime] = None
    product_limit: Optional[int] = None
    branch_limit: Optional[int] = None
    user_limit: Optional[int] = None

    class Config:
        from_attributes = True


class PlatformCompanyListItem(PlatformCompanyResponse):
    """List row: includes inferred trial end for demo when ``trial_expires_at`` was never persisted."""

    trial_display_expires_at: Optional[datetime] = None


class ModuleToggle(BaseModel):
    name: str = Field(..., min_length=1)
    enabled: bool


class PatchCompanyModulesRequest(BaseModel):
    modules: List[ModuleToggle] = Field(default_factory=list)


class PatchCompanySubscriptionRequest(BaseModel):
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    trial_expires_at: Optional[datetime] = None
    product_limit: Optional[int] = None
    branch_limit: Optional[int] = None
    user_limit: Optional[int] = None


class PatchCompanyStatusRequest(BaseModel):
    is_active: bool


class PatchCompanyProfileRequest(BaseModel):
    """Update company + matching tenant registry contact (single-DB)."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    admin_full_name: Optional[str] = Field(None, max_length=255)
    portal_upgrade_whatsapp: Optional[str] = Field(
        None,
        max_length=32,
        description="WhatsApp for marketing portal upgrade CTA (digits or local e.g. 07…); empty clears.",
    )


class CreatePlatformCompanyRequest(BaseModel):
    """Provision a new organization on the shared app DB + tenant registry (single-DB)."""

    name: str = Field(..., min_length=1, max_length=255, description="Legal / display company name")
    admin_email: EmailStr = Field(..., description="Primary contact; used on tenant registry row")
    admin_full_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    currency: str = Field(default="KES", max_length=10)
    timezone: str = Field(default="Africa/Nairobi", max_length=50)
    hq_branch_name: str = Field(default="Head Office", max_length=255)
    hq_branch_code: str = Field(default="HQ", max_length=50)
    tenant_subdomain: Optional[str] = Field(
        None,
        max_length=100,
        description="Optional URL slug; must be unique. If omitted, a slug is generated from the company name.",
    )
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    trial_expires_at: Optional[datetime] = None
    product_limit: Optional[int] = None
    branch_limit: Optional[int] = None
    user_limit: Optional[int] = None


class PlatformEtimsBranchRow(BaseModel):
    branch_id: UUID
    branch_name: str
    branch_code: Optional[str] = None
    environment: str = "sandbox"
    enabled: bool = False
    connection_status: str = "not_configured"
    last_tested_at: Optional[datetime] = None
    kra_bhf_id: Optional[str] = None
    device_serial: Optional[str] = None
    has_cmc_key: bool = False
    has_oauth_config: bool = False


class PlatformEtimsCompanyResponse(BaseModel):
    company_id: UUID
    company_name: str
    company_pin: Optional[str] = None
    branches: List[PlatformEtimsBranchRow] = Field(default_factory=list)


class PatchCompanyPinRequest(BaseModel):
    pin: Optional[str] = None


class PatchBranchEtimsRequest(BaseModel):
    kra_bhf_id: Optional[str] = None
    device_serial: Optional[str] = None
    cmc_key: Optional[str] = None
    environment: Optional[str] = None
    enabled: Optional[bool] = None


def _norm_env(v: Optional[str]) -> str:
    e = (v or "sandbox").strip().lower()
    if e not in ("sandbox", "production"):
        raise HTTPException(status_code=400, detail="environment must be sandbox or production")
    return e


def _test_http_success(r: requests.Response, parsed: Optional[dict]) -> bool:
    if not (200 <= r.status_code < 300):
        return False
    if not isinstance(parsed, dict):
        return True
    rc = find_etims_result_cd(parsed)
    if rc is None:
        return True
    return rc == "000"


@router.get("/companies", response_model=List[PlatformCompanyListItem])
def list_companies(
    q: Optional[str] = Query(None),
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    query = db.query(Company)
    if q and str(q).strip():
        term = f"%{str(q).strip()}%"
        query = query.filter(Company.name.ilike(term))
    rows = query.order_by(Company.created_at.desc()).limit(1000).all()
    out: List[PlatformCompanyListItem] = []
    for c in rows:
        base = PlatformCompanyResponse.model_validate(c).model_dump()
        base["trial_display_expires_at"] = company_trial_expires_effective(c)
        out.append(PlatformCompanyListItem(**base))
    return out


@router.post("/companies", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_platform_company(
    request: Request,
    background_tasks: BackgroundTasks,
    body: CreatePlatformCompanyRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """
    Create a new client company: ``Company`` + HQ ``Branch`` + ``tenants`` registry row.

    Does **not** create a login user. Use **Tenant invites** (``POST /api/admin/platform-licensing/tenants/{tenant_id}/invites``)
    or your public signup flow so the client can set a password and receive branch access.
    """
    from app.services.company_provisioning_service import HQBranchSpec, create_company_with_hq_branch_and_registry

    email_norm = str(body.admin_email).strip().lower()
    if is_supabase_owner_email(email_norm):
        raise HTTPException(
            status_code=400,
            detail="This email is reserved (Supabase owner). Use a different admin contact email.",
        )
    existing_tenant = master_db.query(Tenant).filter(func.lower(Tenant.admin_email) == email_norm).first()
    if existing_tenant:
        raise HTTPException(
            status_code=409,
            detail="A tenant registry row already uses this admin email. Use another email or manage the existing company.",
        )

    sub_raw = (body.tenant_subdomain or "").strip().lower()
    if sub_raw:
        if len(sub_raw) > 100:
            raise HTTPException(status_code=400, detail="tenant_subdomain is too long (max 100).")
        taken = master_db.query(Tenant).filter(Tenant.subdomain == sub_raw).first()
        if taken:
            raise HTTPException(status_code=409, detail="That subdomain is already in use.")

    company_kwargs: Dict[str, Any] = {
        "name": body.name.strip(),
        "currency": (body.currency or "KES").strip() or "KES",
        "timezone": (body.timezone or "Africa/Nairobi").strip() or "Africa/Nairobi",
        "is_active": True,
        "email": email_norm,
    }
    if body.phone and str(body.phone).strip():
        company_kwargs["phone"] = str(body.phone).strip()[:50]
    for key in (
        "subscription_plan",
        "subscription_status",
        "trial_expires_at",
        "product_limit",
        "branch_limit",
        "user_limit",
    ):
        val = getattr(body, key, None)
        if val is not None:
            if key in ("subscription_plan", "subscription_status") and isinstance(val, str):
                company_kwargs[key] = val.strip() or None
            else:
                company_kwargs[key] = val

    plan_slug = (company_kwargs.get("subscription_plan") or "").strip().lower()
    if plan_slug == "demo" and company_kwargs.get("trial_expires_at") is None:
        demo_days = int(getattr(settings, "DEMO_DURATION_DAYS", 7) or 7)
        company_kwargs["trial_expires_at"] = datetime.now(timezone.utc) + timedelta(days=demo_days)

    hq = HQBranchSpec(
        name=(body.hq_branch_name or "Head Office").strip()[:255] or "Head Office",
        code=(body.hq_branch_code or "HQ").strip()[:50] or "HQ",
    )

    try:
        company, branch, tenant = create_company_with_hq_branch_and_registry(
            db,
            master_db,
            company_kwargs=company_kwargs,
            admin_email=email_norm,
            hq=hq,
            admin_full_name=(body.admin_full_name or "").strip() or None,
            tenant_phone=(body.phone or "").strip() or None,
            tenant_subdomain=sub_raw if sub_raw else None,
            tenant_status="trial",
            tenant_plan_type="paid",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Provisioning failed: {e}") from e

    sync_demo_plan_slug_with_subscription_status(company)
    db.add(company)
    db.commit()
    db.refresh(company)

    initial_invite: Optional[TenantInviteResponse] = None
    invite_warning: Optional[str] = None
    try:
        initial_invite = create_tenant_invite(
            tenant_id=tenant.id,
            invite_data=TenantInviteCreate(expires_in_days=7, send_email=True),
            db=master_db,
            request=request,
            background_tasks=background_tasks,
        )
    except HTTPException as he:
        invite_warning = str(he.detail)
        logger.warning("Auto-invite failed after company create: %s", invite_warning)
    except Exception:
        logger.exception("Auto-invite failed after company create")
        invite_warning = "Invite could not be created; use Manage → resend invite."

    return {
        "company": PlatformCompanyResponse.model_validate(company).model_dump(),
        "tenant_id": str(tenant.id),
        "subdomain": tenant.subdomain,
        "hq_branch_id": str(branch.id),
        "initial_invite": initial_invite.model_dump() if initial_invite else None,
        "invite_warning": invite_warning,
        "invite_hint": (
            f"Create an invite for this tenant: POST /api/admin/platform-licensing/tenants/{tenant.id}/invites "
            "(same admin session) so the client can complete signup."
        ),
    }


@router.post("/tenants/{tenant_id}/invites", response_model=TenantInviteResponse, status_code=status.HTTP_201_CREATED)
def licensing_create_tenant_invite(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    invite_data: TenantInviteCreate,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """
    Create a setup invite for a tenant registry row (same logic as legacy ``/api/admin/tenants/.../invites``).

    Exposed under platform-licensing so ``admin.html`` works when ``ENABLE_TENANT_ADMIN`` is not set.
    """
    return create_tenant_invite(
        tenant_id=tenant_id,
        invite_data=invite_data,
        db=db,
        request=request,
        background_tasks=background_tasks,
    )


@router.get("/tenants/{tenant_id}/invites", response_model=List[TenantInviteResponse])
def licensing_list_tenant_invites(
    tenant_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    return list_tenant_invites(tenant_id=tenant_id, db=db)


@router.get("/company/{company_id}", response_model=Dict[str, Any])
def get_company(
    company_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    rows = (
        db.query(CompanyModule)
        .filter(CompanyModule.company_id == company_id)
        .order_by(CompanyModule.module_name.asc())
        .all()
    )
    company_payload = PlatformCompanyResponse.model_validate(c).model_dump()
    # What enforcement uses (demo + NULL columns → platform demo defaults).
    company_payload["resolved_user_limit"] = company_user_limit(c)
    company_payload["resolved_branch_limit"] = company_branch_limit(c)
    company_payload["resolved_product_limit"] = company_product_limit(c)
    company_payload["trial_display_expires_at"] = company_trial_expires_effective(c)
    tenant = master_db.query(Tenant).filter(Tenant.company_id == company_id).first()
    if tenant:
        company_payload["tenant_id"] = str(tenant.id)
        company_payload["tenant_subdomain"] = tenant.subdomain
        company_payload["tenant_admin_full_name"] = tenant.admin_full_name
    else:
        company_payload["tenant_id"] = None
        company_payload["tenant_subdomain"] = None
        company_payload["tenant_admin_full_name"] = None
    return {
        "company": company_payload,
        "modules": [{"name": r.module_name, "enabled": bool(r.is_enabled)} for r in rows],
        "module_catalog": get_company_module_license_catalog(db, company_id),
        "core_modules": sorted(list(get_core_modules(db))),
    }


@router.patch("/company/{company_id}/profile", response_model=Dict[str, Any])
def patch_company_profile(
    company_id: UUID,
    body: PatchCompanyProfileRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    tenant = master_db.query(Tenant).filter(Tenant.company_id == company_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant registry row not found for this company")

    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        nm = str(data["name"]).strip()
        if not nm:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        c.name = nm[:255]
        tenant.name = nm[:255]
    if "email" in data and data["email"] is not None:
        new_email = str(data["email"]).strip().lower()
        if is_supabase_owner_email(new_email):
            raise HTTPException(status_code=400, detail="This email is reserved. Use a different contact email.")
        if new_email != (tenant.admin_email or "").lower():
            taken = (
                master_db.query(Tenant)
                .filter(func.lower(Tenant.admin_email) == new_email, Tenant.id != tenant.id)
                .first()
            )
            if taken:
                raise HTTPException(
                    status_code=409,
                    detail="That admin email is already used by another tenant.",
                )
        c.email = new_email
        tenant.admin_email = new_email
    if "phone" in data:
        ph = data["phone"]
        if ph is None or str(ph).strip() == "":
            c.phone = None
            tenant.phone = None
        else:
            phs = str(ph).strip()[:50]
            c.phone = phs
            tenant.phone = phs
    if "admin_full_name" in data:
        afn = data["admin_full_name"]
        tenant.admin_full_name = (str(afn).strip()[:255] if afn else None)
    if "portal_upgrade_whatsapp" in data:
        wa = data["portal_upgrade_whatsapp"]
        if wa is None or str(wa).strip() == "":
            c.portal_upgrade_whatsapp = None
        else:
            c.portal_upgrade_whatsapp = str(wa).strip()[:32]

    db.commit()
    master_db.commit()
    db.refresh(c)
    master_db.refresh(tenant)

    company_payload = PlatformCompanyResponse.model_validate(c).model_dump()
    company_payload["resolved_user_limit"] = company_user_limit(c)
    company_payload["resolved_branch_limit"] = company_branch_limit(c)
    company_payload["resolved_product_limit"] = company_product_limit(c)
    company_payload["trial_display_expires_at"] = company_trial_expires_effective(c)
    company_payload["tenant_id"] = str(tenant.id)
    company_payload["tenant_subdomain"] = tenant.subdomain
    company_payload["tenant_admin_full_name"] = tenant.admin_full_name
    return {"company": company_payload}


@router.patch("/company/{company_id}/modules", response_model=Dict[str, Any])
def patch_company_modules(
    company_id: UUID,
    body: PatchCompanyModulesRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    core = {m.lower() for m in get_core_modules(db)}
    changes = 0
    ignored_core = []

    for t in body.modules:
        name = (t.name or "").strip().lower()
        if not name:
            continue
        if name in core:
            ignored_core.append(name)
            continue
        row = (
            db.query(CompanyModule)
            .filter(CompanyModule.company_id == company_id, CompanyModule.module_name == name)
            .first()
        )
        if row is None:
            row = CompanyModule(company_id=company_id, module_name=name, is_enabled=bool(t.enabled))
            db.add(row)
            changes += 1
        else:
            new_val = bool(t.enabled)
            if bool(row.is_enabled) != new_val:
                row.is_enabled = new_val
                changes += 1

    db.commit()
    return {"success": True, "changed": changes, "ignored_core": ignored_core}


@router.patch("/company/{company_id}/subscription", response_model=PlatformCompanyResponse)
def patch_company_subscription(
    company_id: UUID,
    body: PatchCompanySubscriptionRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    upd = body.model_dump(exclude_unset=True)
    for key in ("subscription_plan", "subscription_status", "trial_expires_at", "product_limit", "branch_limit", "user_limit"):
        if key in upd:
            setattr(c, key, upd[key])
    sync_demo_plan_slug_with_subscription_status(c)
    db.commit()
    db.refresh(c)
    return c


@router.patch("/company/{company_id}/status", response_model=PlatformCompanyResponse)
def patch_company_status(
    company_id: UUID,
    body: PatchCompanyStatusRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    c.is_active = bool(body.is_active)
    db.commit()
    db.refresh(c)
    return c


@router.get("/company/{company_id}/etims", response_model=PlatformEtimsCompanyResponse)
def admin_get_company_etims(
    company_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    branches = db.query(Branch).filter(Branch.company_id == company_id).order_by(Branch.name.asc()).all()
    out_rows: List[PlatformEtimsBranchRow] = []
    for b in branches:
        creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == b.id).first()
        if not creds:
            out_rows.append(
                PlatformEtimsBranchRow(
                    branch_id=b.id,
                    branch_name=b.name,
                    branch_code=b.code,
                )
            )
            continue
        u, p = get_oauth_username_password(creds)
        out_rows.append(
            PlatformEtimsBranchRow(
                branch_id=b.id,
                branch_name=b.name,
                branch_code=b.code,
                environment=effective_etims_environment(creds),
                enabled=bool(creds.enabled),
                connection_status=creds.connection_status or "not_configured",
                last_tested_at=creds.last_tested_at,
                kra_bhf_id=creds.kra_bhf_id,
                device_serial=creds.device_serial,
                has_cmc_key=bool(get_cmc_key_plain(creds)),
                has_oauth_config=bool(u and p),
            )
        )
    return PlatformEtimsCompanyResponse(
        company_id=c.id,
        company_name=c.name,
        company_pin=c.pin,
        branches=out_rows,
    )


@router.patch("/company/{company_id}/etims/pin", response_model=PlatformEtimsCompanyResponse)
def admin_patch_company_pin(
    company_id: UUID,
    body: PatchCompanyPinRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    c.pin = (body.pin or "").strip() or None
    db.commit()
    return admin_get_company_etims(company_id, _admin=_admin, db=db)


@router.patch("/branch/{branch_id}/etims", response_model=PlatformEtimsBranchRow)
def admin_patch_branch_etims(
    branch_id: UUID,
    body: PatchBranchEtimsRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch_id).first()
    if not creds:
        creds = BranchEtimsCredentials(branch_id=branch_id, company_id=branch.company_id, environment="sandbox", enabled=False)
        db.add(creds)

    if body.kra_bhf_id is not None:
        creds.kra_bhf_id = (body.kra_bhf_id or "").strip() or None
    if body.device_serial is not None:
        creds.device_serial = (body.device_serial or "").strip() or None
    if body.cmc_key is not None:
        # write-only; never returned
        v = (body.cmc_key or "").strip()
        if v:
            creds.cmc_key_encrypted = v
    if body.environment is not None:
        creds.environment = _norm_env(body.environment)
    if body.enabled is not None:
        if body.enabled and (creds.connection_status or "") != "verified":
            raise HTTPException(status_code=400, detail="Branch must be VERIFIED before enabling submission.")
        creds.enabled = bool(body.enabled)

    db.commit()
    db.refresh(creds)
    u, p = get_oauth_username_password(creds)
    return PlatformEtimsBranchRow(
        branch_id=branch.id,
        branch_name=branch.name,
        branch_code=branch.code,
        environment=effective_etims_environment(creds),
        enabled=bool(creds.enabled),
        connection_status=creds.connection_status or "not_configured",
        last_tested_at=creds.last_tested_at,
        kra_bhf_id=creds.kra_bhf_id,
        device_serial=creds.device_serial,
        has_cmc_key=bool(get_cmc_key_plain(creds)),
        has_oauth_config=bool(u and p),
    )


@router.post("/branch/{branch_id}/etims/test-connection", response_model=Dict[str, Any])
def admin_test_branch_etims_connection(
    branch_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch_id).first()
    if not creds:
        raise HTTPException(status_code=400, detail="No branch_etims_credentials row. Save branch eTIMS fields first.")
    company = db.query(Company).filter(Company.id == branch.company_id).first()
    tin = (company.pin or "").strip() if company else ""
    if not tin:
        raise HTTPException(status_code=400, detail="Company PIN (TIN) is not configured.")
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        raise HTTPException(status_code=400, detail="Branch kra_bhf_id is not configured.")
    if not (creds.device_serial and str(creds.device_serial).strip()):
        raise HTTPException(status_code=400, detail="Branch device_serial is not configured.")
    cmc = get_cmc_key_plain(creds)
    if not cmc:
        raise HTTPException(status_code=400, detail="Branch CMC key is not configured.")
    u, p = get_oauth_username_password(creds)
    if not u or not p:
        raise HTTPException(status_code=400, detail="OAuth is not configured on server for eTIMS (ETIMS_APP_CONSUMER_*).")

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    now = datetime.now(timezone.utc)
    try:
        token = get_access_token(api_base=base, username=u, password=p, timeout=45, environment=env_eff)
    except Exception as e:
        creds.connection_status = "failed"
        creds.last_tested_at = now
        db.commit()
        raise HTTPException(status_code=502, detail=f"eTIMS OAuth failed: {e}") from e

    bhf = str(creds.kra_bhf_id).strip()
    dvc = str(creds.device_serial).strip()
    url = f"{base}{SELECT_INIT_OSDC_PATH}"
    body = {"tin": tin, "bhfId": bhf, "dvcSrlNo": dvc}
    try:
        r = requests.post(
            url,
            json=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "tin": tin,
                "bhfId": bhf,
                "cmcKey": cmc,
            },
            timeout=45,
        )
    except requests.RequestException as e:
        creds.connection_status = "failed"
        creds.last_tested_at = now
        db.commit()
        raise HTTPException(status_code=502, detail=f"eTIMS request failed: {e}") from e

    text = (r.text or "")[:8000]
    parsed: Optional[dict] = None
    try:
        parsed = r.json()
    except Exception:
        parsed = None

    ok = _test_http_success(r, parsed)
    creds.connection_status = "verified" if ok else "failed"
    creds.last_tested_at = now
    db.commit()

    return {
        "success": ok,
        "status_code": r.status_code,
        "connection_status": creds.connection_status,
        "environment": env_eff,
        "response_text": text,
        "response": parsed,
    }

