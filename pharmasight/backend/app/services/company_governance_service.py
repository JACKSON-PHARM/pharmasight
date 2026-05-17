"""
Company governance compiler — single authoritative policy surface for SightOps.

Platform admin writes authoritative fields; runtime consumes compiled governance.
The constitutional transaction engine records transitions under this policy; it does not define it.

Modules are capabilities. Branch invoice_workflow_type is fiscal doctrine. Never infer one from the other.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Branch, Company
from app.models.company_module import CompanyModule
from app.module_metadata import get_core_modules
from app.services.invoice_workflow_policy import doctrine_label, normalize_invoice_workflow_type

if TYPE_CHECKING:
    from app.utils.company_access import CompanyAccess


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

CommercialAccessState = Literal[
    "blocked",
    "active",
    "trial",
    "expired",
    "demo",
    "suspended",
    "legacy_active",
    "onboarding_pending",
]

OrganizationOperatingModel = Literal[
    "PHARMACY_RETAIL",
    "OUTPATIENT_CLINIC",
    "HYBRID_HOSPITAL",
    "ENTERPRISE_NETWORK",
]

BranchFiscalDoctrine = Literal["RETAIL_COUNTER", "ENCOUNTER_CONSOLIDATED", "WHOLESALE_DISTRIBUTION"]

OPERATING_MODEL_VALUES: Tuple[str, ...] = (
    "PHARMACY_RETAIL",
    "OUTPATIENT_CLINIC",
    "HYBRID_HOSPITAL",
    "ENTERPRISE_NETWORK",
)

BRANCH_DOCTRINE_VALUES: Tuple[str, ...] = (
    "RETAIL_COUNTER",
    "ENCOUNTER_CONSOLIDATED",
    "WHOLESALE_DISTRIBUTION",
)

# Preset compilation: capabilities (module names) + default HQ branch doctrine.
_OPERATING_MODEL_PRESETS: Dict[str, Dict[str, Any]] = {
    "PHARMACY_RETAIL": {
        "label": "Pharmacy retail",
        "description": "Retail-first; counter fiscal spine per branch.",
        "modules": ("pharmacy", "inventory", "finance", "procurement", "pos"),
        "hq_workflow": "RETAIL_COUNTER",
        "allowed_branch_doctrines": ("RETAIL_COUNTER", "WHOLESALE_DISTRIBUTION"),
    },
    "OUTPATIENT_CLINIC": {
        "label": "Outpatient clinic",
        "description": "Encounter-first; consolidated billing doctrine on branches.",
        "modules": ("clinic", "patients", "opd", "prescriptions", "billing", "finance"),
        "hq_workflow": "ENCOUNTER_CONSOLIDATED",
        "allowed_branch_doctrines": ("ENCOUNTER_CONSOLIDATED",),
    },
    "HYBRID_HOSPITAL": {
        "label": "Hybrid hospital",
        "description": "Pharmacy + clinic; per-branch fiscal doctrine required.",
        "modules": (
            "pharmacy",
            "inventory",
            "wholesale",
            "clinic",
            "patients",
            "opd",
            "prescriptions",
            "billing",
            "finance",
            "lab",
        ),
        "hq_workflow": "ENCOUNTER_CONSOLIDATED",
        "allowed_branch_doctrines": (
            "RETAIL_COUNTER",
            "ENCOUNTER_CONSOLIDATED",
            "WHOLESALE_DISTRIBUTION",
        ),
    },
    "ENTERPRISE_NETWORK": {
        "label": "Enterprise network",
        "description": "Multi-branch enterprise; mixed doctrines and broad capabilities.",
        "modules": (
            "pharmacy",
            "inventory",
            "wholesale",
            "finance",
            "procurement",
            "pos",
            "billing",
            "clinic",
            "patients",
            "opd",
            "prescriptions",
            "lab",
            "radiology",
            "ipd",
            "emr",
        ),
        "hq_workflow": "RETAIL_COUNTER",
        "allowed_branch_doctrines": (
            "RETAIL_COUNTER",
            "ENCOUNTER_CONSOLIDATED",
            "WHOLESALE_DISTRIBUTION",
        ),
    },
}


def normalize_operating_model(value: object | None) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if s not in OPERATING_MODEL_VALUES:
        raise ValueError(f"Invalid organization_operating_model: {value}")
    return s


def is_legacy_governance_company(company: Optional[Company]) -> bool:
    """
    Legacy grandfather (Option A): unset operating model and unset subscription_status.

    New companies receive explicit operating_model + subscription_status at provisioning.
    """
    if company is None:
        return False
    model = getattr(company, "organization_operating_model", None)
    if model and str(model).strip():
        return False
    sub = (getattr(company, "subscription_status", None) or "").strip().lower()
    if sub:
        return False
    return True


def derive_commercial_access(
    company: Optional[Company],
    *,
    now: Optional[datetime] = None,
) -> CommercialAccessState:
    """Layer 1 — commercial access from company row (explicit + legacy rules)."""
    if company is None:
        return "active"

    if not bool(getattr(company, "is_active", True)):
        return "blocked"

    sub = (getattr(company, "subscription_status", None) or "").strip().lower()

    if sub == "active":
        return "active"
    if sub in ("suspended", "canceled", "cancelled", "past_due"):
        return "suspended"

    trial_expires_at = getattr(company, "trial_expires_at", None)

    if sub == "demo":
        if trial_expires_at is not None:
            n = now or now_utc()
            end = trial_expires_at
            if getattr(end, "tzinfo", None) is None:
                end = end.replace(tzinfo=timezone.utc)
            if n >= end:
                return "expired"
        return "demo"

    if sub in ("trialing", "trial") or trial_expires_at is not None:
        if trial_expires_at is None and sub in ("trialing", "trial"):
            return "trial"
        if trial_expires_at is not None:
            n = now or now_utc()
            end = trial_expires_at
            if getattr(end, "tzinfo", None) is None:
                end = end.replace(tzinfo=timezone.utc)
            return "trial" if n < end else "expired"

    if is_legacy_governance_company(company):
        return "legacy_active"

    return "onboarding_pending"


def map_commercial_access_to_company_access(state: CommercialAccessState) -> "CompanyAccess":
    from app.utils.company_access import CompanyAccess

    """
    Map governance commercial state → legacy CompanyAccess for API enforcement.

    ``active`` commercial subscription ignores ``trial_expires_at`` (paid / operator-approved).
    """
    if state in ("active", "legacy_active"):
        return "active"
    if state in ("trial", "demo"):
        return "trial"
    if state == "expired":
        return "expired"
    if state in ("blocked", "suspended", "onboarding_pending"):
        return "blocked"
    return "blocked"


def subscription_access_for_company(
    company: Optional[Company],
    *,
    now: Optional[datetime] = None,
) -> str:
    """
    Map company row → SPA ``subscription_access`` (auth/me, subscription_ui.js).

    - full: paid/active commercial access
    - trial: in trial/demo window
    - trial_expired: trial ended, not commercially active
    - blocked: inactive, suspended, or onboarding without access
    """
    state = derive_commercial_access(company, now=now)
    if state in ("active", "legacy_active"):
        return "full"
    if state in ("trial", "demo"):
        return "trial"
    if state == "expired":
        return "trial_expired"
    return "blocked"


def governance_access_display(state: CommercialAccessState) -> Dict[str, Any]:
    labels = {
        "active": ("Active", "success", False),
        "trial": ("Trial", "info", False),
        "expired": ("Trial expired", "danger", False),
        "demo": ("Demo", "warning", False),
        "suspended": ("Suspended", "danger", False),
        "blocked": ("Blocked", "danger", False),
        "legacy_active": ("Legacy active", "warning", True),
        "onboarding_pending": ("Onboarding pending", "warning", True),
    }
    label, tone, legacy = labels.get(state, (state, "secondary", False))
    return {
        "state": state,
        "label": label,
        "tone": tone,
        "uses_legacy_fallback": legacy,
    }


def _company_module_rows(db: Session, company_id: UUID) -> List[CompanyModule]:
    return (
        db.query(CompanyModule)
        .filter(CompanyModule.company_id == company_id)
        .order_by(CompanyModule.module_name.asc())
        .all()
    )


def compile_module_entitlements(
    db: Session,
    company_id: UUID,
    *,
    company: Optional[Company] = None,
) -> Dict[str, Any]:
    """
    Layer 2 — effective licensed capabilities.

    Legacy companies without module rows: pharmacy enabled only (grandfather).
    Non-legacy: explicit rows only (no implicit pharmacy).
    """
    company = company or db.query(Company).filter(Company.id == company_id).first()
    rows = _company_module_rows(db, company_id)
    core = {m.lower() for m in get_core_modules(db)}
    legacy = is_legacy_governance_company(company)
    has_license_row = any(
        r.module_name.lower() not in core for r in rows
    )

    explicit: Dict[str, bool] = {}
    for r in rows:
        name = (r.module_name or "").strip().lower()
        if name and name not in core:
            explicit[name] = bool(r.is_enabled)

    effective: Dict[str, bool] = dict(explicit)
    if legacy and not has_license_row:
        effective["pharmacy"] = True

    return {
        "explicit": explicit,
        "effective": effective,
        "uses_legacy_module_fallback": legacy and not has_license_row,
        "core_modules": sorted(core),
    }


def is_module_enabled_compiled(
    db: Session,
    company_id: UUID,
    module_name: str,
    *,
    company: Optional[Company] = None,
) -> bool:
    normalized = (module_name or "").strip().lower()
    if not normalized:
        return False
    core = {m.lower() for m in get_core_modules(db)}
    if normalized in core:
        return True
    ent = compile_module_entitlements(db, company_id, company=company)
    return bool(ent["effective"].get(normalized, False))


def allowed_branch_doctrines_for_model(
    operating_model: Optional[str],
) -> Tuple[str, ...]:
    if not operating_model:
        return BRANCH_DOCTRINE_VALUES
    preset = _OPERATING_MODEL_PRESETS.get(operating_model.upper())
    if not preset:
        return BRANCH_DOCTRINE_VALUES
    return tuple(preset.get("allowed_branch_doctrines") or BRANCH_DOCTRINE_VALUES)


def validate_branch_doctrine_for_company(
    company: Optional[Company],
    doctrine: str,
) -> List[str]:
    """Non-blocking warnings (B1); Phase 2 may hard-enforce."""
    warnings: List[str] = []
    model = (getattr(company, "organization_operating_model", None) or "").strip().upper() or None
    doc = normalize_invoice_workflow_type(doctrine)
    allowed = allowed_branch_doctrines_for_model(model)
    if doc not in allowed:
        warnings.append(
            f"Branch doctrine {doc} is not typical for operating model {model or '(unset)'}; "
            f"expected one of: {', '.join(allowed)}."
        )
    return warnings


def compile_branch_governance(
    db: Session,
    company_id: UUID,
    *,
    company: Optional[Company] = None,
) -> List[Dict[str, Any]]:
    """Layer 4 — branch fiscal doctrine summary."""
    company = company or db.query(Company).filter(Company.id == company_id).first()
    model = (getattr(company, "organization_operating_model", None) or "").strip().upper() or None
    allowed = allowed_branch_doctrines_for_model(model)
    branches = (
        db.query(Branch)
        .filter(Branch.company_id == company_id)
        .order_by(Branch.is_hq.desc(), Branch.name.asc())
        .all()
    )
    out: List[Dict[str, Any]] = []
    for b in branches:
        doctrine = normalize_invoice_workflow_type(getattr(b, "invoice_workflow_type", None))
        warnings = validate_branch_doctrine_for_company(company, doctrine)
        out.append(
            {
                "branch_id": str(b.id),
                "name": b.name,
                "code": b.code,
                "is_hq": bool(b.is_hq),
                "is_active": bool(b.is_active),
                "invoice_workflow_type": doctrine,
                "doctrine_label": doctrine_label(doctrine),
                "governance_warnings": warnings,
                "doctrine_allowed_for_model": doctrine in allowed,
            }
        )
    return out


def compile_constitutional_observability(db: Session, company_id: UUID) -> Dict[str, Any]:
    """Layer 5 — read-only constitutional spine visibility."""
    try:
        from app.models.commercial_transaction import CommercialTransaction

        total = (
            db.query(CommercialTransaction)
            .filter(CommercialTransaction.company_id == company_id)
            .count()
        )
        by_state_rows = (
            db.query(
                CommercialTransaction.constitutional_state,
                CommercialTransaction.id,
            )
            .filter(CommercialTransaction.company_id == company_id)
            .all()
        )
        counts: Dict[str, int] = {}
        for state, _ in by_state_rows:
            key = str(state or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return {
            "commercial_transaction_count": total,
            "constitutional_state_counts": counts,
        }
    except Exception:
        return {
            "commercial_transaction_count": 0,
            "constitutional_state_counts": {},
        }


def detect_governance_problems(
    *,
    commercial_access: CommercialAccessState,
    operating_model: Optional[str],
    legacy: bool,
    module_entitlements: Dict[str, Any],
    branches: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    problems: List[Dict[str, str]] = []
    if legacy:
        problems.append(
            {
                "severity": "warning",
                "code": "legacy_governance",
                "message": "Legacy governance fallback is active (unset operating model and subscription status). Migrate to explicit policy.",
            }
        )
    if commercial_access == "onboarding_pending":
        problems.append(
            {
                "severity": "warning",
                "code": "onboarding_pending",
                "message": "Commercial access is onboarding_pending — set subscription status and operating model.",
            }
        )
    if not operating_model and not legacy:
        problems.append(
            {
                "severity": "warning",
                "code": "missing_operating_model",
                "message": "Organization operating model is not set.",
            }
        )
    if module_entitlements.get("uses_legacy_module_fallback"):
        problems.append(
            {
                "severity": "info",
                "code": "legacy_module_fallback",
                "message": "Licensed capabilities use legacy pharmacy default (no explicit module rows).",
            }
        )
    for b in branches:
        if b.get("governance_warnings"):
            for w in b["governance_warnings"]:
                problems.append(
                    {
                        "severity": "warning",
                        "code": "branch_doctrine_mismatch",
                        "message": f"{b.get('name')}: {w}",
                    }
                )
        if not b.get("doctrine_allowed_for_model", True):
            problems.append(
                {
                    "severity": "warning",
                    "code": "branch_doctrine_not_allowed",
                    "message": f"Branch {b.get('name')} doctrine may conflict with operating model.",
                }
            )
    return problems


def compile_governance_profile(
    db: Session,
    company_id: UUID,
    *,
    company: Optional[Company] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Full compiled governance for admin and runtime summaries."""
    company = company or db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise ValueError("Company not found")

    commercial_access = derive_commercial_access(company, now=now)
    legacy = is_legacy_governance_company(company)
    operating_model = normalize_operating_model(getattr(company, "organization_operating_model", None))
    modules = compile_module_entitlements(db, company_id, company=company)
    branches = compile_branch_governance(db, company_id, company=company)
    constitutional = compile_constitutional_observability(db, company_id)
    problems = detect_governance_problems(
        commercial_access=commercial_access,
        operating_model=operating_model,
        legacy=legacy,
        module_entitlements=modules,
        branches=branches,
    )

    preset_meta = _OPERATING_MODEL_PRESETS.get(operating_model or "", {})

    return {
        "company_id": str(company_id),
        "company_name": company.name,
        "is_active": bool(company.is_active),
        "commercial_access": governance_access_display(commercial_access),
        "runtime_company_access": map_commercial_access_to_company_access(commercial_access),
        "uses_legacy_governance": legacy,
        "organization_operating_model": operating_model,
        "operating_model_label": preset_meta.get("label") if operating_model else None,
        "operating_model_description": preset_meta.get("description") if operating_model else None,
        "subscription_plan": company.subscription_plan,
        "subscription_status": company.subscription_status,
        "trial_expires_at": company.trial_expires_at.isoformat() if company.trial_expires_at else None,
        "kra_enabled": bool(getattr(company, "kra_enabled", False)),
        "module_entitlements": modules,
        "branch_governance": branches,
        "constitutional_observability": constitutional,
        "governance_problems": problems,
        "available_operating_models": [
            {"value": k, "label": v["label"], "description": v["description"]}
            for k, v in _OPERATING_MODEL_PRESETS.items()
        ],
        "available_branch_doctrines": list(BRANCH_DOCTRINE_VALUES),
    }


