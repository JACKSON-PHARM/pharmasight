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
from app.models.item import Item
from app.models.kra_event_outbox import KraEventOutbox
from app.models.user import UserBranchRole, UserRole
from app.api.users import _user_has_owner_or_admin_role
from app.api.platform_admin import require_platform_super_admin
from app.config import settings
from app.services.etims.constants import SELECT_INIT_OSDC_PATH
from app.services.etims.branch_credentials import (
    effective_etims_environment,
    get_cmc_key_plain,
    get_oauth_username_password,
)
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials
from app.services.etims.etims_oauth_client import get_access_token
from app.services.etims.sync_cursor_service import EtimsSyncCursorService
from app.services.etims.kra_profile_service import KraProfileService
from app.services.etims.kra_validation_service import KraValidationService
from app.services.etims.credential_crypto import encrypt_secret
from app.services.etims.kra_audit_service import KraAuditService
from app.services.etims.select_init_osdc_client import (
    post_select_init_osdc_info_with_retries,
    summarize_select_init_probe,
)
from app.services.etims.kra_policy_service import KraPolicyService
from app.services.etims.kra_readiness_resolver import BranchKraReadinessResolver
from app.services.etims.kra_outbox_service import KraOutboxService
from app.services.etims.kra_company_activation import company_kra_execution_enabled

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


class CompanyKraProfilePatch(BaseModel):
    module_enabled: Optional[bool] = None
    default_environment: Optional[str] = None
    integrator_pin: Optional[str] = None
    onboarding_status: Optional[str] = None
    activation_status: Optional[str] = None


class BranchKraProfilePatch(BaseModel):
    environment: Optional[str] = None
    enabled: Optional[bool] = None
    activation_status: Optional[str] = None
    kra_bhf_id: Optional[str] = None
    device_serial: Optional[str] = None
    apigee_app_id: Optional[str] = None
    client_tax_pin: Optional[str] = None
    integrator_pin: Optional[str] = None
    consumer_key: Optional[str] = None
    consumer_secret: Optional[str] = Field(
        None,
        description="Write-only KRA consumer secret; never returned in APIs",
    )
    cmc_key: Optional[str] = None
    kra_oauth_username: Optional[str] = None
    kra_oauth_password: Optional[str] = Field(
        None,
        description="Write-only branch OAuth password; never returned in APIs",
    )


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
            "activation_status": "not_configured",
            "validation_status": "unknown",
            "token_status": "unknown",
            "health_state": "not_ready",
            "credential_version": 1,
            "credential_updated_at": None,
            "failed_validation_count": 0,
            "token_expires_at": None,
            "activation_blockers": [],
            "revalidation_required": True,
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
        # Compatibility-safe exposure of new control-plane state to legacy consumers.
        "activation_status": (creds.activation_status or "not_configured"),
        "validation_status": (creds.validation_status or "unknown"),
        "token_status": (creds.token_status or "unknown"),
        "health_state": KraProfileService.compute_health_state(creds),
        "credential_version": int(creds.credential_version or 1),
        "credential_updated_at": creds.credential_updated_at.isoformat() if creds.credential_updated_at else None,
        "failed_validation_count": int(getattr(creds, "failed_validation_count", 0) or 0),
        "token_expires_at": creds.token_expires_at.isoformat() if getattr(creds, "token_expires_at", None) else None,
        "activation_blockers": KraProfileService.activation_blockers(creds),
        "revalidation_required": KraPolicyService.requires_revalidation(creds),
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


