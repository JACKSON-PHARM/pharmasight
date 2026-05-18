"""
Lineage coverage matrix (Stage 2A.5) — which operational workflows should emit financial events.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Kernel phases (doctrine reference — not calendar truth for every tenant)
KERNEL_PHASE_E3 = "E3"
KERNEL_PHASE_E5 = "E5"


@dataclass(frozen=True)
class WorkflowLineageExpectation:
    workflow_id: str
    operational_module: str
    workflow_label: str
    cashbook_source_type: str
    source_entity_type: str
    expected_event_types: Tuple[str, ...]
    lineage_mandatory: bool
    effective_since_phase: str
    replay_backfill_supported: bool
    hook_active: bool
    notes: str


WORKFLOW_LINEAGE_REGISTRY: Dict[str, WorkflowLineageExpectation] = {
    "expense": WorkflowLineageExpectation(
        workflow_id="expense_approved",
        operational_module="Finance",
        workflow_label="Expense approved",
        cashbook_source_type="expense",
        source_entity_type="expense",
        expected_event_types=("expense_recognized",),
        lineage_mandatory=True,
        effective_since_phase=KERNEL_PHASE_E3,
        replay_backfill_supported=True,
        hook_active=True,
        notes="Emitted on expense approval; cashbook outflow is compatibility tracking.",
    ),
    "supplier_payment": WorkflowLineageExpectation(
        workflow_id="supplier_payment",
        operational_module="Purchases",
        workflow_label="Supplier payment",
        cashbook_source_type="supplier_payment",
        source_entity_type="supplier_payment",
        expected_event_types=("cash_paid",),
        lineage_mandatory=True,
        effective_since_phase=KERNEL_PHASE_E3,
        replay_backfill_supported=True,
        hook_active=True,
        notes="Emitted when supplier payment is recorded.",
    ),
    "sale": WorkflowLineageExpectation(
        workflow_id="retail_sale_cash",
        operational_module="Sales",
        workflow_label="Retail / paid sale (cash movement)",
        cashbook_source_type="sale",
        source_entity_type="sales_invoice",
        expected_event_types=("retail_cash_collected",),
        lineage_mandatory=True,
        effective_since_phase=KERNEL_PHASE_E5,
        replay_backfill_supported=True,
        hook_active=True,
        notes="Cashbook sale rows are cash-collected retail; wholesale credit uses receivable_accrued (not in cash movement projection).",
    ),
    "customer_payment": WorkflowLineageExpectation(
        workflow_id="customer_payment",
        operational_module="Customers",
        workflow_label="Customer payment received",
        cashbook_source_type="customer_payment",
        source_entity_type="customer_payment",
        expected_event_types=("cash_received",),
        lineage_mandatory=True,
        effective_since_phase=KERNEL_PHASE_E3,
        replay_backfill_supported=True,
        hook_active=True,
        notes="Wholesale AR collection; may settle receivable_accrued via settlement links.",
    ),
    "insurance_settlement": WorkflowLineageExpectation(
        workflow_id="insurance_settlement",
        operational_module="Billing",
        workflow_label="Insurance settlement received",
        cashbook_source_type="insurance_settlement",
        source_entity_type="insurance_settlement",
        expected_event_types=("insurance_settlement_received",),
        lineage_mandatory=True,
        effective_since_phase=KERNEL_PHASE_E5,
        replay_backfill_supported=True,
        hook_active=True,
        notes="Emitted when insurance settlement funds are recorded.",
    ),
}


def get_expectation_for_cashbook_source(source_type: str) -> Optional[WorkflowLineageExpectation]:
    return WORKFLOW_LINEAGE_REGISTRY.get((source_type or "").strip().lower())


def introspect_lineage_coverage_matrix() -> List[dict]:
    return [
        {
            "workflow_id": w.workflow_id,
            "operational_module": w.operational_module,
            "workflow_label": w.workflow_label,
            "cashbook_source_type": w.cashbook_source_type,
            "source_entity_type": w.source_entity_type,
            "expected_event_types": list(w.expected_event_types),
            "lineage_mandatory": w.lineage_mandatory,
            "effective_since_phase": w.effective_since_phase,
            "replay_backfill_supported": w.replay_backfill_supported,
            "hook_active": w.hook_active,
            "notes": w.notes,
        }
        for w in WORKFLOW_LINEAGE_REGISTRY.values()
    ]
