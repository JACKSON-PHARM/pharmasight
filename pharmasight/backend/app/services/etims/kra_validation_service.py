"""Minimal KRA profile validation foundation (token + initialize reachability)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.company import BranchEtimsCredentials, Company
from app.services.etims.branch_credentials import (
    effective_etims_environment,
    get_cmc_key_plain,
    get_oauth_username_password,
)
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials
from app.services.etims.etims_oauth_client import get_access_token
from app.services.etims.kra_profile_service import KraProfileService
from app.services.etims.select_init_osdc_client import (
    post_select_init_osdc_info_with_retries,
    summarize_select_init_probe,
)


class KraValidationService:
    @staticmethod
    def _issue(code: str, category: str, message: str, retryable: bool = False) -> Dict[str, Any]:
        return {
            "code": code,
            "category": category,
            "message": message,
            "retryable": bool(retryable),
        }

    @staticmethod
    def validate_branch_credentials(db: Session, creds: BranchEtimsCredentials) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        company = db.query(Company).filter(Company.id == creds.company_id).first()
        tin = ((creds.client_tax_pin or "") if creds.client_tax_pin else (company.pin if company else "") or "").strip()
        env_eff = effective_etims_environment(creds)

        issues: List[Dict[str, Any]] = []
        result: Dict[str, Any] = {
            "ok": False,
            "checked_at": now.isoformat(),
            "environment": env_eff,
            "checks": {
                "credentials_present": False,
                "oauth_token": False,
                "initialize_reachable": False,
            },
            "issues": issues,
        }

        if not tin:
            issues.append(KraValidationService._issue("TIN_MISSING", "credential_completeness", "Client/company PIN (TIN) is missing"))
        if not ((creds.kra_bhf_id or "").strip()):
            issues.append(KraValidationService._issue("BHF_ID_MISSING", "credential_completeness", "Branch BHF ID is missing"))
        if not ((creds.device_serial or "").strip()):
            issues.append(KraValidationService._issue("DEVICE_SERIAL_MISSING", "credential_completeness", "Device serial is missing"))
        user, password = get_oauth_username_password(creds)
        if not user or not password:
            issues.append(KraValidationService._issue("OAUTH_MISSING", "credential_completeness", "OAuth credentials are missing"))

        if not issues:
            result["checks"]["credentials_present"] = True

        base = api_base_for_branch_credentials(env_eff)
        token = None
        if result["checks"]["credentials_present"]:
            try:
                token = get_access_token(
                    api_base=base,
                    username=user,
                    password=password,
                    timeout=45,
                    environment=env_eff,
                )
                result["checks"]["oauth_token"] = True
            except Exception:
                issues.append(
                    KraValidationService._issue(
                        "OAUTH_FAILED",
                        "token_acquisition",
                        "OAuth token acquisition failed",
                        retryable=True,
                    )
                )

        if token:
            try:
                KraProfileService.migrate_branch_secret_fields(creds)
                cmc_plain = get_cmc_key_plain(creds) or None
                apigee = (creds.apigee_app_id or "").strip() or None
                r, parsed = post_select_init_osdc_info_with_retries(
                    api_base=base,
                    tin=tin,
                    bhf_id=str(creds.kra_bhf_id).strip(),
                    dvc_serial=str(creds.device_serial).strip(),
                    bearer_token=token,
                    apigee_app_id=apigee,
                    cmc_key_plain=cmc_plain,
                    timeout=90,
                )
                summary = summarize_select_init_probe(parsed=parsed, response=r, creds=creds)
                KraProfileService.migrate_branch_secret_fields(creds)
                if summary.get("verified"):
                    result["checks"]["initialize_reachable"] = True
                else:
                    rc = summary.get("result_cd")
                    issues.append(
                        KraValidationService._issue(
                            "INITIALIZE_FAILED",
                            "endpoint_connectivity",
                            f"Initialize endpoint failed (http={r.status_code}, resultCd={rc or 'none'}, "
                            f"has_cmc={summary.get('has_cmc_key')})",
                            retryable=(r.status_code >= 500),
                        )
                    )
            except Exception:
                issues.append(
                    KraValidationService._issue(
                        "INITIALIZE_REQUEST_FAILED",
                        "endpoint_connectivity",
                        "Initialize endpoint request failed",
                        retryable=True,
                    )
                )

        result["ok"] = all(result["checks"].values())
        creds.last_validation_at = now
        creds.validation_status = "passed" if result["ok"] else "failed"
        creds.last_validation_error = None if result["ok"] else "; ".join(i["code"] for i in issues)[:4000]
        creds.token_last_checked_at = now
        creds.token_status = "ok" if result["checks"]["oauth_token"] else "failed"
        if result["ok"]:
            creds.connection_status = "verified"
            creds.last_tested_at = now
            creds.failed_validation_count = 0
            if KraProfileService.normalize_branch_activation_state(creds.activation_status) in (
                "configured",
                "validating",
                "connection_failed",
                "invalid_credentials",
                "not_configured",
            ):
                creds.activation_status = "validated"
        else:
            creds.failed_validation_count = int(getattr(creds, "failed_validation_count", 0) or 0) + 1
            if result["checks"]["oauth_token"]:
                creds.activation_status = "connection_failed"
            else:
                creds.activation_status = "invalid_credentials"
        creds.activation_blockers = ";".join(KraProfileService.activation_blockers(creds))[:4000]
        return result