@router.get("/outbox/summary")
def get_kra_outbox_summary(
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    company_id = get_effective_company_id_for_user(db, user)
    if not company_id:
        raise HTTPException(status_code=400, detail="No company context for user")
    if not _user_has_owner_or_admin_role(db, user.id):
        try:
            require_platform_super_admin((user, db))
        except Exception:
            raise HTTPException(status_code=403, detail="Not authorized to view KRA outbox summary.")

    counts = {
        "pending": 0,
        "processing": 0,
        "retry": 0,
        "processed": 0,
        "dead_letter": 0,
    }


@router.post("/outbox/requeue/item/{event_id}")
def requeue_kra_item_outbox_event(
    event_id: UUID,
    dry_run: bool = False,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    company_id = get_effective_company_id_for_user(db, user)
    if not company_id:
        raise HTTPException(status_code=400, detail="No company context for user")
    if not _user_has_owner_or_admin_role(db, user.id):
        try:
            require_platform_super_admin((user, db))
        except Exception:
            raise HTTPException(status_code=403, detail="Not authorized to requeue KRA outbox events.")

    row = db.query(KraEventOutbox).filter(KraEventOutbox.id == event_id).first()
    if not row or str(row.company_id) != str(company_id):
        raise HTTPException(status_code=404, detail="Outbox event not found")
    if row.event_type != "item.updated":
        raise HTTPException(status_code=400, detail="Only item.updated events can be requeued from this endpoint.")
    if row.processing_status == "processing":
        raise HTTPException(status_code=400, detail="Event is currently processing; try again later.")

    if dry_run:
        return {
            "dry_run": True,
            "event_id": str(row.id),
            "event_type": row.event_type,
            "current_status": row.processing_status,
            "can_requeue": row.processing_status in ("retry", "dead_letter", "processed", "pending"),
        }

    KraOutboxService.reset_for_requeue(db, row)
    item = db.query(Item).filter(Item.id == row.aggregate_id, Item.company_id == row.company_id).first()
    if item:
        item.kra_needs_resync = True
        item.kra_sync_status = "queued"
    db.commit()
    return {"ok": True, "event_id": str(row.id), "status": row.processing_status}


@router.post("/outbox/requeue/items/{branch_id}")
def requeue_kra_item_outbox_events_batch(
    branch_id: UUID,
    limit: int = 100,
    dry_run: bool = False,
    include_retry: bool = True,
    include_dead_letter: bool = True,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    if not _user_has_owner_or_admin_role(db, user.id):
        try:
            require_platform_super_admin((user, db))
        except Exception:
            raise HTTPException(status_code=403, detail="Not authorized to requeue KRA outbox events.")
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_document_belongs_to_user_company(db, user, branch, "Branch", None)
    ensure_user_has_branch_access(db, user.id, branch_id)

    statuses = []
    if include_retry:
        statuses.append("retry")
    if include_dead_letter:
        statuses.append("dead_letter")
    if not statuses:
        raise HTTPException(status_code=400, detail="Select at least one status to requeue.")

    rows = (
        db.query(KraEventOutbox)
        .filter(
            KraEventOutbox.company_id == branch.company_id,
            KraEventOutbox.branch_id == branch_id,
            KraEventOutbox.event_type == "item.updated",
            KraEventOutbox.processing_status.in_(tuple(statuses)),
        )
        .order_by(KraEventOutbox.updated_at.asc())
        .limit(max(1, min(int(limit or 100), 500)))
        .all()
    )
    if dry_run:
        return {
            "dry_run": True,
            "branch_id": str(branch_id),
            "company_id": str(branch.company_id),
            "candidates": len(rows),
            "candidate_event_ids": [str(r.id) for r in rows[:50]],
        }

    affected_item_ids: set[UUID] = set()
    for row in rows:
        KraOutboxService.reset_for_requeue(db, row)
        affected_item_ids.add(row.aggregate_id)

    if affected_item_ids:
        db.query(Item).filter(
            Item.company_id == branch.company_id,
            Item.id.in_(tuple(affected_item_ids)),
        ).update(
            {
                Item.kra_needs_resync: True,
                Item.kra_sync_status: "queued",
            },
            synchronize_session=False,
        )
    db.commit()
    return {
        "ok": True,
        "branch_id": str(branch_id),
        "company_id": str(branch.company_id),
        "requeued_events": len(rows),
        "affected_items": len(affected_item_ids),
    }
    rows = (
        db.query(KraEventOutbox.processing_status, func.count(KraEventOutbox.id))
        .filter(KraEventOutbox.company_id == company_id)
        .group_by(KraEventOutbox.processing_status)
        .all()
    )
    for st, c in rows:
        counts[str(st or "pending")] = int(c or 0)

    oldest_pending = (
        db.query(KraEventOutbox.created_at)
        .filter(
            KraEventOutbox.company_id == company_id,
            KraEventOutbox.processing_status.in_(("pending", "retry", "processing")),
        )
        .order_by(KraEventOutbox.created_at.asc())
        .first()
    )
    latest_dead = (
        db.query(KraEventOutbox)
        .filter(
            KraEventOutbox.company_id == company_id,
            KraEventOutbox.processing_status == "dead_letter",
        )
        .order_by(KraEventOutbox.updated_at.desc())
        .limit(5)
        .all()
    )
    return {
        "company_id": str(company_id),
        "counts": counts,
        "oldest_unprocessed_at": oldest_pending[0].isoformat() if oldest_pending else None,
        "recent_dead_letter": [
            {
                "id": str(r.id),
                "event_type": r.event_type,
                "aggregate_id": str(r.aggregate_id),
                "attempt_count": int(r.attempt_count or 0),
                "last_error": (r.last_error or "")[:400],
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in latest_dead
        ],
    }


@router.post("/items/bootstrap-sync/{branch_id}")
def bootstrap_kra_item_sync(
    branch_id: UUID,
    limit: int = 100,
    dry_run: bool = False,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    if not _user_has_owner_or_admin_role(db, user.id):
        try:
            require_platform_super_admin((user, db))
        except Exception:
            raise HTTPException(status_code=403, detail="Not authorized to run KRA item bootstrap sync.")
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_document_belongs_to_user_company(db, user, branch, "Branch", None)
    ensure_user_has_branch_access(db, user.id, branch_id)

    if not dry_run and not company_kra_execution_enabled(db, branch.company_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "KRA execution is not enabled for this company. "
                "A platform administrator can enable it under Licensing → eTIMS."
            ),
        )

    rows = (
        db.query(Item)
        .filter(Item.company_id == branch.company_id, Item.is_active.is_(True))
        .order_by(Item.updated_at.asc())
        .limit(max(1, min(int(limit or 100), 1000)))
        .all()
    )
    out = {
        "branch_id": str(branch_id),
        "company_id": str(branch.company_id),
        "dry_run": bool(dry_run),
        "candidates": len(rows),
        "queued": 0,
        "synced": 0,
        "failed": 0,
        "errors": [],
    }
    for item in rows:
        if dry_run:
            out["queued"] += 1
            continue
        item.kra_needs_resync = True
        item.kra_sync_status = "queued"
        KraOutboxService.enqueue_item_updated(
            db,
            item=item,
            branch_id=branch_id,
            source="items.bootstrap",
            max_attempts=max(int(settings.KRA_OUTBOX_MAX_ATTEMPTS or 12), 1),
        )
        out["queued"] += 1
    db.commit()
    return out


@router.get("/items/sync-summary/{branch_id}")
def get_kra_item_sync_summary(
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

    rows = (
        db.query(Item.kra_sync_status, func.count(Item.id))
        .filter(Item.company_id == branch.company_id, Item.is_active.is_(True))
        .group_by(Item.kra_sync_status)
        .all()
    )
    counts: Dict[str, int] = {}
    for st, c in rows:
        counts[(st or "not_synced")] = int(c or 0)
    blocked = (
        db.query(Item.id, Item.name, Item.kra_sync_error, Item.kra_needs_resync)
        .filter(
            Item.company_id == branch.company_id,
            Item.is_active.is_(True),
            Item.kra_sync_status.in_(("failed", "not_synced", "queued")),
        )
        .order_by(Item.updated_at.desc())
        .limit(50)
        .all()
    )
    return {
        "branch_id": str(branch_id),
        "company_id": str(branch.company_id),
        "counts": counts,
        "blocked_items": [
            {
                "item_id": str(r[0]),
                "item_name": r[1],
                "error": r[2],
                "needs_resync": bool(r[3]),
            }
            for r in blocked
        ],
    }


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


@router.get("/company-profile/{company_id}")
def get_company_kra_profile(
    company_id: UUID,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    require_document_belongs_to_user_company(db, user, company, "Company", None)
    row = KraProfileService.get_or_create_company_profile(db, company_id=company_id)
    if KraProfileService.migrate_company_secret_fields(row):
        db.commit()
        db.refresh(row)
    db.flush()
    out = KraProfileService.serialize_company_profile_masked(row)
    out["company_name"] = company.name
    out["company_pin_configured"] = bool((company.pin or "").strip())
    return out


@router.patch("/company-profile/{company_id}")
def patch_company_kra_profile(
    company_id: UUID,
    body: CompanyKraProfilePatch,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    require_platform_super_admin((user, db))
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    row = KraProfileService.get_or_create_company_profile(db, company_id=company_id)
    KraProfileService.migrate_company_secret_fields(row)
    data = body.model_dump(exclude_unset=True)
    if "module_enabled" in data:
        row.module_enabled = bool(data["module_enabled"])
    if "default_environment" in data and data["default_environment"] is not None:
        row.default_environment = _norm_env(data["default_environment"])
    if "integrator_pin" in data and data["integrator_pin"] is not None:
        v = str(data["integrator_pin"]).strip()
        row.integrator_pin = encrypt_secret(v) if v else None
        row.credential_updated_at = datetime.now(timezone.utc)
    if "onboarding_status" in data and data["onboarding_status"] is not None:
        row.onboarding_status = str(data["onboarding_status"]).strip() or row.onboarding_status
    if "activation_status" in data and data["activation_status"] is not None:
        row.activation_status = str(data["activation_status"]).strip() or row.activation_status
    db.commit()
    KraAuditService.log_event(
        db,
        company_id=company.id,
        actor_user_id=user.id,
        event_type="company_profile_updated",
        event_status="success",
        message="Company KRA profile updated",
        metadata={"module_enabled": bool(row.module_enabled), "default_environment": row.default_environment},
    )
    db.commit()
    logger.info("KRA company profile updated company_id=%s by_user=%s", str(company_id), str(user.id))
    db.refresh(row)
    out = KraProfileService.serialize_company_profile_masked(row)
    out["company_name"] = company.name
    out["company_pin_configured"] = bool((company.pin or "").strip())
    return out


@router.get("/branch-profile/{branch_id}")
def get_branch_kra_profile(
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
    row = KraProfileService.get_or_create_branch_profile(db, branch_id=branch_id)
    if KraProfileService.migrate_branch_secret_fields(row):
        db.commit()
        db.refresh(row)
    db.flush()
    out = KraProfileService.serialize_branch_profile_masked(row)
    out["branch_name"] = branch.name
    out["branch_code"] = branch.code
    return out


@router.get("/branch-profile/{branch_id}/readiness")
def get_branch_kra_readiness(
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
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch_id).first()
    if creds:
        KraProfileService.migrate_branch_secret_fields(creds)
    readiness = BranchKraReadinessResolver.resolve(db, branch=branch, creds=creds)
    readiness["branch_name"] = branch.name
    readiness["branch_code"] = branch.code
    return readiness


@router.patch("/branch-profile/{branch_id}")
def patch_branch_kra_profile(
    branch_id: UUID,
    body: BranchKraProfilePatch,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    require_platform_super_admin((user, db))
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    row = KraProfileService.get_or_create_branch_profile(db, branch_id=branch_id)
    KraProfileService.migrate_branch_secret_fields(row)
    data = body.model_dump(exclude_unset=True)
    touched_secret = False
    enable_requested = None

    if "environment" in data and data["environment"] is not None:
        next_env = _norm_env(data["environment"])
        KraPolicyService.enforce_environment_switch_rules(row, next_env)
        row.environment = next_env
    if "enabled" in data and data["enabled"] is not None:
        enable_requested = bool(data["enabled"])
    if "activation_status" in data and data["activation_status"] is not None:
        target = KraProfileService.normalize_branch_activation_state(str(data["activation_status"]))
        if target == "active" and not KraProfileService.can_activate_branch(row):
            raise HTTPException(status_code=400, detail="Branch cannot be activated before successful validation.")
        row.activation_status = target
    if "kra_bhf_id" in data:
        row.kra_bhf_id = (str(data["kra_bhf_id"]).strip() if data["kra_bhf_id"] is not None else "") or None
    if "device_serial" in data:
        row.device_serial = (str(data["device_serial"]).strip() if data["device_serial"] is not None else "") or None
    if "apigee_app_id" in data:
        row.apigee_app_id = (str(data["apigee_app_id"]).strip() if data["apigee_app_id"] is not None else "") or None
    if "client_tax_pin" in data:
        row.client_tax_pin = (str(data["client_tax_pin"]).strip() if data["client_tax_pin"] is not None else "") or None
    if "integrator_pin" in data:
        v = (str(data["integrator_pin"]).strip() if data["integrator_pin"] is not None else "")
        row.integrator_pin = encrypt_secret(v) if v else None
    if "consumer_key" in data:
        row.consumer_key = (str(data["consumer_key"]).strip() if data["consumer_key"] is not None else "") or None
    if "consumer_secret" in data and data["consumer_secret"] is not None:
        v = str(data["consumer_secret"]).strip()
        row.consumer_secret_encrypted = encrypt_secret(v) if v else None
        touched_secret = True
    if "cmc_key" in data and data["cmc_key"] is not None:
        v = str(data["cmc_key"]).strip()
        row.cmc_key_encrypted = encrypt_secret(v) if v else None
        touched_secret = True
    if "kra_oauth_username" in data:
        row.kra_oauth_username = (str(data["kra_oauth_username"]).strip() if data["kra_oauth_username"] is not None else "") or None
    if "kra_oauth_password" in data and data["kra_oauth_password"] is not None:
        v = str(data["kra_oauth_password"]).strip()
        row.kra_oauth_password = encrypt_secret(v) if v else None
        touched_secret = True

    if touched_secret or any(
        k in data
        for k in (
            "consumer_key",
            "integrator_pin",
            "apigee_app_id",
            "client_tax_pin",
            "environment",
            "kra_oauth_username",
            "kra_bhf_id",
            "device_serial",
        )
    ):
        KraProfileService.touch_credential_update(row)
        row.connection_status = "not_tested"

    if enable_requested is not None:
        if enable_requested:
            KraPolicyService.enforce_enable_rules(row)
        row.enabled = enable_requested
        if not enable_requested:
            row.activation_status = "disabled"
    row.activation_blockers = ";".join(KraProfileService.activation_blockers(row))[:4000]

    db.commit()
    KraAuditService.log_event(
        db,
        company_id=branch.company_id,
        branch_id=branch_id,
        actor_user_id=user.id,
        event_type="branch_profile_updated",
        event_status="success",
        message="Branch KRA profile updated",
        metadata={
            "enabled": bool(row.enabled),
            "activation_status": row.activation_status,
            "validation_status": row.validation_status,
        },
    )
    db.commit()
    logger.info(
        "KRA branch profile updated branch_id=%s company_id=%s by_user=%s",
        str(branch_id),
        str(branch.company_id),
        str(user.id),
    )
    db.refresh(row)
    out = KraProfileService.serialize_branch_profile_masked(row)
    out["branch_name"] = branch.name
    out["branch_code"] = branch.code
    return out


@router.post("/branch-profile/{branch_id}/validate")
def validate_branch_kra_profile(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    user, _ = current_user_and_db
    if not _user_has_owner_or_admin_role(db, user.id) and not _user_has_any_of_roles(
        db, user.id, role_names={"branch_admin", "company_admin", "platform_super_admin"}
    ):
        raise HTTPException(status_code=403, detail="Not authorized to validate KRA profile.")
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_document_belongs_to_user_company(db, user, branch, "Branch", None)
    row = KraProfileService.get_or_create_branch_profile(db, branch_id=branch_id)
    KraProfileService.migrate_branch_secret_fields(row)
    if KraProfileService.normalize_branch_activation_state(row.activation_status) != "disabled":
        row.activation_status = "validating"
    result = KraValidationService.validate_branch_credentials(db, row)
    db.commit()
    KraAuditService.log_event(
        db,
        company_id=branch.company_id,
        branch_id=branch_id,
        actor_user_id=user.id,
        event_type="branch_validation",
        event_status="success" if bool(result.get("ok")) else "error",
        message="Branch KRA validation executed",
        metadata={"ok": bool(result.get("ok")), "environment": result.get("environment")},
    )
    db.commit()
    logger.info(
        "KRA branch validation branch_id=%s company_id=%s ok=%s",
        str(branch_id),
        str(branch.company_id),
        bool(result.get("ok")),
    )
    db.refresh(row)
    out = KraProfileService.serialize_branch_profile_masked(row)
    out["branch_name"] = branch.name
    out["branch_code"] = branch.code
    return {"validation": result, "profile": out}


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
    else:
        KraProfileService.migrate_branch_secret_fields(creds)

    if "kra_bhf_id" in data:
        creds.kra_bhf_id = (data["kra_bhf_id"] or None) and str(data["kra_bhf_id"]).strip() or None
    if "device_serial" in data:
        creds.device_serial = (data["device_serial"] or None) and str(data["device_serial"]).strip() or None
    if "cmc_key" in data and data["cmc_key"] is not None:
        v = str(data["cmc_key"]).strip()
        creds.cmc_key_encrypted = encrypt_secret(v) if v else None
    if "kra_oauth_username" in data:
        v = data["kra_oauth_username"]
        creds.kra_oauth_username = (str(v).strip() if v is not None else None) or None
    if "kra_oauth_password" in data and data["kra_oauth_password"] is not None:
        v = str(data["kra_oauth_password"]).strip()
        creds.kra_oauth_password = encrypt_secret(v) if v else None
    if "environment" in data and data["environment"] is not None:
        next_env = _norm_env(str(data["environment"]))
        KraPolicyService.enforce_environment_switch_rules(creds, next_env)
        creds.environment = next_env

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
            KraPolicyService.enforce_enable_rules(creds)
            creds.enabled = True
            if KraProfileService.can_activate_branch(creds):
                creds.activation_status = "active"
        else:
            creds.enabled = False
            creds.connection_status = "disabled"
            creds.activation_status = "disabled"
    creds.activation_blockers = ";".join(KraProfileService.activation_blockers(creds))[:4000]

    db.commit()
    KraAuditService.log_event(
        db,
        company_id=branch.company_id,
        branch_id=branch_id,
        actor_user_id=user.id,
        event_type="branch_credentials_updated",
        event_status="success",
        message="Legacy branch credentials endpoint updated KRA settings",
        metadata={"enabled": bool(creds.enabled), "connection_status": creds.connection_status},
    )
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
        missing.append("Branch kra_bhf_id (KRA Branch Id)")
    if not (creds.device_serial and str(creds.device_serial).strip()):
        missing.append("Branch device_serial")
    u_chk, p_chk = get_oauth_username_password(creds)
    if not u_chk or not p_chk:
        missing.append(
            "KRA OAuth — Consumer Key + Consumer Secret on the branch or ETIMS_APP_CONSUMER_* / ETIMS_OAUTH_* env"
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
        token = get_access_token(
            api_base=base, username=u, password=p, timeout=45, environment=env_eff
        )
    except Exception as e:
        logger.warning("eTIMS OAuth test failed for branch_id=%s", str(branch_id))
        creds.connection_status = "failed"
        creds.last_tested_at = now
        creds.validation_status = "failed"
        creds.last_validation_error = "OAUTH_FAILED"
        creds.token_status = "failed"
        creds.activation_status = "invalid_credentials"
        db.commit()
        raise HTTPException(status_code=502, detail="eTIMS OAuth failed") from e

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
        raise HTTPException(status_code=502, detail="eTIMS request failed") from e

    text = (r.text or "")[:8000]
    summary = summarize_select_init_probe(parsed=parsed, response=r, creds=creds)
    KraProfileService.migrate_branch_secret_fields(creds)
    ok = bool(summary.get("verified"))
    creds.last_tested_at = now
    creds.connection_status = "verified" if ok else "failed"
    creds.validation_status = "passed" if ok else "failed"
    if ok:
        creds.last_validation_at = now
    creds.last_validation_error = None if ok else (
        "INITIALIZE_NO_CMC"
        if summary.get("envelope_ok") and not summary.get("has_cmc_key")
        else "INITIALIZE_FAILED"
    )
    creds.token_last_checked_at = now
    creds.token_status = "ok"
    if ok and KraProfileService.can_activate_branch(creds) and creds.enabled:
        creds.activation_status = "active"
    elif ok:
        creds.activation_status = "validated"
    else:
        creds.activation_status = "connection_failed"
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
        "cmc_extracted_from_response": summary.get("cmc_extracted_from_response"),
        "has_cmc_key": summary.get("has_cmc_key"),
        "result_cd": summary.get("result_cd"),
    }
    try:
        out["response_json"] = parsed
    except Exception:
        out["response_json"] = None
    return out
