"""
KRA eTIMS OSCU operator endpoints (sandbox/production per branch credentials).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import (
    get_effective_company_id_for_user,
    get_tenant_db,
    ensure_user_has_branch_access,
    require_document_belongs_to_user_company,
)
from app.module_enforcement import require_module
from app.models.company import Branch, BranchEtimsCredentials, Company
from app.models.user import UserBranchRole, UserRole
from app.api.users import _user_has_owner_or_admin_role
from app.api.platform_admin import require_platform_super_admin
from app.services.etims.constants import SELECT_INIT_OSDC_PATH
from app.services.etims.branch_credentials import (
    effective_etims_environment,
    get_cmc_key_plain,
    get_oauth_username_password,
)
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials, find_etims_result_cd
from app.services.etims.etims_oauth_client import get_access_token
from app.services.etims.sync_cursor_service import EtimsSyncCursorService

logger = logging.getLogger(__name__)

router = APIRouter()


def _user_has_any_of_roles(db: Session, user_id: UUID, role_names: set[str]) -> bool:
    """
    Branch-scoped role check for eTIMS validation access.
    Used only to loosen test-connection access (auth still required by require_module("pharmacy")).
    """
    if not role_names:
        return False
    role_names_l = {str(r).strip().lower() for r in role_names if str(r).strip()}
    if not role_names_l:
        return False
    rows = (
        db.query(UserRole.role_name)
        .join(UserBranchRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user_id)
        .all()
    )
    return any((r[0] or "").strip().lower() in role_names_l for r in rows)


@router.get("/sync-cursor/{branch_id}/{category}")
def get_etims_sync_cursor(
    branch_id: UUID,
    category: str,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    """
    Debug/helper endpoint: return the persisted OSCU lastReqDt cursor for a branch+category.
    Owner/admin only (to avoid leaking internal sync behavior to low-privilege users).
    """
    user, _ = current_user_and_db
    if not _user_has_owner_or_admin_role(db, user.id):
        # allow platform super admin too
        try:
            require_platform_super_admin((user, db))
        except Exception:
            raise HTTPException(status_code=403, detail="Only owner/admin can view eTIMS sync cursors.")
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_document_belongs_to_user_company(db, user, branch, "Branch", None)
    ensure_user_has_branch_access(db, user.id, branch_id)
    last_req_dt = EtimsSyncCursorService.get_last_req_dt(
        db, company_id=branch.company_id, branch_id=branch_id, category=category
    )
    return {"branch_id": str(branch_id), "category": category, "lastReqDt": last_req_dt}


class EtimsCredentialsUpdate(BaseModel):
    kra_bhf_id: Optional[str] = None
    device_serial: Optional[str] = None
    cmc_key: Optional[str] = Field(None, description="Plain CMC key; sent over TLS, stored in cmc_key_encrypted column")
    kra_oauth_username: Optional[str] = None
    kra_oauth_password: Optional[str] = None
    environment: Optional[str] = None
    enabled: Optional[bool] = None


def _norm_env(v: Optional[str]) -> str:
    e = (v or "sandbox").strip().lower()
    if e not in ("sandbox", "production"):
        raise HTTPException(status_code=400, detail="environment must be sandbox or production")
    return e


def _oauth_configured(creds: BranchEtimsCredentials) -> bool:
    u, p = get_oauth_username_password(creds)
    return bool(u and p)


def _hardware_configured(creds: BranchEtimsCredentials) -> bool:
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        return False
    if not (creds.device_serial and str(creds.device_serial).strip()):
        return False
    if not get_cmc_key_plain(creds):
        return False
    return True


def _apply_connection_status_after_field_updates(
    creds: BranchEtimsCredentials, *, invalidate_verification: bool
) -> None:
    """Recompute status from current field values; caller handles enabled flag separately."""
    if not _hardware_configured(creds) or not _oauth_configured(creds):
        creds.connection_status = "not_configured"
        return
    if invalidate_verification:
        creds.connection_status = "not_tested"
        return
    if creds.connection_status in ("not_configured", "failed"):
        creds.connection_status = "not_tested"


def _serialize_etims_public(
    creds: Optional[BranchEtimsCredentials],
    branch_id: UUID,
    *,
    is_admin: bool,
) -> Dict[str, Any]:
    if not creds:
        return {
            "branch_id": str(branch_id),
            "has_credentials_row": False,
            "kra_bhf_id": None,
            "device_serial": None,
            "environment": "sandbox",
            "enabled": False,
            "connection_status": "not_configured",
            "last_tested_at": None,
            "has_cmc_key": False,
            "kra_oauth_username": None,
            "has_oauth_password": False,
            "company_pin_configured": None,
        }
    has_cmc = bool(get_cmc_key_plain(creds))
    u, p = get_oauth_username_password(creds)
    has_oauth = bool(u and p)
    out: Dict[str, Any] = {
        "branch_id": str(branch_id),
        "has_credentials_row": True,
        "environment": (creds.environment or "sandbox").strip().lower() or "sandbox",
        "enabled": bool(creds.enabled),
        "connection_status": creds.connection_status or "not_configured",
        "last_tested_at": creds.last_tested_at.isoformat() if creds.last_tested_at else None,
        "has_cmc_key": has_cmc,
        "has_oauth_password": has_oauth,
    }
    if is_admin:
        out["kra_bhf_id"] = creds.kra_bhf_id
        out["device_serial"] = creds.device_serial
        out["kra_oauth_username"] = creds.kra_oauth_username
    else:
        out["kra_bhf_id"] = None
        out["device_serial"] = None
        out["kra_oauth_username"] = None
    return out


def _test_http_success(r: requests.Response, parsed: Optional[dict]) -> bool:
    if not (200 <= r.status_code < 300):
        return False
    if not isinstance(parsed, dict):
        return True
    rc = find_etims_result_cd(parsed)
    if rc is None:
        return True
    return rc == "000"


@router.get("/branch-credentials/{branch_id}")
def get_branch_etims_credentials(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_document_belongs_to_user_company(db, user, branch, "Branch", None)
    ensure_user_has_branch_access(db, user.id, branch_id)

    # Integrator-grade: tenants only see status. Platform admin manages secrets/config elsewhere.
    is_admin = False
    creds = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.branch_id == branch_id)
        .first()
    )
    company = db.query(Company).filter(Company.id == branch.company_id).first()
    tin = (company.pin or "").strip() if company else ""
    payload = _serialize_etims_public(creds, branch_id, is_admin=is_admin)
    payload["company_pin_configured"] = bool(tin)
    return payload


@router.get("/summary")
def list_etims_summaries_for_company(
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    company_id = get_effective_company_id_for_user(db, user)
    if not company_id:
        raise HTTPException(status_code=400, detail="No company context for user")

    branch_ids_subq = (
        db.query(UserBranchRole.branch_id)
        .filter(UserBranchRole.user_id == user.id)
        .subquery()
    )
    branches: List[Branch] = (
        db.query(Branch)
        .filter(Branch.company_id == company_id, Branch.id.in_(branch_ids_subq))
        .order_by(Branch.name.asc())
        .all()
    )
    is_admin = False
    items: List[Dict[str, Any]] = []
    for b in branches:
        creds = (
            db.query(BranchEtimsCredentials)
            .filter(BranchEtimsCredentials.branch_id == b.id)
            .first()
        )
        row = _serialize_etims_public(creds, b.id, is_admin=is_admin)
        row["branch_name"] = b.name
        row["branch_code"] = b.code
        items.append(row)
    return {"branches": items}


@router.patch("/branch-credentials/{branch_id}")
def patch_branch_etims_credentials(
    branch_id: UUID,
    body: EtimsCredentialsUpdate,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    # Platform-admin only: tenants cannot edit any eTIMS credentials/secrets.
    user, _ = current_user_and_db
    require_platform_super_admin((user, db))
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_document_belongs_to_user_company(db, user, branch, "Branch", None)
    # Platform admin: no branch assignment required.

    data = body.model_dump(exclude_unset=True)
    enable_requested = data.pop("enabled", None)

    secrets_changed = bool(data.get("cmc_key")) or bool(
        data.get("kra_oauth_password") is not None and str(data.get("kra_oauth_password") or "").strip()
    )
    config_changed = any(
        k in data for k in ("kra_bhf_id", "device_serial", "environment", "kra_oauth_username")
    )
    invalidate = secrets_changed or config_changed

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.branch_id == branch_id)
        .first()
    )
    if not creds:
        creds = BranchEtimsCredentials(
            branch_id=branch_id,
            company_id=branch.company_id,
            environment="sandbox",
            enabled=False,
            connection_status="not_configured",
        )
        db.add(creds)

    if "kra_bhf_id" in data:
        creds.kra_bhf_id = (data["kra_bhf_id"] or None) and str(data["kra_bhf_id"]).strip() or None
    if "device_serial" in data:
        creds.device_serial = (data["device_serial"] or None) and str(data["device_serial"]).strip() or None
    if "cmc_key" in data and data["cmc_key"] is not None:
        v = str(data["cmc_key"]).strip()
        creds.cmc_key_encrypted = v if v else None
    if "kra_oauth_username" in data:
        v = data["kra_oauth_username"]
        creds.kra_oauth_username = (str(v).strip() if v is not None else None) or None
    if "kra_oauth_password" in data and data["kra_oauth_password"] is not None:
        v = str(data["kra_oauth_password"]).strip()
        creds.kra_oauth_password = v if v else None
    if "environment" in data and data["environment"] is not None:
        creds.environment = _norm_env(str(data["environment"]))

    _apply_connection_status_after_field_updates(creds, invalidate_verification=invalidate)

    if creds.enabled and (
        creds.connection_status == "not_configured"
        or not _hardware_configured(creds)
        or not _oauth_configured(creds)
    ):
        creds.enabled = False
        if creds.connection_status != "disabled":
            creds.connection_status = "not_configured"

    if enable_requested is not None:
        if enable_requested:
            if creds.connection_status != "verified":
                raise HTTPException(
                    status_code=400,
                    detail="Run Test eTIMS Connection successfully before enabling submission.",
                )
            creds.enabled = True
        else:
            creds.enabled = False
            creds.connection_status = "disabled"

    db.commit()
    db.refresh(creds)
    return _serialize_etims_public(creds, branch_id, is_admin=True)


@router.post("/test-connection/{branch_id}")
def test_etims_connection(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    """
    Verify OAuth + OSCU initialization for a branch (does not submit invoices).
    Requires owner/admin. Safe to call in sandbox.
    """
    # Sandbox validation needs this to be callable by branch/company admins too.
    user, _ = current_user_and_db
    if not _user_has_owner_or_admin_role(db, user.id) and not _user_has_any_of_roles(
        db,
        user.id,
        role_names={"branch_admin", "company_admin", "platform_super_admin"},
    ):
        raise HTTPException(status_code=403, detail="Not authorized to run eTIMS test-connection.")
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_document_belongs_to_user_company(db, user, branch, "Branch", None)
    # Platform admin: no branch assignment required.

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.branch_id == branch_id)
        .first()
    )
    if not creds:
        raise HTTPException(
            status_code=400,
            detail="No eTIMS credentials row for this branch. Save credentials first.",
        )
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
        raise HTTPException(
            status_code=400,
            detail="KRA OAuth credentials missing: set ETIMS_APP_CONSUMER_KEY and ETIMS_APP_CONSUMER_SECRET on the server, or both branch OAuth fields, or legacy ETIMS_OAUTH_* env vars.",
        )

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    now = datetime.now(timezone.utc)
    try:
        token = get_access_token(
            api_base=base, username=u, password=p, timeout=45, environment=env_eff
        )
    except Exception as e:
        logger.warning("eTIMS OAuth test failed: %s", e)
        creds.connection_status = "failed"
        creds.last_tested_at = now
        db.commit()
        raise HTTPException(status_code=502, detail=f"eTIMS OAuth failed: {e}") from e

    bhf = str(creds.kra_bhf_id).strip()
    dvc = str(creds.device_serial).strip()
    body = {"tin": tin, "bhfId": bhf, "dvcSrlNo": dvc}
    url = f"{base}{SELECT_INIT_OSDC_PATH}"
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

    out: Dict[str, Any] = {
        "ok": ok,
        "http_status": r.status_code,
        "environment": env_eff,
        "branch_environment": creds.environment,
        "api_base": base,
        "endpoint": SELECT_INIT_OSDC_PATH,
        "connection_status": creds.connection_status,
        "last_tested_at": creds.last_tested_at.isoformat() if creds.last_tested_at else None,
        "response_excerpt": text,
    }
    try:
        out["response_json"] = parsed
    except Exception:
        out["response_json"] = None
    return out
