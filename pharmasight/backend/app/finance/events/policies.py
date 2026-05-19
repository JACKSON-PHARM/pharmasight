"""
Event policy packs (E4) — lightweight domain variability without workflow engines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class FinancialEventPolicyPack:
    pack_id: str
    description: str
    enabled_event_types: FrozenSet[str]
    settlement_linking_enabled: bool
    default_correlation_prefix: str


RETAIL_SIMPLE = FinancialEventPolicyPack(
    pack_id="RETAIL_SIMPLE",
    description="Retail cash-first; minimal AR accrual; retail sale cash at batch.",
    enabled_event_types=frozenset(
        {
            "retail_cash_collected",
            "cash_received",
            "expense_recognized",
            "payable_recognized",
            "cash_paid",
        }
    ),
    settlement_linking_enabled=False,
    default_correlation_prefix="retail",
)

WHOLESALE_AR = FinancialEventPolicyPack(
    pack_id="WHOLESALE_AR",
    description="Wholesale AR/AP with settlement linkage.",
    enabled_event_types=frozenset(
        {
            "receivable_accrued",
            "cash_received",
            "payable_recognized",
            "cash_paid",
            "expense_recognized",
        }
    ),
    settlement_linking_enabled=True,
    default_correlation_prefix="wholesale",
)

HOSPITAL_INSURANCE = FinancialEventPolicyPack(
    pack_id="HOSPITAL_INSURANCE",
    description="Hospital insurance claim lineage, settlements, plus core AP.",
    enabled_event_types=frozenset(
        {
            "insurance_claim_recognized",
            "insurance_settlement_received",
            "payable_recognized",
            "cash_paid",
            "expense_recognized",
            "receivable_accrued",
            "cash_received",
            "care_value_accrued",
            "care_value_reversed",
            "liability_allocated",
            "patient_receivable_recognized",
            "insurer_receivable_recognized",
        }
    ),
    settlement_linking_enabled=True,
    default_correlation_prefix="hospital",
)

DEFAULT_POLICY_PACK = WHOLESALE_AR

POLICY_PACKS: dict[str, FinancialEventPolicyPack] = {
    RETAIL_SIMPLE.pack_id: RETAIL_SIMPLE,
    WHOLESALE_AR.pack_id: WHOLESALE_AR,
    HOSPITAL_INSURANCE.pack_id: HOSPITAL_INSURANCE,
}


def resolve_policy_pack(
    *,
    sales_type: str | None = None,
    branch_workflow: str | None = None,
    explicit_pack_id: str | None = None,
) -> FinancialEventPolicyPack:
    if explicit_pack_id and explicit_pack_id in POLICY_PACKS:
        return POLICY_PACKS[explicit_pack_id]
    wf = (branch_workflow or "").strip().upper()
    if wf == "ENCOUNTER" or wf == "HOSPITAL":
        return HOSPITAL_INSURANCE
    st = (sales_type or "").strip().upper()
    if st == "RETAIL":
        return RETAIL_SIMPLE
    return DEFAULT_POLICY_PACK


def event_enabled_for_pack(pack: FinancialEventPolicyPack, event_type: str) -> bool:
    return event_type in pack.enabled_event_types


def introspect_policy_packs() -> list[dict]:
    return [
        {
            "pack_id": p.pack_id,
            "description": p.description,
            "enabled_event_types": sorted(p.enabled_event_types),
            "settlement_linking_enabled": p.settlement_linking_enabled,
            "default_correlation_prefix": p.default_correlation_prefix,
        }
        for p in POLICY_PACKS.values()
    ]


def correlation_group_for_invoice(invoice_id: str, *, prefix: str = "invoice_lifecycle") -> str:
    from app.finance.events.correlation import correlation_group_for_invoice as _cg

    return _cg(invoice_id, prefix=prefix)


def correlation_group_for_payment(payment_id: str, *, prefix: str = "payment") -> str:
    from app.finance.events.correlation import correlation_group_for_payment as _cg

    return _cg(payment_id, prefix=prefix)
