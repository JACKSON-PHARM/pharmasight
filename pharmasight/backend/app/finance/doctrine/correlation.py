"""
Correlation governance (E5.5 / E6) — semantic immutability of correlation kinds.

Kinds must never change meaning after release. Use a new kind instead of overloading.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional

# Allowed prefixes — must match CorrelationKind values exactly
REGISTERED_CORRELATION_PREFIXES: FrozenSet[str] = frozenset(
    {
        "invoice_lifecycle",
        "supplier_invoice",
        "payment",
        "supplier_payment",
        "insurance_claim",
        "insurance_settlement",
        "procurement",
        "expense",
        "replay",
        "backfill",
        "settlement_group",
        "treasury_flow",
        "posting_candidate",
        "audit_session",
    }
)

# Policy-pack workflow prefixes are FORBIDDEN — they overload commercial semantics
FORBIDDEN_CORRELATION_PREFIXES: FrozenSet[str] = frozenset(
    {"retail", "wholesale", "hospital", "retail_simple", "wholesale_ar", "hospital_insurance"}
)


@dataclass(frozen=True)
class CorrelationGovernanceRule:
    kind: str
    purpose: str
    semantic_immutable: bool = True
    may_include_settlement: bool = False
    may_include_treasury: bool = False
    may_include_posting: bool = False


CORRELATION_GOVERNANCE: tuple[CorrelationGovernanceRule, ...] = (
    CorrelationGovernanceRule(
        kind="invoice_lifecycle",
        purpose="Commercial customer invoice economic flow (accrual, payment, reversal)",
        may_include_settlement=True,
    ),
    CorrelationGovernanceRule(
        kind="supplier_invoice",
        purpose="Supplier payable recognition chain",
        may_include_settlement=True,
    ),
    CorrelationGovernanceRule(
        kind="payment",
        purpose="Customer payment settlement orchestration",
        may_include_settlement=True,
    ),
    CorrelationGovernanceRule(
        kind="supplier_payment",
        purpose="Supplier disbursement chain",
        may_include_settlement=True,
    ),
    CorrelationGovernanceRule(
        kind="insurance_claim",
        purpose="Insurance claim lifecycle lineage (not insurer GL)",
        may_include_settlement=True,
    ),
    CorrelationGovernanceRule(
        kind="insurance_settlement",
        purpose="Insurer settlement inflow grouping",
        may_include_settlement=True,
    ),
    CorrelationGovernanceRule(
        kind="settlement_group",
        purpose="Multi-allocation payment settlement group",
        may_include_settlement=True,
    ),
    CorrelationGovernanceRule(
        kind="treasury_flow",
        purpose="Treasury routing movement stream (not account balance)",
        may_include_treasury=True,
    ),
    CorrelationGovernanceRule(
        kind="procurement",
        purpose="Purchase fulfillment economic chain",
    ),
    CorrelationGovernanceRule(
        kind="expense",
        purpose="Operating expense recognition",
    ),
    CorrelationGovernanceRule(
        kind="replay",
        purpose="Emission failure replay operation batch",
    ),
    CorrelationGovernanceRule(
        kind="backfill",
        purpose="Controlled lineage reconstruction batch",
    ),
    CorrelationGovernanceRule(
        kind="posting_candidate",
        purpose="Reserved: future accounting staging (no GL writes in E6)",
        may_include_posting=True,
    ),
    CorrelationGovernanceRule(
        kind="audit_session",
        purpose="Audit investigation grouping (read governance)",
    ),
)


def validate_correlation_group(group: Optional[str], *, strict: bool = True) -> None:
    """
    Validate correlation_group format and prefix governance.

    strict=True raises on unknown/forbidden prefixes (emitter path).
  strict=False logs-safe for legacy rows (read path).
    """
    if not group:
        return
    parts = group.split(":", 1)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        if strict:
            raise ValueError(f"invalid correlation_group format: {group}")
        return
    prefix = parts[0].strip().lower()
    if prefix in FORBIDDEN_CORRELATION_PREFIXES:
        raise ValueError(
            f"correlation prefix '{prefix}' is forbidden (policy-pack prefixes overload semantics)"
        )
    if strict and prefix not in REGISTERED_CORRELATION_PREFIXES:
        raise ValueError(f"correlation prefix '{prefix}' is not registered in governance taxonomy")


def introspect_correlation_governance() -> list[dict]:
    return [
        {
            "kind": r.kind,
            "purpose": r.purpose,
            "semantic_immutable": r.semantic_immutable,
            "may_include_settlement": r.may_include_settlement,
            "may_include_treasury": r.may_include_treasury,
            "may_include_posting": r.may_include_posting,
        }
        for r in CORRELATION_GOVERNANCE
    ]
