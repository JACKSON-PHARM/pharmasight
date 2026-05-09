"""Normalized readiness resolver for KRA branch operations."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.company import Branch, BranchEtimsCredentials
from app.services.etims.kra_policy_service import KraPolicyService
from app.services.etims.kra_profile_service import KraProfileService


class BranchKraReadinessResolver:
    STATES = frozenset(
        {
            "NOT_CONFIGURED",
            "CONFIGURED",
            "REQUIRES_VALIDATION",
            "VALIDATING",
            "READY",
            "DEGRADED",
            "INVALID",
            "DISABLED",
            "ENVIRONMENT_MISMATCH",
            "TOKEN_EXPIRED",
            "ACTIVATION_BLOCKED",
        }
    )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _is_token_expired(creds: BranchEtimsCredentials) -> bool:
        exp = getattr(creds, "token_expires_at", None)
        if not exp:
            return False
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp <= BranchKraReadinessResolver._now()

    @staticmethod
    def _recommended_action(state: str, blockers: List[str], warnings: List[str]) -> str:
        if state == "NOT_CONFIGURED":
            return "Configure required branch credentials, then run validation."
        if state == "DISABLED":
            return "Enable branch only after validation passes."
        if state in ("INVALID", "TOKEN_EXPIRED"):
            return "Update/rotate credentials and run validation."
        if state in ("REQUIRES_VALIDATION", "CONFIGURED", "VALIDATING"):
            return "Run branch validation to refresh readiness."
        if state in ("ENVIRONMENT_MISMATCH", "ACTIVATION_BLOCKED"):
            return "Resolve blockers before enabling processing."
        if state == "DEGRADED":
            return "Branch can operate with caution; investigate warnings."
        if state == "READY":
            return "Ready for activation and async processing."
        if blockers:
            return "Resolve blockers and re-check readiness."
        if warnings:
            return "Review warnings and continue with caution."
        return "No action required."

    @staticmethod
    def resolve(db: Session, *, branch: Branch, creds: BranchEtimsCredentials | None) -> Dict[str, Any]:
        if not creds:
            blockers = ["missing_credentials_row"]
            state = "NOT_CONFIGURED"
            warnings: List[str] = []
            return {
                "branch_id": str(branch.id),
                "company_id": str(branch.company_id),
                "readiness_state": state,
                "can_enable": False,
                "can_process": False,
                "activation_allowed": False,
                "validation_allowed": True,
                "requires_revalidation": True,
                "blockers": blockers,
                "warnings": warnings,
                "recommended_action": BranchKraReadinessResolver._recommended_action(state, blockers, warnings),
                "token_status": "unknown",
                "environment": "sandbox",
                "health_summary": "Branch is not configured for KRA.",
            }

        company_profile = KraProfileService.get_or_create_company_profile(db, company_id=branch.company_id)
        blockers = list(KraProfileService.activation_blockers(creds))
        warnings: List[str] = []

        module_enabled = bool(getattr(company_profile, "module_enabled", False))
        if not module_enabled:
            blockers.append("company_module_disabled")

        if bool(getattr(creds, "enabled", False)) and (creds.connection_status or "").strip().lower() != "verified":
            blockers.append("enabled_without_verified_connection")

        token_expired = BranchKraReadinessResolver._is_token_expired(creds)
        if token_expired:
            blockers.append("token_expired")

        token_status = (creds.token_status or "unknown").strip().lower() or "unknown"
        if token_status == "failed":
            blockers.append("token_invalid")

        requires_revalidation = KraPolicyService.requires_revalidation(creds)
        if requires_revalidation:
            warnings.append("validation_stale")

        failed_count = int(getattr(creds, "failed_validation_count", 0) or 0)
        if failed_count > 0:
            warnings.append("recent_validation_failures")

        default_env = (company_profile.default_environment or "sandbox").strip().lower()
        branch_env = (creds.environment or "sandbox").strip().lower()
        env_mismatch = module_enabled and default_env in ("sandbox", "production") and default_env != branch_env
        if env_mismatch:
            blockers.append("environment_mismatch")

        act = KraProfileService.normalize_branch_activation_state(creds.activation_status)
        val = (creds.validation_status or "unknown").strip().lower()

        state = "CONFIGURED"
        if act == "disabled" or not bool(getattr(creds, "enabled", False)):
            state = "DISABLED"
        elif act == "validating":
            state = "VALIDATING"
        elif token_expired:
            state = "TOKEN_EXPIRED"
        elif env_mismatch:
            state = "ENVIRONMENT_MISMATCH"
        elif val == "failed" or token_status == "failed":
            state = "INVALID"
        elif blockers:
            state = "ACTIVATION_BLOCKED"
        elif requires_revalidation:
            state = "REQUIRES_VALIDATION"
        elif failed_count > 0:
            state = "DEGRADED"
        elif val == "passed" and (creds.connection_status or "").strip().lower() == "verified":
            state = "READY"
        elif act == "not_configured":
            state = "NOT_CONFIGURED"

        can_enable = False
        try:
            KraPolicyService.enforce_enable_rules(creds)
            can_enable = module_enabled and not env_mismatch and not token_expired and token_status != "failed"
        except Exception:
            can_enable = False

        can_process = bool(getattr(creds, "enabled", False)) and state in ("READY", "DEGRADED")

        health_summary = KraProfileService.compute_health_state(creds)
        if state in ("INVALID", "TOKEN_EXPIRED", "ACTIVATION_BLOCKED", "ENVIRONMENT_MISMATCH"):
            health_summary = "blocked"
        elif state == "DEGRADED":
            health_summary = "degraded"
        elif state == "READY":
            health_summary = "healthy"

        return {
            "branch_id": str(branch.id),
            "company_id": str(branch.company_id),
            "readiness_state": state,
            "can_enable": bool(can_enable),
            "can_process": bool(can_process),
            "activation_allowed": bool(can_enable),
            "validation_allowed": act != "disabled",
            "requires_revalidation": bool(requires_revalidation),
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "recommended_action": BranchKraReadinessResolver._recommended_action(state, blockers, warnings),
            "token_status": token_status,
            "environment": branch_env,
            "health_summary": health_summary,
        }

