"""Shared Pydantic models and helpers for platform eTIMS onboarding (admin + platform-admin routers)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.models.company import Branch, BranchEtimsCredentials
from app.models.company_kra_profile import CompanyKraProfile
from app.services.etims.branch_credentials import effective_etims_environment, get_cmc_key_plain, get_oauth_username_password
from app.services.etims.kra_profile_service import KraProfileService


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
    etims_solution: str = "OSCU"
    apigee_app_id: Optional[str] = None
    client_tax_pin: Optional[str] = None
    consumer_key: Optional[str] = None
    has_cmc_key: bool = False
    has_consumer_secret: bool = False
    has_oauth_config: bool = False


class PlatformEtimsCompanyResponse(BaseModel):
    company_id: UUID
    company_name: str
    company_pin: Optional[str] = None
    trader_invoicing_system_name: Optional[str] = None
    has_company_integrator_pin: bool = False
    branches: List[PlatformEtimsBranchRow] = Field(default_factory=list)


class PatchCompanyPinRequest(BaseModel):
    """Company-level KRA identity fields (PIN + developer-portal trace metadata)."""

    pin: Optional[str] = None
    trader_invoicing_system_name: Optional[str] = Field(
        None,
        description="KRA Trader Invoicing System Name (ops traceability; from developer.go.ke / validation).",
    )
    integrator_pin: Optional[str] = Field(
        None,
        description="Plain integrator PIN; stored encrypted on company_kra_profiles. Omit to leave unchanged.",
    )
    clear_integrator_pin: Optional[bool] = Field(
        None,
        description="If true, clears stored company integrator PIN.",
    )


class PatchBranchEtimsRequest(BaseModel):
    kra_bhf_id: Optional[str] = Field(None, description="KRA Branch Id (bhfId)")
    device_serial: Optional[str] = None
    cmc_key: Optional[str] = Field(None, description="Plain CMC key; stored encrypted")
    environment: Optional[str] = None
    enabled: Optional[bool] = None
    etims_solution: Optional[str] = Field(None, description="e.g. OSCU (from KRA onboarding)")
    apigee_app_id: Optional[str] = Field(None, description="Apigee App ID from validation screen")
    client_tax_pin: Optional[str] = Field(None, description="Application / test taxpayer PIN from KRA validation")
    consumer_key: Optional[str] = Field(None, description="developer.go.ke Consumer Key (OAuth client id)")
    consumer_secret: Optional[str] = Field(
        None,
        description="developer.go.ke Consumer Secret; write-only, stored encrypted",
    )


def norm_etims_env(v: Optional[str]) -> str:
    e = (v or "sandbox").strip().lower()
    if e not in ("sandbox", "production"):
        raise HTTPException(status_code=400, detail="environment must be sandbox or production")
    return e


def norm_etims_solution(v: Optional[str]) -> str:
    s = (v or "OSCU").strip().upper() or "OSCU"
    if len(s) > 50:
        raise HTTPException(status_code=400, detail="etims_solution too long (max 50)")
    return s


def invalidate_branch_etims_verification(creds: BranchEtimsCredentials, *, dirty: bool) -> None:
    if not dirty:
        return
    if (creds.connection_status or "").strip().lower() == "verified":
        creds.connection_status = "not_tested"


def branch_etims_credential_material_changed(
    creds: BranchEtimsCredentials,
    body: PatchBranchEtimsRequest,
    body_data: Dict[str, Any],
) -> bool:
    """
    True when PATCH updates values that should drop verified connection_status.

    Re-saving identical credentials must NOT invalidate (e.g. toggling Submission enabled alone).
    """
    if body.kra_bhf_id is not None:
        new_v = (body.kra_bhf_id or "").strip() or None
        old_v = (creds.kra_bhf_id or "").strip() or None
        if new_v != old_v:
            return True
    if body.device_serial is not None:
        new_v = (body.device_serial or "").strip() or None
        old_v = (creds.device_serial or "").strip() or None
        if new_v != old_v:
            return True
    if body.environment is not None:
        new_e = norm_etims_env(body.environment)
        old_e = norm_etims_env(creds.environment)
        if new_e != old_e:
            return True
    if body.etims_solution is not None:
        new_s = norm_etims_solution(body.etims_solution)
        old_s = norm_etims_solution(getattr(creds, "etims_solution", None))
        if new_s != old_s:
            return True
    if body.apigee_app_id is not None:
        new_v = (body.apigee_app_id or "").strip() or None
        old_v = (creds.apigee_app_id or "").strip() or None
        if new_v != old_v:
            return True
    if body.client_tax_pin is not None:
        new_v = (body.client_tax_pin or "").strip() or None
        old_v = (creds.client_tax_pin or "").strip() or None
        if new_v != old_v:
            return True
    if body.consumer_key is not None:
        new_v = (body.consumer_key or "").strip() or None
        old_v = (creds.consumer_key or "").strip() or None
        if new_v != old_v:
            return True
    if "consumer_secret" in body_data:
        v = (body.consumer_secret or "").strip()
        if v:
            return True
    if body.cmc_key is not None:
        v = (body.cmc_key or "").strip()
        if v:
            return True
    return False


def branch_etims_row(branch: Branch, creds: Optional[BranchEtimsCredentials]) -> PlatformEtimsBranchRow:
    if not creds:
        return PlatformEtimsBranchRow(branch_id=branch.id, branch_name=branch.name, branch_code=branch.code)
    KraProfileService.migrate_branch_secret_fields(creds)
    u, p = get_oauth_username_password(creds)
    cs_plain = bool((getattr(creds, "consumer_secret_encrypted", None) or "").strip())
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
        etims_solution=(creds.etims_solution or "OSCU").strip().upper() or "OSCU",
        apigee_app_id=creds.apigee_app_id,
        client_tax_pin=creds.client_tax_pin,
        consumer_key=creds.consumer_key,
        has_cmc_key=bool(get_cmc_key_plain(creds)),
        has_consumer_secret=cs_plain,
        has_oauth_config=bool(u and p),
    )


def company_etims_profile_labels(db, company_id: UUID) -> tuple[Optional[str], bool]:
    kra_co = db.query(CompanyKraProfile).filter(CompanyKraProfile.company_id == company_id).first()
    trader_name = kra_co.kra_trader_invoicing_system_name if kra_co else None
    has_int = bool(kra_co and (kra_co.integrator_pin or "").strip())
    return trader_name, has_int
