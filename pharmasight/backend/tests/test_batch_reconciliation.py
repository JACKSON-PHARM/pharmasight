"""Unit tests for batch-pool reconciliation against item-level stock."""
from datetime import date

from app.services.inventory_service import InventoryService


def test_reconcile_batch_pools_no_trim_when_totals_match():
    pools = [
        {"batch_number": "A", "expiry_date": date(2026, 6, 30), "quantity": 1.0},
    ]
    out = InventoryService.reconcile_batch_pools(pools, current_stock=1.0)
    assert len(out) == 1
    assert out[0]["quantity"] == 1.0


def test_reconcile_batch_pools_trims_earliest_expiry_first_for_fefo():
    """Phantom layers on sold-out early batches are removed; real stock batch remains."""
    pools = [
        {"batch_number": "OLD", "expiry_date": date(2026, 6, 30), "quantity": 1.0, "value": 100.0},
        {"batch_number": "MID", "expiry_date": date(2026, 8, 31), "quantity": 1.0, "value": 110.0},
        {"batch_number": "NEW", "expiry_date": date(2027, 10, 31), "quantity": 1.0, "value": 120.0},
    ]
    out = InventoryService.reconcile_batch_pools(
        pools, current_stock=1.0, trim_from="earliest_expiry"
    )
    assert len(out) == 1
    assert out[0]["batch_number"] == "NEW"
    assert out[0]["quantity"] == 1.0


def test_reconcile_batch_pools_trims_latest_expiry_first_for_expiry_report():
    pools = [
        {"batch_number": "OLD", "expiry_date": date(2026, 6, 30), "quantity": 1.0},
        {"batch_number": "MID", "expiry_date": date(2026, 8, 31), "quantity": 1.0},
        {"batch_number": "NEW", "expiry_date": date(2027, 10, 31), "quantity": 1.0},
    ]
    out = InventoryService.reconcile_batch_pools(
        pools, current_stock=1.0, trim_from="latest_expiry"
    )
    assert len(out) == 1
    assert out[0]["batch_number"] == "OLD"


def test_reconcile_then_expiry_window_excludes_far_batch():
    """After reconciliation, only batches inside the expiring window are listed."""
    from datetime import timedelta

    today = date.today()
    far_expiry = today + timedelta(days=400)
    near_expiry = today + timedelta(days=90)
    pools = InventoryService.reconcile_batch_pools(
        [
            {"batch_number": "PHANTOM", "expiry_date": near_expiry, "quantity": 1.0},
            {"batch_number": "REAL", "expiry_date": far_expiry, "quantity": 1.0},
        ],
        current_stock=1.0,
    )
    cutoff = today + timedelta(days=180)
    in_window = [
        p
        for p in pools
        if p["expiry_date"] and today <= p["expiry_date"] <= cutoff
    ]
    assert len(pools) == 1
    assert pools[0]["batch_number"] == "REAL"
    assert in_window == []


def test_reconcile_batch_pools_keeps_multiple_when_stock_allows():
    pools = [
        {"batch_number": "A", "expiry_date": date(2026, 6, 30), "quantity": 1.0},
        {"batch_number": "B", "expiry_date": date(2027, 10, 31), "quantity": 1.0},
    ]
    out = InventoryService.reconcile_batch_pools(pools, current_stock=2.0)
    assert len(out) == 2
    assert sum(p["quantity"] for p in out) == 2.0
