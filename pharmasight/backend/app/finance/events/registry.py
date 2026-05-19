"""
Canonical financial event type registry (E3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Literal

from app.finance.governance.classification import (
    BRANCH_FINANCE,
    CONFIDENTIAL,
    MANAGEMENT,
)

EconomicDirection = Literal["inflow", "outflow", "accrual", "reduction", "adjustment"]


@dataclass(frozen=True)
class FinancialEventSpec:
    event_type: str
    operational_domain: str
    classification: str
    economic_direction: EconomicDirection
    schema_version: int
    source_entity_type: str
    reversibility: bool
    compensating_event_type: str | None
    idempotency_template: str
    description: str


FINANCIAL_EVENT_REGISTRY: Dict[str, FinancialEventSpec] = {
    "receivable_accrued": FinancialEventSpec(
        event_type="receivable_accrued",
        operational_domain="wholesale",
        classification=BRANCH_FINANCE,
        economic_direction="accrual",
        schema_version=1,
        source_entity_type="sales_invoice",
        reversibility=True,
        compensating_event_type="receivable_accrued_reversal",
        idempotency_template="sales_invoice:{source_entity_id}:receivable_accrued",
        description="Customer receivable recognized when sales invoice is issued/batched.",
    ),
    "receivable_accrued_reversal": FinancialEventSpec(
        event_type="receivable_accrued_reversal",
        operational_domain="wholesale",
        classification=BRANCH_FINANCE,
        economic_direction="reduction",
        schema_version=1,
        source_entity_type="sales_invoice",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="sales_invoice:{source_entity_id}:receivable_accrued_reversal:{reversal_of_event_id}",
        description="Compensating event for receivable_accrued.",
    ),
    "cash_received": FinancialEventSpec(
        event_type="cash_received",
        operational_domain="wholesale",
        classification=BRANCH_FINANCE,
        economic_direction="inflow",
        schema_version=1,
        source_entity_type="customer_payment",
        reversibility=True,
        compensating_event_type="cash_received_reversal",
        idempotency_template="customer_payment:{source_entity_id}:cash_received",
        description="Customer payment received (cash in).",
    ),
    "cash_received_reversal": FinancialEventSpec(
        event_type="cash_received_reversal",
        operational_domain="wholesale",
        classification=BRANCH_FINANCE,
        economic_direction="outflow",
        schema_version=1,
        source_entity_type="customer_payment",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="customer_payment:{source_entity_id}:cash_received_reversal:{reversal_of_event_id}",
        description="Compensating event for cash_received.",
    ),
    "payable_recognized": FinancialEventSpec(
        event_type="payable_recognized",
        operational_domain="procurement",
        classification=MANAGEMENT,
        economic_direction="accrual",
        schema_version=1,
        source_entity_type="supplier_invoice",
        reversibility=True,
        compensating_event_type="payable_recognized_reversal",
        idempotency_template="supplier_invoice:{source_entity_id}:payable_recognized",
        description="Supplier payable recognized when purchase invoice is batched.",
    ),
    "payable_recognized_reversal": FinancialEventSpec(
        event_type="payable_recognized_reversal",
        operational_domain="procurement",
        classification=MANAGEMENT,
        economic_direction="reduction",
        schema_version=1,
        source_entity_type="supplier_invoice",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="supplier_invoice:{source_entity_id}:payable_recognized_reversal:{reversal_of_event_id}",
        description="Compensating event for payable_recognized.",
    ),
    "cash_paid": FinancialEventSpec(
        event_type="cash_paid",
        operational_domain="procurement",
        classification=MANAGEMENT,
        economic_direction="outflow",
        schema_version=1,
        source_entity_type="supplier_payment",
        reversibility=True,
        compensating_event_type="cash_paid_reversal",
        idempotency_template="supplier_payment:{source_entity_id}:cash_paid",
        description="Supplier payment disbursed (cash out).",
    ),
    "cash_paid_reversal": FinancialEventSpec(
        event_type="cash_paid_reversal",
        operational_domain="procurement",
        classification=MANAGEMENT,
        economic_direction="inflow",
        schema_version=1,
        source_entity_type="supplier_payment",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="supplier_payment:{source_entity_id}:cash_paid_reversal:{reversal_of_event_id}",
        description="Compensating event for cash_paid.",
    ),
    "insurance_claim_recognized": FinancialEventSpec(
        event_type="insurance_claim_recognized",
        operational_domain="hospital",
        classification=CONFIDENTIAL,
        economic_direction="accrual",
        schema_version=1,
        source_entity_type="insurance_claim",
        reversibility=True,
        compensating_event_type="insurance_claim_recognized_reversal",
        idempotency_template="insurance_claim:{source_entity_id}:insurance_claim_recognized",
        description="Insurer receivable recognized when claim is submitted or approved.",
    ),
    "insurance_claim_recognized_reversal": FinancialEventSpec(
        event_type="insurance_claim_recognized_reversal",
        operational_domain="hospital",
        classification=CONFIDENTIAL,
        economic_direction="reduction",
        schema_version=1,
        source_entity_type="insurance_claim",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="insurance_claim:{source_entity_id}:insurance_claim_recognized_reversal:{reversal_of_event_id}",
        description="Compensating event for insurance_claim_recognized.",
    ),
    "retail_cash_collected": FinancialEventSpec(
        event_type="retail_cash_collected",
        operational_domain="wholesale",
        classification=BRANCH_FINANCE,
        economic_direction="inflow",
        schema_version=1,
        source_entity_type="sales_invoice",
        reversibility=True,
        compensating_event_type="retail_cash_collected_reversal",
        idempotency_template="sales_invoice:{source_entity_id}:retail_cash_collected",
        description="Retail counter cash collected at invoice batch (no separate AR accrual).",
    ),
    "retail_cash_collected_reversal": FinancialEventSpec(
        event_type="retail_cash_collected_reversal",
        operational_domain="wholesale",
        classification=BRANCH_FINANCE,
        economic_direction="outflow",
        schema_version=1,
        source_entity_type="sales_invoice",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="sales_invoice:{source_entity_id}:retail_cash_collected_reversal:{reversal_of_event_id}",
        description="Compensating event for retail_cash_collected.",
    ),
    "insurance_settlement_received": FinancialEventSpec(
        event_type="insurance_settlement_received",
        operational_domain="hospital",
        classification=BRANCH_FINANCE,
        economic_direction="inflow",
        schema_version=1,
        source_entity_type="insurance_settlement",
        reversibility=True,
        compensating_event_type="insurance_settlement_received_reversal",
        idempotency_template="insurance_settlement:{source_entity_id}:insurance_settlement_received",
        description="Insurance settlement funds received.",
    ),
    "insurance_settlement_received_reversal": FinancialEventSpec(
        event_type="insurance_settlement_received_reversal",
        operational_domain="hospital",
        classification=BRANCH_FINANCE,
        economic_direction="outflow",
        schema_version=1,
        source_entity_type="insurance_settlement",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="insurance_settlement:{source_entity_id}:insurance_settlement_received_reversal:{reversal_of_event_id}",
        description="Compensating event for insurance_settlement_received.",
    ),
    "expense_recognized": FinancialEventSpec(
        event_type="expense_recognized",
        operational_domain="operations",
        classification=MANAGEMENT,
        economic_direction="outflow",
        schema_version=1,
        source_entity_type="expense",
        reversibility=True,
        compensating_event_type="expense_recognized_reversal",
        idempotency_template="expense:{source_entity_id}:expense_recognized",
        description="Operating expense recognized on approval.",
    ),
    "care_value_accrued": FinancialEventSpec(
        event_type="care_value_accrued",
        operational_domain="hospital",
        classification=CONFIDENTIAL,
        economic_direction="accrual",
        schema_version=1,
        source_entity_type="care_charge",
        reversibility=True,
        compensating_event_type="care_value_reversed",
        idempotency_template="care_charge:{source_entity_id}:care_value_accrued",
        description="Accrued care value when clinical trigger completes (not AR recognition).",
    ),
    "care_value_reversed": FinancialEventSpec(
        event_type="care_value_reversed",
        operational_domain="hospital",
        classification=CONFIDENTIAL,
        economic_direction="reduction",
        schema_version=1,
        source_entity_type="care_charge",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="care_charge:{source_entity_id}:care_value_reversed:{reversal_of_event_id}",
        description="Compensating event for care_value_accrued.",
    ),
    "patient_receivable_recognized": FinancialEventSpec(
        event_type="patient_receivable_recognized",
        operational_domain="hospital",
        classification=BRANCH_FINANCE,
        economic_direction="accrual",
        schema_version=1,
        source_entity_type="liability_allocation_line",
        reversibility=True,
        compensating_event_type="patient_receivable_recognized_reversal",
        idempotency_template="liability_allocation_line:{source_entity_id}:patient_receivable_recognized",
        description="Patient AR recognized from obligated liability slice.",
    ),
    "patient_receivable_recognized_reversal": FinancialEventSpec(
        event_type="patient_receivable_recognized_reversal",
        operational_domain="hospital",
        classification=BRANCH_FINANCE,
        economic_direction="reduction",
        schema_version=1,
        source_entity_type="liability_allocation_line",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="liability_allocation_line:{source_entity_id}:patient_receivable_recognized_reversal:{reversal_of_event_id}",
        description="Compensating event for patient_receivable_recognized.",
    ),
    "insurer_receivable_recognized": FinancialEventSpec(
        event_type="insurer_receivable_recognized",
        operational_domain="hospital",
        classification=CONFIDENTIAL,
        economic_direction="accrual",
        schema_version=1,
        source_entity_type="liability_allocation_line",
        reversibility=True,
        compensating_event_type="insurer_receivable_recognized_reversal",
        idempotency_template="liability_allocation_line:{source_entity_id}:insurer_receivable_recognized",
        description="Insurer AR recognized from obligated liability slice (before/with claim packaging).",
    ),
    "insurer_receivable_recognized_reversal": FinancialEventSpec(
        event_type="insurer_receivable_recognized_reversal",
        operational_domain="hospital",
        classification=CONFIDENTIAL,
        economic_direction="reduction",
        schema_version=1,
        source_entity_type="liability_allocation_line",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="liability_allocation_line:{source_entity_id}:insurer_receivable_recognized_reversal:{reversal_of_event_id}",
        description="Compensating event for insurer_receivable_recognized.",
    ),
    "liability_allocated": FinancialEventSpec(
        event_type="liability_allocated",
        operational_domain="hospital",
        classification=CONFIDENTIAL,
        economic_direction="adjustment",
        schema_version=1,
        source_entity_type="liability_allocation_run",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="liability_allocation_run:{source_entity_id}:liability_allocated",
        description="Obligor split applied to accrued care charge (not AR).",
    ),
    "expense_recognized_reversal": FinancialEventSpec(
        event_type="expense_recognized_reversal",
        operational_domain="operations",
        classification=MANAGEMENT,
        economic_direction="inflow",
        schema_version=1,
        source_entity_type="expense",
        reversibility=False,
        compensating_event_type=None,
        idempotency_template="expense:{source_entity_id}:expense_recognized_reversal:{reversal_of_event_id}",
        description="Compensating event for expense_recognized.",
    ),
}


def get_event_spec(event_type: str) -> FinancialEventSpec:
    spec = FINANCIAL_EVENT_REGISTRY.get(event_type)
    if spec is None:
        raise KeyError(f"Unknown financial event type: {event_type}")
    return spec


def list_event_types() -> FrozenSet[str]:
    return frozenset(FINANCIAL_EVENT_REGISTRY.keys())


def introspect_event_registry() -> list[dict]:
    return [
        {
            "event_type": s.event_type,
            "operational_domain": s.operational_domain,
            "classification": s.classification,
            "economic_direction": s.economic_direction,
            "schema_version": s.schema_version,
            "source_entity_type": s.source_entity_type,
            "reversibility": s.reversibility,
            "compensating_event_type": s.compensating_event_type,
            "idempotency_template": s.idempotency_template,
            "description": s.description,
        }
        for s in FINANCIAL_EVENT_REGISTRY.values()
    ]


def build_idempotency_key(spec: FinancialEventSpec, *, source_entity_id: str, reversal_of_event_id: str | None = None) -> str:
    ctx = {"source_entity_id": source_entity_id, "reversal_of_event_id": reversal_of_event_id or ""}
    return spec.idempotency_template.format(**ctx)
