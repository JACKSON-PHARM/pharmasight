"""
Stage 2A treasury movement reconciliation — drift classification unit tests.
"""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.finance.reconciliation.legitimacy import classify_missing_lineage
from app.finance.reconciliation.lineage_coverage import get_expectation_for_cashbook_source
from app.finance.reconciliation.treasury_movement import (
    classify_cashbook_lineage_pair,
    DRIFT_LABELS,
)


def _entry(**kwargs):
    defaults = dict(
        id=uuid4(),
        source_type="expense",
        source_id=uuid4(),
        type="outflow",
        amount=Decimal("100.00"),
        date=date(2025, 6, 1),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _event(**kwargs):
    defaults = dict(
        id=uuid4(),
        event_type="expense_recognized",
        economic_direction="outflow",
        amount=Decimal("100.00"),
        occurred_at=datetime(2025, 6, 1, 12, 0, 0),
        reversal_of_event_id=None,
        replay_source_failure_id=None,
        emission_channel="original",
    )
    defaults.update(kwargs)
    if isinstance(defaults.get("occurred_at"), date) and not isinstance(defaults["occurred_at"], datetime):
        defaults["occurred_at"] = datetime.combine(defaults["occurred_at"], datetime.min.time())
    return SimpleNamespace(**defaults)


def test_classify_matched():
    item = classify_cashbook_lineage_pair(
        _entry(),
        _event(),
        attribution={"record_exists": True, "operational_module": "Finance"},
        governance_start=date(2025, 1, 1),
        has_unresolved_failure=False,
        period_until=date(2026, 5, 18),
    )
    assert item.drift_type == "matched"


def test_classify_missing_event_emission():
    item = classify_cashbook_lineage_pair(
        _entry(),
        None,
        attribution={"record_exists": True},
        governance_start=date(2026, 5, 1),
        has_unresolved_failure=False,
        period_until=date(2026, 5, 18),
    )
    assert item.drift_type == "missing_event_emission"
    assert item.legitimacy["category"] in (
        "backfill_eligible",
        "active_operational_bypass",
        "historical_legacy_record",
    )


def test_classify_amount_mismatch():
    item = classify_cashbook_lineage_pair(
        _entry(amount=Decimal("50")),
        _event(amount=Decimal("100")),
        attribution={},
        governance_start=date(2025, 1, 1),
        has_unresolved_failure=False,
        period_until=date(2026, 5, 18),
    )
    assert item.drift_type == "amount_mismatch"


def test_classify_timing_drift():
    item = classify_cashbook_lineage_pair(
        _entry(date=date(2025, 6, 1)),
        _event(occurred_at=date(2025, 6, 5)),
        attribution={},
        governance_start=date(2025, 1, 1),
        has_unresolved_failure=False,
        period_until=date(2026, 5, 18),
    )
    assert item.drift_type == "timing_drift"


def test_classify_settlement_timing_for_cash_received():
    item = classify_cashbook_lineage_pair(
        _entry(source_type="customer_payment", type="inflow", date=date(2025, 6, 1)),
        _event(event_type="cash_received", economic_direction="inflow", occurred_at=date(2025, 6, 3)),
        attribution={},
        governance_start=date(2025, 1, 1),
        has_unresolved_failure=False,
        period_until=date(2026, 5, 18),
    )
    assert item.drift_type == "settlement_timing_variance"


def test_historical_legacy_when_pre_governance():
    exp = get_expectation_for_cashbook_source("expense")
    v = classify_missing_lineage(
        expectation=exp,
        cashbook_date=date(2025, 1, 15),
        cashbook_created_at=None,
        governance_start=date(2026, 5, 10),
        has_unresolved_failure=False,
        operational_record_exists=True,
        operational_date=date(2025, 1, 15),
        period_until=date(2026, 5, 18),
    )
    assert v.category == "historical_legacy_record"
    assert v.severity == "info"


def test_drift_labels_human_readable():
    assert DRIFT_LABELS["missing_event_emission"] == "Missing lineage event"
