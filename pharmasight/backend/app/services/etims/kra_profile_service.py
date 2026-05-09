"""KRA tenant/branch profile helpers (masked reads + compatibility-safe updates)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Branch, BranchEtimsCredentials
from app.models.company_kra_profile import CompanyKraProfile
from app.services.etims.credential_crypto import ensure_encrypted_secret


class KraProfileService:
    BRANCH_ACTIVATION_STATES = frozenset(
        {
            "not_configured",
            "configured",
            "validating",
            "validated",
            "active",
            "invalid_credentials",
            "connection_failed",
            "disabled",
        }
    )

    @staticmethod
    def normalize_branch_activation_state(state: str | None) -> str:
        s = (state or "").strip().lower()
        if s in KraProfileService.BRANCH_ACTIVATION_STATES:
            return s
        return "not_configured"

    @staticmethod
    def can_activate_branch(row: BranchEtimsCredentials) -> bool:
        return (
            (row.validation_status or "").strip().lower() == "passed"
            and (row.connection_status or "").strip().lower() == "verified"
            and bool((row.kra_bhf_id or "").strip())
            and bool((row.device_serial or "").strip())
            and bool((row.client_tax_pin or "").strip())
        )

    @staticmethod
    def activation_blockers(row: BranchEtimsCredentials) -> list[str]:
        blockers: list[str] = []
        if not bool((row.kra_bhf_id or "").strip()):
            blockers.append("missing_bhf_id")
        if not bool((row.device_serial or "").strip()):
            blockers.append("missing_device_serial")
        if not bool((row.client_tax_pin or "").strip()):
            blockers.append("missing_client_tax_pin")
        if not bool((row.consumer_key or "").strip()):
            blockers.append("missing_consumer_key")
        if not bool((row.consumer_secret_encrypted or "").strip()):
            blockers.append("missing_consumer_secret")
        if (row.validation_status or "").strip().lower() != "passed":
            blockers.append("validation_not_passed")
        if (row.connection_status or "").strip().lower() != "verified":
            blockers.append("connection_not_verified")
        return blockers

    @staticmethod
    def compute_health_state(row: BranchEtimsCredentials) -> str:
        act = KraProfileService.normalize_branch_activation_state(row.activation_status)
        if act == "disabled":
            return "disabled"
        if act == "active" and (row.validation_status or "").strip().lower() == "passed":
            return "healthy"
        if (row.validation_status or "").strip().lower() == "failed":
            return "degraded"
        if act in ("configured", "validating", "validated"):
            return "pending_activation"
        return "not_ready"

    @staticmethod
    def get_or_create_company_profile(db: Session, *, company_id: UUID) -> CompanyKraProfile:
        row = db.query(CompanyKraProfile).filter(CompanyKraProfile.company_id == company_id).first()
        if row:
            return row
        row = CompanyKraProfile(company_id=company_id)
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def migrate_company_secret_fields(row: CompanyKraProfile) -> bool:
        changed = False
        enc = ensure_encrypted_secret(getattr(row, "integrator_pin", None))
        if enc != row.integrator_pin:
            row.integrator_pin = enc
            changed = True
        return changed

    @staticmethod
    def get_or_create_branch_profile(db: Session, *, branch_id: UUID) -> BranchEtimsCredentials:
        row = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch_id).first()
        if row:
            return row
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise ValueError("Branch not found")
        row = BranchEtimsCredentials(
            branch_id=branch_id,
            company_id=branch.company_id,
            environment="sandbox",
            enabled=False,
            etims_solution="OSCU",
            connection_status="not_configured",
            activation_status="not_configured",
            validation_status="unknown",
            token_status="unknown",
            credential_version=1,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def migrate_branch_secret_fields(row: BranchEtimsCredentials) -> bool:
        changed = False
        for field in ("cmc_key_encrypted", "kra_oauth_password", "consumer_secret_encrypted", "integrator_pin"):
            cur = getattr(row, field, None)
            enc = ensure_encrypted_secret(cur)
            if enc != cur:
                setattr(row, field, enc)
                changed = True
        return changed

    @staticmethod
    def serialize_company_profile_masked(row: CompanyKraProfile) -> Dict[str, Any]:
        return {
            "company_id": str(row.company_id),
            "module_enabled": bool(row.module_enabled),
            "default_environment": row.default_environment or "sandbox",
            "has_integrator_pin": bool((row.integrator_pin or "").strip()),
            "onboarding_status": row.onboarding_status or "draft",
            "activation_status": row.activation_status or "inactive",
            "last_health_check_at": row.last_health_check_at.isoformat() if row.last_health_check_at else None,
            "last_successful_sync_at": row.last_successful_sync_at.isoformat() if row.last_successful_sync_at else None,
            "last_validation_status": row.last_validation_status,
            "last_validation_error": row.last_validation_error,
            "credential_updated_at": row.credential_updated_at.isoformat() if row.credential_updated_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def serialize_branch_profile_masked(row: BranchEtimsCredentials) -> Dict[str, Any]:
        return {
            "branch_id": str(row.branch_id),
            "company_id": str(row.company_id),
            "environment": (row.environment or "sandbox").strip().lower() or "sandbox",
            "enabled": bool(row.enabled),
            "connection_status": row.connection_status or "not_configured",
            "activation_status": row.activation_status or "draft",
            "validation_status": row.validation_status or "unknown",
            "health_state": KraProfileService.compute_health_state(row),
            "last_validation_error": row.last_validation_error,
            "last_validation_at": row.last_validation_at.isoformat() if row.last_validation_at else None,
            "last_successful_sync_at": row.last_successful_sync_at.isoformat() if row.last_successful_sync_at else None,
            "token_status": row.token_status or "unknown",
            "token_last_checked_at": row.token_last_checked_at.isoformat() if row.token_last_checked_at else None,
            "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
            "kra_bhf_id": row.kra_bhf_id,
            "device_serial": row.device_serial,
            "apigee_app_id": row.apigee_app_id,
            "client_tax_pin": row.client_tax_pin,
            "has_cmc_key": bool((row.cmc_key_encrypted or "").strip()),
            "has_consumer_key": bool((row.consumer_key or "").strip()),
            "has_consumer_secret": bool((row.consumer_secret_encrypted or "").strip()),
            "has_oauth_username": bool((row.kra_oauth_username or "").strip()),
            "has_oauth_password": bool((row.kra_oauth_password or "").strip()),
            "has_integrator_pin": bool((row.integrator_pin or "").strip()),
            "credential_version": int(row.credential_version or 1),
            "credential_updated_at": row.credential_updated_at.isoformat() if row.credential_updated_at else None,
            "failed_validation_count": int(getattr(row, "failed_validation_count", 0) or 0),
            "token_expires_at": row.token_expires_at.isoformat() if getattr(row, "token_expires_at", None) else None,
            "activation_blockers": KraProfileService.activation_blockers(row),
            "revalidation_required": (
                bool(row.credential_updated_at and (not row.last_validation_at or row.credential_updated_at > row.last_validation_at))
                or (row.validation_status or "").strip().lower() != "passed"
            ),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def touch_credential_update(branch_row: BranchEtimsCredentials) -> None:
        branch_row.credential_updated_at = datetime.now(timezone.utc)
        branch_row.credential_version = int(branch_row.credential_version or 0) + 1
        branch_row.validation_status = "unknown"
        branch_row.last_validation_error = None
        branch_row.token_status = "unknown"
        cur = KraProfileService.normalize_branch_activation_state(branch_row.activation_status)
        if cur == "active":
            branch_row.activation_status = "configured"
        elif cur == "not_configured":
            branch_row.activation_status = "configured"
