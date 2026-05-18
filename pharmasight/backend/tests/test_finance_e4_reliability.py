"""
E4 financial event reliability tests.
"""
from pathlib import Path

from app.finance.events.lifecycle import ALL_EMISSION_CHANNELS, ALL_OPERATIONAL_STATUSES
from app.finance.events.policies import POLICY_PACKS, resolve_policy_pack
from app.finance.events.registry import FINANCIAL_EVENT_REGISTRY


def test_policy_packs_defined():
    assert "RETAIL_SIMPLE" in POLICY_PACKS
    assert "WHOLESALE_AR" in POLICY_PACKS
    assert "HOSPITAL_INSURANCE" in POLICY_PACKS


def test_retail_policy_skips_receivable_accrued():
    pack = resolve_policy_pack(sales_type="RETAIL")
    assert "receivable_accrued" not in pack.enabled_event_types


def test_wholesale_policy_enables_settlement():
    pack = resolve_policy_pack(sales_type="WHOLESALE")
    assert pack.settlement_linking_enabled
    assert "receivable_accrued" in pack.enabled_event_types


def test_economic_direction_neutral_not_accounting():
    forbidden = ("debit", "credit", "dr_", "cr_", "account_id", "journal")
    for spec in FINANCIAL_EVENT_REGISTRY.values():
        d = spec.economic_direction.lower()
        assert d in ("inflow", "outflow", "accrual", "reduction", "adjustment")
        for bad in forbidden:
            assert bad not in d


def test_operational_lifecycle_constants():
    assert "emitted" in ALL_OPERATIONAL_STATUSES
    assert "replayed" in ALL_OPERATIONAL_STATUSES
    assert "replay" in ALL_EMISSION_CHANNELS


def test_no_direct_financial_event_inserts_in_hooks():
    hooks = (Path(__file__).resolve().parent.parent / "app/finance/events/hooks.py").read_text(encoding="utf-8")
    assert "FinancialEvent(" not in hooks
    assert "caused_by_event_id =" not in hooks or "resolve_primary_caused_by_event_id" in hooks


def test_replay_module_exists():
    assert (Path(__file__).resolve().parent.parent / "app/finance/events/replay.py").is_file()


def test_integrity_module_exists():
    assert (Path(__file__).resolve().parent.parent / "app/finance/events/integrity.py").is_file()
