"""
E5 governed projections, treasury doctrine, correlation, and event expansion tests.
"""
from pathlib import Path

from app.finance.events.correlation import CorrelationKind, build_correlation_group, introspect_correlation_taxonomy
from app.finance.events.policies import HOSPITAL_INSURANCE, POLICY_PACKS, RETAIL_SIMPLE, resolve_policy_pack
from app.finance.events.registry import FINANCIAL_EVENT_REGISTRY
from app.finance.projections.registry import PROJECTION_REGISTRY, introspect_projection_registry
from app.finance.treasury.doctrine import FORBIDDEN_TREASURY_FIELD_NAMES, ROUTING_TYPES, assert_treasury_field_safe


def test_treasury_routing_types_not_accounting():
    assert "till" in ROUTING_TYPES
    assert "asset" not in ROUTING_TYPES
    assert "liability" not in ROUTING_TYPES


def test_treasury_forbids_accounting_field_names():
    for name in ("debit", "running_balance", "gl_account"):
        try:
            assert_treasury_field_safe(name)
            assert False, f"should reject {name}"
        except ValueError:
            pass
    assert_treasury_field_safe("routing_type") is None


def test_projection_registry_declares_rebuildability():
    for spec in PROJECTION_REGISTRY.values():
        assert spec.replay_rebuildable is True
        assert spec.lineage_source
        assert spec.authoritative is False
        assert spec.persists_balances is False
        assert spec.lineage_event_types or any(
            k in spec.lineage_source for k in ("integrity", "settlement")
        )


def test_projections_not_authoritative_in_registry_notes():
    snap = introspect_projection_registry()
    treasury = next(p for p in snap if p["projection_id"] == "treasury_routing_snapshot")
    assert "balance" in treasury.get("notes", "").lower() or "movement" in treasury.get("notes", "").lower()


def test_correlation_taxonomy_complete():
    kinds = {k["kind"] for k in introspect_correlation_taxonomy()}
    assert CorrelationKind.BACKFILL.value in kinds
    assert CorrelationKind.INSURANCE_CLAIM.value in kinds


def test_correlation_group_format():
    g = build_correlation_group(CorrelationKind.INSURANCE_CLAIM, "abc-123")
    assert g == "insurance_claim:abc-123"


def test_retail_policy_includes_retail_cash_collected():
    pack = resolve_policy_pack(sales_type="RETAIL")
    assert "retail_cash_collected" in pack.enabled_event_types
    assert "receivable_accrued" not in pack.enabled_event_types


def test_hospital_policy_includes_claim_recognized():
    pack = resolve_policy_pack(branch_workflow="HOSPITAL")
    assert "insurance_claim_recognized" in pack.enabled_event_types


def test_new_event_types_no_debit_credit():
    for et in ("insurance_claim_recognized", "retail_cash_collected"):
        spec = FINANCIAL_EVENT_REGISTRY[et]
        assert spec.economic_direction in ("accrual", "inflow", "outflow", "reduction", "adjustment")
        forbidden = ("debit", "credit")
        for bad in forbidden:
            assert bad not in spec.event_type


def test_e5_modules_exist():
    root = Path(__file__).resolve().parent.parent / "app/finance"
    assert (root / "projections" / "engine.py").is_file()
    assert (root / "treasury" / "doctrine.py").is_file()
    assert (root / "events" / "backfill.py").is_file()
    assert (root / "events" / "correlation.py").is_file()


def test_policy_packs_count_unchanged_base():
    assert len(POLICY_PACKS) == 3
    assert HOSPITAL_INSURANCE.pack_id in POLICY_PACKS
    assert RETAIL_SIMPLE.pack_id in POLICY_PACKS
