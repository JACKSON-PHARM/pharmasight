"""
Formal correlation taxonomy (E5 / E6) — governed group keys for lineage and projections.

Prefixes are stable contracts; semantic meaning is immutable per kind.
"""
from __future__ import annotations

from enum import Enum
from uuid import UUID

from app.finance.doctrine.correlation import (
    CORRELATION_GOVERNANCE,
    validate_correlation_group,
    introspect_correlation_governance,
)


class CorrelationKind(str, Enum):
    INVOICE_LIFECYCLE = "invoice_lifecycle"
    SUPPLIER_INVOICE = "supplier_invoice"
    PAYMENT = "payment"
    SUPPLIER_PAYMENT = "supplier_payment"
    INSURANCE_CLAIM = "insurance_claim"
    INSURANCE_SETTLEMENT = "insurance_settlement"
    PROCUREMENT = "procurement"
    EXPENSE = "expense"
    REPLAY = "replay"
    BACKFILL = "backfill"
    SETTLEMENT_GROUP = "settlement_group"
    TREASURY_FLOW = "treasury_flow"
    POSTING_CANDIDATE = "posting_candidate"
    AUDIT_SESSION = "audit_session"
    PATIENT_FINANCIAL_JOURNEY = "patient_financial_journey"


def build_correlation_group(kind: CorrelationKind, entity_id: str | UUID, *, suffix: str | None = None) -> str:
    eid = str(entity_id)
    base = f"{kind.value}:{eid}"
    if suffix:
        base = f"{base}:{suffix}"
    validate_correlation_group(base, strict=True)
    return base


def correlation_group_for_supplier_invoice(invoice_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.SUPPLIER_INVOICE, invoice_id)


def correlation_group_for_invoice(invoice_id: str | UUID, *, prefix: str | None = None) -> str:
    """Always use invoice_lifecycle — policy-pack prefixes are forbidden (E6)."""
    if prefix and prefix != CorrelationKind.INVOICE_LIFECYCLE.value:
        validate_correlation_group(f"{prefix}:{invoice_id}", strict=True)
    return build_correlation_group(CorrelationKind.INVOICE_LIFECYCLE, invoice_id)


def correlation_group_for_payment(payment_id: str | UUID, *, prefix: str | None = None) -> str:
    if prefix and prefix not in (CorrelationKind.PAYMENT.value, None):
        if prefix == CorrelationKind.SUPPLIER_PAYMENT.value:
            return build_correlation_group(CorrelationKind.SUPPLIER_PAYMENT, payment_id)
        validate_correlation_group(f"{prefix}:{payment_id}", strict=True)
    return build_correlation_group(CorrelationKind.PAYMENT, payment_id)


def correlation_group_for_supplier_payment(payment_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.SUPPLIER_PAYMENT, payment_id)


def correlation_group_for_patient_financial_journey(pfj_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.PATIENT_FINANCIAL_JOURNEY, pfj_id)


def correlation_group_for_insurance_claim(claim_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.INSURANCE_CLAIM, claim_id)


def correlation_group_for_insurance_settlement(settlement_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.INSURANCE_SETTLEMENT, settlement_id)


def correlation_group_for_backfill_run(run_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.BACKFILL, run_id)


def correlation_group_for_replay(failure_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.REPLAY, failure_id)


def correlation_group_for_settlement_group(group_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.SETTLEMENT_GROUP, group_id)


def correlation_group_for_treasury_flow(flow_id: str | UUID) -> str:
    return build_correlation_group(CorrelationKind.TREASURY_FLOW, flow_id)


def introspect_correlation_taxonomy() -> list[dict]:
    governance = {r.kind: r for r in CORRELATION_GOVERNANCE}
    return [
        {
            "kind": k.value,
            "description": _KIND_DESCRIPTIONS.get(k, ""),
            "template": f"{k.value}:<entity_id>",
            "governance": {
                "purpose": governance[k.value].purpose if k.value in governance else "",
                "semantic_immutable": True,
            },
        }
        for k in CorrelationKind
    ]


_KIND_DESCRIPTIONS: dict[CorrelationKind, str] = {
    CorrelationKind.INVOICE_LIFECYCLE: "Commercial customer invoice economic flow",
    CorrelationKind.SUPPLIER_INVOICE: "Supplier payable recognition chain",
    CorrelationKind.PAYMENT: "Customer payment settlement orchestration",
    CorrelationKind.SUPPLIER_PAYMENT: "Supplier disbursement chain",
    CorrelationKind.INSURANCE_CLAIM: "Insurance claim lifecycle lineage",
    CorrelationKind.INSURANCE_SETTLEMENT: "Insurer settlement inflow",
    CorrelationKind.PROCUREMENT: "Purchase fulfillment economic chain",
    CorrelationKind.EXPENSE: "Operating expense recognition",
    CorrelationKind.REPLAY: "Failure replay operation",
    CorrelationKind.BACKFILL: "Controlled lineage reconstruction batch",
    CorrelationKind.SETTLEMENT_GROUP: "Multi-allocation settlement group",
    CorrelationKind.TREASURY_FLOW: "Treasury routing movement stream",
    CorrelationKind.POSTING_CANDIDATE: "Reserved: future accounting staging (no GL in E6)",
    CorrelationKind.AUDIT_SESSION: "Audit investigation grouping",
    CorrelationKind.PATIENT_FINANCIAL_JOURNEY: "Hospital PFJ longitudinal economic lineage",
}
