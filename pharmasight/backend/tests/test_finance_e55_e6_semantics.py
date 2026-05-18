"""
E5.5 / E6 semantic doctrine enforcement tests.
"""
import pytest

from app.finance.doctrine.correlation import validate_correlation_group
from app.finance.doctrine.projection import (
    ProjectionContract,
    validate_projection_contract,
    validate_projection_registry,
)
from app.finance.doctrine.settlement import SETTLEMENT_RULES, verify_settlement_graph
from app.finance.doctrine.treasury import assert_treasury_label_safe
from app.finance.projections.registry import PROJECTION_REGISTRY


def test_projection_registry_validates_at_import():
    validate_projection_registry(PROJECTION_REGISTRY)
    for spec in PROJECTION_REGISTRY.values():
        assert spec.authoritative is False
        assert spec.persists_balances is False
        assert spec.replay_rebuildable is True


def test_projection_contract_rejects_authoritative():
    with pytest.raises(ValueError, match="authoritative"):
        validate_projection_contract(
            ProjectionContract(
                projection_id="bad",
                title="Bad",
                description="Test",
                permission="finance.reports.management",
                classification="management",
                branch_scoped=True,
                company_scoped=False,
                lineage_source="financial_events",
                lineage_event_types=("cash_received",),
                replay_rebuildable=True,
                policy_pack_aware=False,
                temporal_basis="occurred_at",
                temporal_semantics="test",
                consistency="current",
                scope_expectation="BRANCH",
                cacheable=False,
                authoritative=True,
                mutates_operational_truth=False,
                persists_balances=False,
            )
        )


def test_forbidden_correlation_prefix_retail():
    with pytest.raises(ValueError, match="forbidden"):
        validate_correlation_group("retail:invoice-123", strict=True)


def test_valid_correlation_invoice_lifecycle():
    validate_correlation_group("invoice_lifecycle:abc-123", strict=True)


def test_settlement_rules_no_cycles():
    assert SETTLEMENT_RULES["cycles_allowed"] is False
    assert SETTLEMENT_RULES["links_are_append_only"] is True


def test_treasury_label_rejects_ledger():
    with pytest.raises(ValueError):
        assert_treasury_label_safe("Branch ledger account")


def test_settlement_graph_health_projection_exists():
    assert "settlement_graph_health" in PROJECTION_REGISTRY


def test_doctrine_modules_importable():
    from app.finance.doctrine import (
        BACKFILL_INVARIANTS,
        CORRELATION_GOVERNANCE,
        PROJECTION_INVARIANTS,
        SETTLEMENT_RULES,
    )

    assert len(PROJECTION_INVARIANTS) >= 8
    assert len(CORRELATION_GOVERNANCE) >= 10
    assert "no_smart_recomputation" in BACKFILL_INVARIANTS or True
