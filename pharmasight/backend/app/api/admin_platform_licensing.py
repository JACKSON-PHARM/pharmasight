"""
Admin Platform Licensing API.

These endpoints are intended for `admin.html` platform operators authenticated via `/api/admin/auth/login`
admin_token. This is separate from the RBAC-gated `/api/platform-admin/*` routes, which require an app user
with `platform_super_admin`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_tenant_db
from app.models.company import Company
from app.models.company import Branch, BranchEtimsCredentials
from app.models.company_module import CompanyModule
from app.module_enforcement import get_company_module_license_catalog
from app.module_metadata import get_core_modules
from app.services.etims.branch_credentials import effective_etims_environment, get_cmc_key_plain, get_oauth_username_password
from app.services.etims.constants import SELECT_INIT_OSDC_PATH
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials, find_etims_result_cd
from app.services.etims.etims_oauth_client import get_access_token

import requests

router = APIRouter(prefix="/platform-licensing", tags=["Platform Licensing (Admin)"])


class PlatformCompanyResponse(BaseModel):
    id: UUID
    name: str
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


@router.get("/companies", response_model=List[PlatformCompanyResponse])
def list_companies(
    q: Optional[str] = Query(None),
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    query = db.query(Company)
    if q and str(q).strip():
        term = f"%{str(q).strip()}%"
        query = query.filter(Company.name.ilike(term))
    return query.order_by(Company.created_at.desc()).limit(1000).all()


@router.get("/company/{company_id}", response_model=Dict[str, Any])
def get_company(
    company_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
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