def apply_operating_model_preset(
    db: Session,
    company_id: UUID,
    operating_model: str,
    *,
    apply_modules: bool = True,
    apply_hq_doctrine: bool = True,
) -> Dict[str, Any]:
    """
    Policy compilation: set operating model, write module rows, default HQ branch doctrine.
    """
    model = normalize_operating_model(operating_model)
    if not model:
        raise ValueError("operating_model is required")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise ValueError("Company not found")

    preset = _OPERATING_MODEL_PRESETS[model]
    company.organization_operating_model = model

    if apply_modules:
        desired: Set[str] = {m.lower() for m in preset["modules"]}
        existing = _company_module_rows(db, company_id)
        seen: Set[str] = set()
        for r in existing:
            name = (r.module_name or "").strip().lower()
            if not name:
                continue
            seen.add(name)
            r.is_enabled = name in desired
        for name in desired:
            if name in seen:
                continue
            db.add(
                CompanyModule(
                    company_id=company_id,
                    module_name=name,
                    is_enabled=True,
                )
            )

    if apply_hq_doctrine:
        hq = (
            db.query(Branch)
            .filter(Branch.company_id == company_id, Branch.is_hq.is_(True))
            .first()
        )
        if hq is None:
            hq = (
                db.query(Branch)
                .filter(Branch.company_id == company_id)
                .order_by(Branch.created_at.asc())
                .first()
            )
        if hq is not None:
            hq.invoice_workflow_type = preset["hq_workflow"]

    db.flush()
    return compile_governance_profile(db, company_id, company=company)


def provision_governance_defaults(
    db: Session,
    company: Company,
    *,
    operating_model: str = "PHARMACY_RETAIL",
    subscription_status: str = "trialing",
) -> None:
    """Called for NEW companies — explicit governance, no null semantics."""
    company.organization_operating_model = normalize_operating_model(operating_model)
    if not (company.subscription_status or "").strip():
        company.subscription_status = subscription_status
    apply_operating_model_preset(
        db,
        company.id,
        operating_model,
        apply_modules=True,
        apply_hq_doctrine=True,
    )


def set_branch_fiscal_doctrine(
    db: Session,
    branch_id: UUID,
    doctrine: str,
    *,
    enforce: bool = False,
) -> Tuple[Branch, List[str]]:
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise ValueError("Branch not found")
    company = db.query(Company).filter(Company.id == branch.company_id).first()
    normalized = normalize_invoice_workflow_type(doctrine)
    warnings = validate_branch_doctrine_for_company(company, normalized)
    if enforce and warnings:
        raise ValueError(warnings[0])
    branch.invoice_workflow_type = normalized
    db.flush()
    return branch, warnings
