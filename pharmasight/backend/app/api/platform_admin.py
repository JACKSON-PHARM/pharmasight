"""
Platform Admin API (company-level controls).

This is distinct from tenant admin settings:
- Platform admin can manage companies, subscriptions, and licensed modules.
- Access requires the RBAC role_name `platform_super_admin`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.dependencies import get_effective_company_id_for_user
from app.models.company import Company
from app.models.company import Branch, BranchEtimsCredentials
from app.models.company_module import CompanyModule
from app.models.user import User, UserBranchRole, UserRole
from app.module_enforcement import get_company_module_license_catalog
from app.module_metadata import get_core_modules
from app.services.etims.branch_credentials import effective_etims_environment, get_cmc_key_plain, get_oauth_username_password
from app.services.etims.constants import SELECT_INIT_OSDC_PATH
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials, find_etims_result_cd
from app.services.etims.etims_oauth_client import get_access_token

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
    c.pin = (body.pin or "").strip() or None
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
def platform_test_branch_etims_connection(
    branch_id: UUID,
    auth: Tuple[User, Session] = Depends(require_platform_super_admin),
    db: Session = Depends(get_tenant_db),
):
    _user, _ = auth
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
    creds.last_tested_at = now
    creds.connection_status = "verified" if ok else "failed"
    db.commit()
    return {
        "ok": ok,
        "http_status": r.status_code,
        "environment": env_eff,
        "api_base": base,
        "endpoint": SELECT_INIT_OSDC_PATH,
        "connection_status": creds.connection_status,
        "last_tested_at": creds.last_tested_at.isoformat() if creds.last_tested_at else None,
        "response_excerpt": text,
        "response_json": parsed,
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

