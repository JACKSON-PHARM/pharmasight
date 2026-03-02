"""
Unit tests for StockValidationService.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure backend app is on path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import pytest

from app.services.stock_validation_service import (
    validate_stock_entry,
    validate_stock_entry_with_config,
    StockValidationResult,
    StockValidationError,
    StockValidationConfig,
    STOCK_VALIDATION_MODE_OFF,
    STOCK_VALIDATION_MODE_WARN,
    STOCK_VALIDATION_MODE_STRICT,
)


# --- track_expiry=False (always valid) ---


def test_track_expiry_false_always_valid():
    """When track_expiry=False, always returns valid regardless of batch/expiry."""
    ref = date(2025, 3, 1)
    r = validate_stock_entry(
        batch_number=None,
        expiry_date=None,
        track_expiry=False,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r.valid is True
    assert r.expired is False
    assert r.short_expiry is False
    assert r.days_remaining is None

    r2 = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=ref - timedelta(days=30),  # expired
        track_expiry=False,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r2.valid is True


# --- Expired product (hard reject) ---


def test_expired_product_raises():
    """Expired product must raise StockValidationError."""
    ref = date(2025, 3, 1)
    with pytest.raises(StockValidationError) as exc_info:
        validate_stock_entry(
            batch_number="BATCH-001",
            expiry_date=ref - timedelta(days=1),
            track_expiry=True,
            min_expiry_days=90,
            override=False,
            reference_date=ref,
        )
    assert exc_info.value.result is not None
    assert exc_info.value.result.expired is True
    assert exc_info.value.result.valid is False


def test_expired_product_exact_today():
    """Expiry date = today does NOT raise (not expired) but is short_expiry.
    Without override, returns invalid. With override, returns valid."""
    ref = date(2025, 3, 1)
    # Spec: "expiry_date < today" → raise. So expiry=today does NOT raise.
    r = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=ref,
        track_expiry=True,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r.expired is False  # Does not raise
    assert r.short_expiry is True  # 0 days <= 90
    assert r.valid is False  # Short expiry without override

    # With override, valid
    r2 = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=ref,
        track_expiry=True,
        min_expiry_days=90,
        override=True,
        reference_date=ref,
    )
    assert r2.valid is True
    assert r2.days_remaining == 0


# --- Short expiry ---


def test_short_expiry_no_override_invalid():
    """Short expiry without override returns invalid (does NOT raise)."""
    ref = date(2025, 3, 1)
    expiry = ref + timedelta(days=30)  # 30 days, threshold 90
    r = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=expiry,
        track_expiry=True,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r.valid is False
    assert r.short_expiry is True
    assert r.days_remaining == 30


def test_short_expiry_with_override_valid():
    """Short expiry with override returns valid."""
    ref = date(2025, 3, 1)
    expiry = ref + timedelta(days=30)
    r = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=expiry,
        track_expiry=True,
        min_expiry_days=90,
        override=True,
        reference_date=ref,
    )
    assert r.valid is True
    assert r.short_expiry is True
    assert r.days_remaining == 30


# --- Exact threshold ---


def test_exact_threshold_short_expiry():
    """Expiry exactly at threshold (today + min_expiry_days) is short_expiry, invalid without override."""
    ref = date(2025, 3, 1)
    expiry = ref + timedelta(days=90)  # exactly 90 days
    r = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=expiry,
        track_expiry=True,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    # expiry <= today+90, so short_expiry. Without override → invalid
    assert r.valid is False
    assert r.short_expiry is True


def test_just_over_threshold_valid():
    """Expiry one day past threshold is valid without override."""
    ref = date(2025, 3, 1)
    expiry = ref + timedelta(days=91)  # 91 days
    r = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=expiry,
        track_expiry=True,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r.valid is True
    assert r.short_expiry is False
    assert r.days_remaining == 91


# --- Required batch/expiry when track_expiry=True ---


def test_missing_batch_number_invalid():
    """When track_expiry=True, missing batch_number returns invalid."""
    ref = date(2025, 3, 1)
    r = validate_stock_entry(
        batch_number=None,
        expiry_date=ref + timedelta(days=100),
        track_expiry=True,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r.valid is False
    assert "Batch number" in (r.message or "")


def test_empty_batch_number_invalid():
    """Empty/whitespace batch_number returns invalid."""
    ref = date(2025, 3, 1)
    r = validate_stock_entry(
        batch_number="   ",
        expiry_date=ref + timedelta(days=100),
        track_expiry=True,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r.valid is False


def test_missing_expiry_date_invalid():
    """When track_expiry=True, missing expiry_date returns invalid."""
    ref = date(2025, 3, 1)
    r = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=None,
        track_expiry=True,
        min_expiry_days=90,
        override=False,
        reference_date=ref,
    )
    assert r.valid is False
    assert "Expiry date" in (r.message or "")


# --- Override case (short expiry) ---


def test_override_case():
    """Override allows short-expiry to pass."""
    ref = date(2025, 3, 1)
    expiry = ref + timedelta(days=1)  # 1 day left
    r = validate_stock_entry(
        batch_number="BATCH-001",
        expiry_date=expiry,
        track_expiry=True,
        min_expiry_days=90,
        override=True,
        reference_date=ref,
    )
    assert r.valid is True
    assert r.short_expiry is True
    assert r.days_remaining == 1


# --- Config layer: OFF / WARN / STRICT ---


def test_config_off_allows_short_expiry():
    """Mode OFF: short_expiry is allowed (override forced True internally)."""
    config = StockValidationConfig(mode=STOCK_VALIDATION_MODE_OFF, min_expiry_days=90)
    ref = date(2025, 3, 1)
    r = validate_stock_entry_with_config(
        config,
        batch_number="BATCH-001",
        expiry_date=ref + timedelta(days=30),
        track_expiry=True,
        override=False,
        reference_date=ref,
    )
    assert r.valid is True


def test_config_warn_allows_short_expiry():
    """Mode WARN: short_expiry allowed (override forced True), result.short_expiry set."""
    config = StockValidationConfig(mode=STOCK_VALIDATION_MODE_WARN, min_expiry_days=90)
    ref = date(2025, 3, 1)
    r = validate_stock_entry_with_config(
        config,
        batch_number="BATCH-001",
        expiry_date=ref + timedelta(days=30),
        track_expiry=True,
        override=False,
        reference_date=ref,
    )
    assert r.valid is True
    assert r.short_expiry is True


def test_config_warn_rejects_expired():
    """Mode WARN: expired still raises StockValidationError."""
    config = StockValidationConfig(mode=STOCK_VALIDATION_MODE_WARN, min_expiry_days=90)
    ref = date(2025, 3, 1)
    with pytest.raises(StockValidationError):
        validate_stock_entry_with_config(
            config,
            batch_number="BATCH-001",
            expiry_date=ref - timedelta(days=1),
            track_expiry=True,
            override=False,
            reference_date=ref,
        )


def test_config_strict_rejects_short_expiry_without_override():
    """Mode STRICT: short_expiry without override returns invalid."""
    config = StockValidationConfig(mode=STOCK_VALIDATION_MODE_STRICT, min_expiry_days=90)
    ref = date(2025, 3, 1)
    r = validate_stock_entry_with_config(
        config,
        batch_number="BATCH-001",
        expiry_date=ref + timedelta(days=30),
        track_expiry=True,
        override=False,
        reference_date=ref,
    )
    assert r.valid is False
    assert r.short_expiry is True


def test_config_strict_allows_short_expiry_with_override():
    """Mode STRICT: short_expiry with override returns valid."""
    config = StockValidationConfig(mode=STOCK_VALIDATION_MODE_STRICT, min_expiry_days=90)
    ref = date(2025, 3, 1)
    r = validate_stock_entry_with_config(
        config,
        batch_number="BATCH-001",
        expiry_date=ref + timedelta(days=30),
        track_expiry=True,
        override=True,
        reference_date=ref,
    )
    assert r.valid is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
