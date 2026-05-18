"""
E6.5 semantic stabilization tests.
"""
from app.finance.doctrine.causal_lineage import sort_failures_for_replay
from app.finance.doctrine.economic_position import ALL_EXPOSURE_STATES, EXPOSURE_STATE_OPEN
from app.finance.doctrine.orchestration_boundary import E7_FORBIDDEN_ON_LINEAGE, EVENTS_ARE_NOT
from app.finance.doctrine.projection_freshness import PROJECTION_FRESHNESS, build_freshness_envelope
from app.finance.doctrine.settlement import SETTLEMENT_RULES, would_create_settlement_cycle


def test_economic_position_states_defined():
    assert EXPOSURE_STATE_OPEN in ALL_EXPOSURE_STATES
    assert len(ALL_EXPOSURE_STATES) >= 6


def test_settlement_prevent_cycles_before_insert():
    assert SETTLEMENT_RULES["prevent_cycles_before_insert"] is True
    assert SETTLEMENT_RULES["cycles_allowed"] is False


def test_projection_freshness_not_cacheable():
    for spec in PROJECTION_FRESHNESS.values():
        assert spec.cacheable is False


def test_freshness_envelope_disclaimer():
    env = build_freshness_envelope("branch_cash_movement", replay_occurred=True)
    assert env["authoritative"] is False if "authoritative" in env else True
    assert "disclaimer" in env
    assert env["invalidated_by_replay"] is True


def test_orchestration_boundary_forbids_lineage_mutation():
    assert any("financial_events" in x for x in E7_FORBIDDEN_ON_LINEAGE)
    assert "accounting_truth" in EVENTS_ARE_NOT


def test_replay_sort_ordering():
    class F:
        def __init__(self, o, c, i):
            self.occurred_at = o
            self.created_at = c
            self.idempotency_key = i

    from datetime import datetime, timezone

    a = F(datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 2, tzinfo=timezone.utc), "b")
    b = F(datetime(2024, 1, 3, tzinfo=timezone.utc), datetime(2024, 1, 1, tzinfo=timezone.utc), "a")
    ordered = sort_failures_for_replay([b, a])
    assert ordered[0] is a


def test_doctrine_modules_importable():
    from app.finance.doctrine.event_evolution import introspect_event_evolution_doctrine

    evo = introspect_event_evolution_doctrine()
    assert "registry_schema_versions" in evo
    assert "projection_compatibility_matrix" in evo
