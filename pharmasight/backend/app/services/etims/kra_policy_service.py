"""Central policy guardrails for KRA control-plane operations."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.models.company import BranchEtimsCredentials
from app.services.etims.kra_profile_service import KraProfileService


class KraPolicyService:
    @staticmethod
    def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if not dt:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def requires_revalidation(creds: BranchEtimsCredentials) -> bool:
        last_val = KraPolicyService._to_utc(getattr(creds, "last_validation_at", None))
        cred_upd = KraPolicyService._to_utc(getattr(creds, "credential_updated_at", None))
        if cred_upd and (not last_val or cred_upd > last_val):
            return True
        return (getattr(creds, "validation_status", "") or "").strip().lower() != "passed"

    @staticmethod
    def enforce_environment_switch_rules(creds: BranchEtimsCredentials, target_environment: str) -> None:
        cur = ((creds.environment or "sandbox").strip().lower() or "sandbox")
        nxt = ((target_environment or "sandbox").strip().lower() or "sandbox")
        if cur == nxt:
            return
        if bool(getattr(creds, "enabled", False)) or KraProfileService.normalize_branch_activation_state(
            creds.activation_status
        ) in ("active", "validated", "validating"):
            raise HTTPException(
                status_code=400,
                detail="Disable branch and move activation to configured before switching environment.",
            )

    @staticmethod
    def enforce_enable_rules(creds: BranchEtimsCredentials) -> None:
        if KraPolicyService.requires_revalidation(creds):
            raise HTTPException(status_code=400, detail="Validation is stale. Re-run branch validation before enabling.")
        if not KraProfileService.can_activate_branch(creds):
            raise HTTPException(status_code=400, detail="Branch cannot be enabled before successful validation.")

