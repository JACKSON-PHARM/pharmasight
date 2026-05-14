"""
Platform Admin API (company-level controls).

This is distinct from tenant admin settings:
- Platform admin can manage companies, subscriptions, and licensed modules.
- Access requires the RBAC role_name `platform_super_admin`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

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
from app.dependencies import get_current_user, get_tenant_db
from app.dependencies import get_effective_company_id_for_user
from app.models.company import Company
from app.models.company import Branch, BranchEtimsCredentials
from app.models.company_module import CompanyModule
from app.models.user import User, UserBranchRole, UserRole
from app.module_enforcement import get_company_module_license_catalog
from app.utils.company_plan_limits import sync_demo_plan_slug_with_subscription_status
from app.module_metadata import get_core_modules
from app.services.etims.branch_credentials import effective_etims_environment, get_cmc_key_plain, get_oauth_username_password
from app.services.etims.constants import SELECT_INIT_OSDC_PATH
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials
from app.services.etims.etims_oauth_client import get_access_token
from app.services.etims.credential_crypto import encrypt_secret
from app.services.etims.select_init_osdc_client import (
    post_select_init_osdc_info_with_retries,
    summarize_select_init_probe,
)
from app.models.company_kra_profile import CompanyKraProfile
from app.services.etims.kra_profile_service import KraProfileService

import requests

router = APIRouter(prefix="/platform-admin", tags=["Platform Admin"])


def require_platform_super_admin(
    user_db: Tuple[User, Session] = Depends(get_current_user),
) -> Tuple[User, Session]:
    user, db = user_db
    # Any branch role named platform_super_admin grants access.
    role_names = (
        db.query(UserRole.role_name)
        .join(UserBranchRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user.id)
        .distinct()
        .all()
    )
    allowed = {"platform_super_admin"}
    ok = any((r[0] or "").strip().lower() in allowed for r in (role_names or []))
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin access required")
    return user_db


@router.get("/company/{company_id}/etims", response_model=PlatformEtimsCompanyResponse)
def platform_get_company_etims(
    company_id: UUID,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
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
def platform_patch_company_pin(
    company_id: UUID,
    body: PatchCompanyPinRequest,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
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
    return platform_get_company_etims(company_id, auth=auth, db=db)


@router.patch("/branch/{branch_id}/etims", response_model=PlatformEtimsBranchRow)
def platform_patch_branch_etims(
    branch_id: UUID,
    body: PatchBranchEtimsRequest,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
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
def platform_test_branch_etims_connection(
    branch_id: UUID,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
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
        missing.append("Company PIN (TIN)")
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        missing.append("KRA Branch Id (bhfId)")
    if not (creds.device_serial and str(creds.device_serial).strip()):
        missing.append("Device serial")
    u_chk, p_chk = get_oauth_username_password(creds)
    if not u_chk or not p_chk:
        missing.append(
            "OAuth — Consumer Key + Consumer Secret on the branch or ETIMS_APP_CONSUMER_* on server"
        )
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Cannot run Test until these are saved: " + " · ".join(missing),
        )
    cmc_for_request = get_cmc_key_plain(creds) or None
    u, p = u_chk, p_chk

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
        "ok": verified,
        "http_status": r.status_code,
        "environment": env_eff,
        "api_base": base,
        "endpoint": SELECT_INIT_OSDC_PATH,
        "connection_status": creds.connection_status,
        "last_tested_at": creds.last_tested_at.isoformat() if creds.last_tested_at else None,
        "response_excerpt": text,
        "response_json": parsed,
        "result_cd": summary.get("result_cd"),
        "cmc_extracted_from_response": summary.get("cmc_extracted_from_response"),
        "has_cmc_key": summary.get("has_cmc_key"),
        "hint": (
            None
            if verified
            else (
                "KRA did not return a CMC key and none is stored. For resultCd=902 paste CMC from the OSCU portal."
                if summary.get("envelope_ok") and not summary.get("has_cmc_key")
                else None
            )
        ),
    }


class PlatformCompanyResponse(BaseModel):
    id: UUID
    name: str
    currency: Optional[str] = None
    timezone: Optional[str] = None
    is_active: bool = True
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    trial_expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ModuleToggle(BaseModel):
    name: str = Field(..., min_length=1)
    enabled: bool


class PatchCompanyModulesRequest(BaseModel):
    modules: List[ModuleToggle] = Field(default_factory=list)


class PatchCompanySubscriptionRequest(BaseModel):
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    trial_expires_at: Optional[datetime] = None


class PatchCompanyStatusRequest(BaseModel):
    is_active: bool


@router.get("/companies", response_model=List[PlatformCompanyResponse])
def list_companies(
    q: Optional[str] = Query(None),
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
    query = db.query(Company)
    if q and str(q).strip():
        term = f"%{str(q).strip()}%"
        query = query.filter(Company.name.ilike(term))
    return query.order_by(Company.created_at.desc()).limit(1000).all()


@router.get("/company/{company_id}", response_model=Dict[str, Any])
def get_company(
    company_id: UUID,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    rows = (
        db.query(CompanyModule)
        .filter(CompanyModule.company_id == company_id)
        .order_by(CompanyModule.module_name.asc())
        .all()
    )
    return {
        "company": PlatformCompanyResponse.model_validate(c).model_dump(),
        "modules": [{"name": r.module_name, "enabled": bool(r.is_enabled)} for r in rows],
        "module_catalog": get_company_module_license_catalog(db, company_id),
        "core_modules": sorted(list(get_core_modules(db))),
    }


@router.patch("/company/{company_id}/modules", response_model=Dict[str, Any])
def patch_company_modules(
    company_id: UUID,
    body: PatchCompanyModulesRequest,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    core = get_core_modules(db)
    for t in body.modules:
        name = (t.name or "").strip().lower()
        if not name:
            continue
        if name in core:
            # Core modules are implicit; ignore writes to prevent confusion.
            continue
        row = (
            db.query(CompanyModule)
            .filter(CompanyModule.company_id == company_id, CompanyModule.module_name == name)
            .first()
        )
        if row is None:
            row = CompanyModule(company_id=company_id, module_name=name, is_enabled=bool(t.enabled))
            db.add(row)
        else:
            row.is_enabled = bool(t.enabled)
            db.add(row)
    db.commit()
    return {"success": True}


@router.patch("/company/{company_id}/subscription", response_model=PlatformCompanyResponse)
def patch_company_subscription(
    company_id: UUID,
    body: PatchCompanySubscriptionRequest,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    if body.subscription_plan is not None:
        c.subscription_plan = body.subscription_plan.strip() or None
    if body.subscription_status is not None:
        c.subscription_status = body.subscription_status.strip() or None
    if body.trial_expires_at is not None or body.trial_expires_at is None:
        c.trial_expires_at = body.trial_expires_at
    sync_demo_plan_slug_with_subscription_status(c)
    db.commit()
    db.refresh(c)
    return c


@router.patch("/company/{company_id}/status", response_model=PlatformCompanyResponse)
def patch_company_status(
    company_id: UUID,
    body: PatchCompanyStatusRequest,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    c.is_active = bool(body.is_active)
    db.commit()
    db.refresh(c)
    return c

