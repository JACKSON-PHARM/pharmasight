"""
Canonical finance API governance registry (E2.5).

Single source of truth for permission, classification, and scope metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional

from app.finance.governance.classification import (
    BRANCH_FINANCE,
    MANAGEMENT,
    OPERATIONAL,
)
from app.finance.governance.permissions import LEGACY_FINANCE_PERMISSION_ALIASES


@dataclass(frozen=True)
class FinanceEndpointGovernanceSpec:
    registry_id: str
    module: str
    route: str
    permission: str
    classification: str
    scope_expectation: str
    branch_scoped: bool
    company_scoped: bool
    legacy_fallback: bool
    notes: str = ""

    @property
    def has_legacy_fallback(self) -> bool:
        return self.legacy_fallback


def _legacy(permission: str) -> bool:
    return permission in LEGACY_FINANCE_PERMISSION_ALIASES


# Canonical registry — update when adding finance-governed routes
FINANCE_GOVERNANCE_REGISTRY: Dict[str, FinanceEndpointGovernanceSpec] = {
    "cashbook.list_entries": FinanceEndpointGovernanceSpec(
        registry_id="cashbook.list_entries",
        module="cashbook",
        route="GET /api/cashbook/entries",
        permission="finance.cashbook.view_branch",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.cashbook.view_branch"),
    ),
    "cashbook.summary": FinanceEndpointGovernanceSpec(
        registry_id="cashbook.summary",
        module="cashbook",
        route="GET /api/cashbook/summary",
        permission="finance.cashbook.view_branch",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.cashbook.view_branch"),
    ),
    "cashbook.backfill": FinanceEndpointGovernanceSpec(
        registry_id="cashbook.backfill",
        module="cashbook",
        route="POST /api/cashbook/backfill",
        permission="finance.cashbook.reconcile_branch",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.cashbook.reconcile_branch"),
    ),
    "reports.item_movement": FinanceEndpointGovernanceSpec(
        registry_id="reports.item_movement",
        module="reports",
        route="GET /api/reports/item-movement",
        permission="finance.reports.operational",
        classification=OPERATIONAL,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.reports.operational"),
    ),
    "reports.batch_movement": FinanceEndpointGovernanceSpec(
        registry_id="reports.batch_movement",
        module="reports",
        route="GET /api/reports/batch-movement",
        permission="finance.reports.operational",
        classification=OPERATIONAL,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.reports.operational"),
    ),
    "items.batch_dropdown": FinanceEndpointGovernanceSpec(
        registry_id="items.batch_dropdown",
        module="items",
        route="GET /api/items/{item_id}/batches",
        permission="finance.reports.operational",
        classification=OPERATIONAL,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.reports.operational"),
    ),
    "sales.gross_profit": FinanceEndpointGovernanceSpec(
        registry_id="sales.gross_profit",
        module="sales",
        route="GET /api/sales/gross-profit",
        permission="finance.reports.management",
        classification=MANAGEMENT,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.reports.management"),
    ),
    "expenses.summary": FinanceEndpointGovernanceSpec(
        registry_id="expenses.summary",
        module="expenses",
        route="GET /api/expenses/summary",
        permission="finance.reports.management",
        classification=MANAGEMENT,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("finance.reports.management"),
    ),
    "customers.aging": FinanceEndpointGovernanceSpec(
        registry_id="customers.aging",
        module="customer_management",
        route="GET /api/customers/reports/aging",
        permission="wholesale.ar.view",
        classification=MANAGEMENT,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("wholesale.ar.view"),
    ),
    "suppliers.aging": FinanceEndpointGovernanceSpec(
        registry_id="suppliers.aging",
        module="supplier_management",
        route="GET /api/suppliers/reports/aging",
        permission="finance.reports.management",
        classification=MANAGEMENT,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("finance.reports.management"),
    ),
    "insurance.providers_list": FinanceEndpointGovernanceSpec(
        registry_id="insurance.providers_list",
        module="insurance_management",
        route="GET /api/insurance/providers",
        permission="hospital.insurance.view",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("hospital.insurance.view"),
    ),
    "insurance.providers_create": FinanceEndpointGovernanceSpec(
        registry_id="insurance.providers_create",
        module="insurance_management",
        route="POST /api/insurance/providers",
        permission="hospital.insurance.manage_providers",
        classification=MANAGEMENT,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("hospital.insurance.manage_providers"),
    ),
    "insurance.providers_update": FinanceEndpointGovernanceSpec(
        registry_id="insurance.providers_update",
        module="insurance_management",
        route="PATCH /api/insurance/providers/{provider_id}",
        permission="hospital.insurance.manage_providers",
        classification=MANAGEMENT,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("hospital.insurance.manage_providers"),
    ),
    "insurance.claims_list": FinanceEndpointGovernanceSpec(
        registry_id="insurance.claims_list",
        module="insurance_management",
        route="GET /api/insurance/claims",
        permission="hospital.insurance.view",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("hospital.insurance.view"),
    ),
    "insurance.claim_status": FinanceEndpointGovernanceSpec(
        registry_id="insurance.claim_status",
        module="insurance_management",
        route="PATCH /api/insurance/claims/{claim_id}/status",
        permission="hospital.insurance.settle",
        classification=MANAGEMENT,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("hospital.insurance.settle"),
    ),
    "insurance.settlement_create": FinanceEndpointGovernanceSpec(
        registry_id="insurance.settlement_create",
        module="insurance_management",
        route="POST /api/insurance/settlements",
        permission="hospital.insurance.settle",
        classification=MANAGEMENT,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("hospital.insurance.settle"),
    ),
    "insurance.settlements_list": FinanceEndpointGovernanceSpec(
        registry_id="insurance.settlements_list",
        module="insurance_management",
        route="GET /api/insurance/settlements",
        permission="hospital.insurance.view",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("hospital.insurance.view"),
    ),
    "insurance.statement": FinanceEndpointGovernanceSpec(
        registry_id="insurance.statement",
        module="insurance_management",
        route="GET /api/insurance/statement",
        permission="hospital.insurance.view",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("hospital.insurance.view"),
    ),
    "insurance.aging": FinanceEndpointGovernanceSpec(
        registry_id="insurance.aging",
        module="insurance_management",
        route="GET /api/insurance/aging",
        permission="hospital.insurance.view",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("hospital.insurance.view"),
    ),
    "treasury.list_accounts": FinanceEndpointGovernanceSpec(
        registry_id="treasury.list_accounts",
        module="finance_treasury",
        route="GET /api/finance/treasury/accounts",
        permission="finance.cashbook.view_branch",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=True,
        company_scoped=True,
        legacy_fallback=_legacy("finance.cashbook.view_branch"),
        notes="Treasury routing dimension — not GL accounts.",
    ),
    "treasury.create_account": FinanceEndpointGovernanceSpec(
        registry_id="treasury.create_account",
        module="finance_treasury",
        route="POST /api/finance/treasury/accounts",
        permission="finance.cashbook.reconcile_branch",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH|COMPANY",
        branch_scoped=True,
        company_scoped=True,
        legacy_fallback=_legacy("finance.cashbook.reconcile_branch"),
    ),
    "treasury.provision_defaults": FinanceEndpointGovernanceSpec(
        registry_id="treasury.provision_defaults",
        module="finance_treasury",
        route="POST /api/finance/treasury/branches/{branch_id}/provision-defaults",
        permission="finance.cashbook.reconcile_branch",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.cashbook.reconcile_branch"),
    ),
    "projections.registry": FinanceEndpointGovernanceSpec(
        registry_id="projections.registry",
        module="finance_projections",
        route="GET /api/finance/projections/registry",
        permission="finance.reports.audit_read",
        classification=BRANCH_FINANCE,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("finance.reports.audit_read"),
        notes="Governed projection catalog — derived views only.",
    ),
    "projections.execute": FinanceEndpointGovernanceSpec(
        registry_id="projections.execute",
        module="finance_projections",
        route="GET /api/finance/projections/{projection_id}",
        permission="finance.reports.management",
        classification=MANAGEMENT,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.reports.management"),
    ),
    "finance.semantics.exposure": FinanceEndpointGovernanceSpec(
        registry_id="finance.semantics.exposure",
        module="finance_semantics",
        route="GET /api/finance/semantics/exposure/{accrual_event_id}",
        permission="finance.reports.management",
        classification=MANAGEMENT,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("finance.reports.management"),
        notes="Derived exposure — non-authoritative.",
    ),
    "finance.doctrine": FinanceEndpointGovernanceSpec(
        registry_id="finance.doctrine",
        module="finance_doctrine",
        route="GET /api/finance/doctrine",
        permission="finance.reports.audit_read",
        classification=BRANCH_FINANCE,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=_legacy("finance.reports.audit_read"),
        notes="Semantic doctrine bundle for projections, correlation, settlement, treasury.",
    ),
    "accounting.doctrine": FinanceEndpointGovernanceSpec(
        registry_id="accounting.doctrine",
        module="finance_accounting",
        route="GET /api/finance/accounting/doctrine",
        permission="finance.gl.view",
        classification=MANAGEMENT,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=False,
        notes="E7 accounting orchestration doctrine — not GL balances.",
    ),
    "accounting.proposal_generate": FinanceEndpointGovernanceSpec(
        registry_id="accounting.proposal_generate",
        module="finance_accounting",
        route="POST /api/finance/accounting/proposals/generate",
        permission="finance.gl.view",
        classification=MANAGEMENT,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=False,
    ),
    "accounting.proposal_post": FinanceEndpointGovernanceSpec(
        registry_id="accounting.proposal_post",
        module="finance_accounting",
        route="POST /api/finance/accounting/proposals/{id}/post",
        permission="finance.gl.post",
        classification=MANAGEMENT,
        scope_expectation="COMPANY",
        branch_scoped=False,
        company_scoped=True,
        legacy_fallback=False,
    ),
    "finance.backfill.run": FinanceEndpointGovernanceSpec(
        registry_id="finance.backfill.run",
        module="finance_backfill",
        route="POST /api/finance/backfill/runs",
        permission="finance.reports.audit_read",
        classification=BRANCH_FINANCE,
        scope_expectation="BRANCH",
        branch_scoped=True,
        company_scoped=False,
        legacy_fallback=_legacy("finance.reports.audit_read"),
        notes="Controlled lineage reconstruction — preserves occurred_at and idempotency.",
    ),
}


def get_governance_spec(registry_id: str) -> FinanceEndpointGovernanceSpec:
    spec = FINANCE_GOVERNANCE_REGISTRY.get(registry_id)
    if spec is None:
        raise KeyError(f"Unknown finance governance registry id: {registry_id}")
    return spec


def list_registry_ids() -> FrozenSet[str]:
    return frozenset(FINANCE_GOVERNANCE_REGISTRY.keys())


def introspect_registry() -> list[dict]:
    """Serializable registry snapshot for admin tooling / audits."""
    return [
        {
            "registry_id": s.registry_id,
            "module": s.module,
            "route": s.route,
            "permission": s.permission,
            "classification": s.classification,
            "scope_expectation": s.scope_expectation,
            "branch_scoped": s.branch_scoped,
            "company_scoped": s.company_scoped,
            "legacy_fallback": s.legacy_fallback,
            "notes": s.notes,
        }
        for s in FINANCE_GOVERNANCE_REGISTRY.values()
    ]
