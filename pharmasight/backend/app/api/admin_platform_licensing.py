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
from app.api.platform_etims_common import (
    PatchBranchEtimsRequest,
    PatchCompanyPinRequest,
    PlatformEtimsBranchRow,
    PlatformEtimsCompanyResponse,
    branch_etims_credential_material_changed,
    branch_etims_row,
    company_etims_profile_labels,
    invalidate_branch_etims_verification,
    norm_etims_env,
    norm_etims_solution,
    norm_kra_mode,
)
from app.models.company import Company
from app.models.tenant import Tenant
from app.models.company import Branch, BranchEtimsCredentials
from app.models.company_kra_profile import CompanyKraProfile
from app.services.etims.kra_profile_service import KraProfileService
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
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials
from app.services.etims.etims_oauth_client import get_access_token
from app.services.etims.credential_crypto import encrypt_secret
from app.services.etims.select_init_osdc_client import (
    post_select_init_osdc_info_with_retries,
    summarize_select_init_probe,
)
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
    trader_name, has_int = company_etims_profile_labels(db, company_id)
    branches = db.query(Branch).filter(Branch.company_id == company_id).order_by(Branch.name.asc()).all()
    out_rows: List[PlatformEtimsBranchRow] = []
    for b in branches:
        creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == b.id).first()
        out_rows.append(branch_etims_row(b, creds))
    return PlatformEtimsCompanyResponse(
        company_id=c.id,
        company_name=c.name,
        company_pin=c.pin,
        trader_invoicing_system_name=trader_name,
        has_company_integrator_pin=has_int,
        kra_enabled=bool(getattr(c, "kra_enabled", False)),
        kra_mode=(getattr(c, "kra_mode", None) or "sandbox"),
        kra_onboarded_at=getattr(c, "kra_onboarded_at", None),
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
    data = body.model_dump(exclude_unset=True)
    if "pin" in data:
        c.pin = (body.pin or "").strip() or None
    prof: Optional[CompanyKraProfile] = None

    def _prof() -> CompanyKraProfile:
        nonlocal prof
        if prof is None:
            prof = KraProfileService.get_or_create_company_profile(db, company_id=c.id)
            KraProfileService.migrate_company_secret_fields(prof)
        return prof

    if "trader_invoicing_system_name" in data:
        p = _prof()
        p.kra_trader_invoicing_system_name = (body.trader_invoicing_system_name or "").strip() or None
    if data.get("clear_integrator_pin"):
        p = _prof()
        p.integrator_pin = None
        p.credential_updated_at = datetime.now(timezone.utc)
    elif "integrator_pin" in data:
        p = _prof()
        v = (body.integrator_pin or "").strip()
        p.integrator_pin = encrypt_secret(v) if v else None
        p.credential_updated_at = datetime.now(timezone.utc)

    if body.kra_enabled is not None:
        was = bool(getattr(c, "kra_enabled", False))
        c.kra_enabled = bool(body.kra_enabled)
        if bool(body.kra_enabled) and not was and getattr(c, "kra_onboarded_at", None) is None:
            c.kra_onboarded_at = datetime.now(timezone.utc)
    if body.kra_mode is not None:
        c.kra_mode = norm_kra_mode(body.kra_mode)

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
        creds = BranchEtimsCredentials(
            branch_id=branch_id,
            company_id=branch.company_id,
            environment="sandbox",
            enabled=False,
            etims_solution="OSCU",
        )
        db.add(creds)

    data = body.model_dump(exclude_unset=True)
    credential_material_changed = branch_etims_credential_material_changed(creds, body, data)

    if body.kra_bhf_id is not None:
        creds.kra_bhf_id = (body.kra_bhf_id or "").strip() or None
    if body.device_serial is not None:
        creds.device_serial = (body.device_serial or "").strip() or None
    if body.cmc_key is not None:
        v = (body.cmc_key or "").strip()
        if v:
            creds.cmc_key_encrypted = encrypt_secret(v)
    if body.environment is not None:
        creds.environment = norm_etims_env(body.environment)
    if body.etims_solution is not None:
        creds.etims_solution = norm_etims_solution(body.etims_solution)
    if body.apigee_app_id is not None:
        creds.apigee_app_id = (body.apigee_app_id or "").strip() or None
    if body.client_tax_pin is not None:
        creds.client_tax_pin = (body.client_tax_pin or "").strip() or None
    if body.consumer_key is not None:
        creds.consumer_key = (body.consumer_key or "").strip() or None
    if "consumer_secret" in data:
        v = (body.consumer_secret or "").strip()
        if v:
            creds.consumer_secret_encrypted = encrypt_secret(v)

    KraProfileService.migrate_branch_secret_fields(creds)
    invalidate_branch_etims_verification(creds, dirty=credential_material_changed)

    _oauth_u, _oauth_p = get_oauth_username_password(creds)
    _hardware_ok = bool(
        (creds.kra_bhf_id and str(creds.kra_bhf_id).strip())
        and (creds.device_serial and str(creds.device_serial).strip())
        and get_cmc_key_plain(creds)
    )
    if creds.enabled and (
        (creds.connection_status or "").strip().lower() == "not_configured"
        or not _hardware_ok
        or not (_oauth_u and _oauth_p)
    ):
        creds.enabled = False

    if body.enabled is not None:
        if body.enabled and (creds.connection_status or "").strip().lower() != "verified":
            raise HTTPException(status_code=400, detail="Branch must be VERIFIED before enabling submission.")
        creds.enabled = bool(body.enabled)
        if creds.enabled:
            KraProfileService.get_or_create_company_profile(db, company_id=branch.company_id).module_enabled = True

    if credential_material_changed:
        creds.credential_updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(creds)
    return branch_etims_row(branch, creds)


@router.post("/branch/{branch_id}/etims/test-connection", response_model=Dict[str, Any])
def admin_test_branch_etims_connection(
    branch_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    try:
        creds = KraProfileService.get_or_create_branch_profile(db, branch_id=branch_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Branch not found") from None
    KraProfileService.migrate_branch_secret_fields(creds)
    db.commit()
    db.refresh(creds)
    company = db.query(Company).filter(Company.id == branch.company_id).first()
    tin = (company.pin or "").strip() if company else ""
    missing: List[str] = []
    if not tin:
        missing.append("Company PIN (TIN) — fill above and click Save company eTIMS identity")
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        missing.append(
            "KRA Branch Id (bhfId) — from developer.go.ke validation (often 00); fill on the branch row and click Save branch"
        )
    if not (creds.device_serial and str(creds.device_serial).strip()):
        missing.append("Device serial — fill on the branch row and click Save branch")
    u_chk, p_chk = get_oauth_username_password(creds)
    if not u_chk or not p_chk:
        missing.append(
            "OAuth client — Consumer Key + Consumer Secret on the branch (Save branch), or server ETIMS_APP_CONSUMER_* env"
        )
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Cannot run Test until these are saved on the server: " + " · ".join(missing),
        )
    cmc_for_request = get_cmc_key_plain(creds) or None
    u, p = get_oauth_username_password(creds)

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    now = datetime.now(timezone.utc)
    try:
        token = get_access_token(api_base=base, username=u, password=p, timeout=45, environment=env_eff)
    except Exception as e:
        creds.connection_status = "failed"
        creds.last_tested_at = now
        creds.validation_status = "failed"
        creds.last_validation_error = "OAUTH_FAILED"
        creds.token_status = "failed"
        creds.activation_status = "invalid_credentials"
        db.commit()
        raise HTTPException(status_code=502, detail=f"eTIMS OAuth failed: {e}") from e

    bhf = str(creds.kra_bhf_id).strip()
    dvc = str(creds.device_serial).strip()
    apigee = (creds.apigee_app_id or "").strip() or None
    try:
        r, parsed = post_select_init_osdc_info_with_retries(
            api_base=base,
            tin=tin,
            bhf_id=bhf,
            dvc_serial=dvc,
            bearer_token=token,
            apigee_app_id=apigee,
            cmc_key_plain=cmc_for_request,
            timeout=90,
        )
    except requests.RequestException as e:
        creds.connection_status = "failed"
        creds.last_tested_at = now
        creds.validation_status = "failed"
        creds.last_validation_error = "INITIALIZE_REQUEST_FAILED"
        creds.activation_status = "connection_failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"eTIMS request failed: {e}") from e

    text = (r.text or "")[:8000]
    summary = summarize_select_init_probe(parsed=parsed, response=r, creds=creds)
    KraProfileService.migrate_branch_secret_fields(creds)
    verified = bool(summary.get("verified"))
    creds.last_tested_at = now
    creds.connection_status = "verified" if verified else "failed"
    creds.validation_status = "passed" if verified else "failed"
    creds.last_validation_error = None if verified else (
        "INITIALIZE_NO_CMC"
        if summary.get("envelope_ok") and not summary.get("has_cmc_key")
        else "INITIALIZE_FAILED"
    )
    creds.token_last_checked_at = now
    creds.token_status = "ok" if verified else "failed"
    if verified:
        creds.last_validation_at = now
    if verified and KraProfileService.can_activate_branch(creds) and creds.enabled:
        creds.activation_status = "active"
    elif verified:
        creds.activation_status = "validated"
    else:
        creds.activation_status = "connection_failed"
    db.commit()

    return {
        "success": verified,
        "status_code": r.status_code,
        "connection_status": creds.connection_status,
        "environment": env_eff,
        "response_text": text,
        "response": parsed,
        "result_cd": summary.get("result_cd"),
        "cmc_extracted_from_response": summary.get("cmc_extracted_from_response"),
        "has_cmc_key": summary.get("has_cmc_key"),
        "envelope_ok": summary.get("envelope_ok"),
        "hint": (
            None
            if verified
            else (
                "KRA did not return a CMC key and none is stored. For resultCd=902 paste CMC from the OSCU portal, "
                "or ensure device serial / branch id match your Gava registration."
                if summary.get("envelope_ok") and not summary.get("has_cmc_key")
                else None
            )
        ),
    }

