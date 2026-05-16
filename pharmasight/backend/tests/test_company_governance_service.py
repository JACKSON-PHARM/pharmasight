"""Company governance compiler — commercial access, legacy grandfather, presets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.company_governance_service import (
    derive_commercial_access,
    is_legacy_governance_company,
    map_commercial_access_to_company_access,
    normalize_operating_model,
    subscription_access_for_company,
)


def _company(**kwargs):
    defaults = dict(
        is_active=True,
        subscription_status=None,
        trial_expires_at=None,
        organization_operating_model=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_legacy_grandfather_detection():
    c = _company()
    assert is_legacy_governance_company(c) is True
    c2 = _company(organization_operating_model="PHARMACY_RETAIL")
    assert is_legacy_governance_company(c2) is False
    c3 = _company(subscription_status="active")
    assert is_legacy_governance_company(c3) is False


def test_derive_commercial_access_legacy_active():
    assert derive_commercial_access(_company()) == "legacy_active"


def test_derive_commercial_access_onboarding_pending():
    c = _company(organization_operating_model="PHARMACY_RETAIL")
    assert derive_commercial_access(c) == "onboarding_pending"


def test_derive_commercial_access_active_and_trial():
    assert derive_commercial_access(_company(subscription_status="active")) == "active"
    end = datetime.now(timezone.utc) + timedelta(days=5)
    assert derive_commercial_access(_company(subscription_status="trialing", trial_expires_at=end)) == "trial"


def test_map_legacy_active_to_runtime_active():
    assert map_commercial_access_to_company_access("legacy_active") == "active"


def test_active_status_ignores_past_trial_end():
    end = datetime.now(timezone.utc) - timedelta(days=20)
    c = _company(subscription_status="active", trial_expires_at=end)
    assert derive_commercial_access(c) == "active"
    assert subscription_access_for_company(c) == "full"


def test_trialing_past_end_is_expired():
    end = datetime.now(timezone.utc) - timedelta(days=1)
    c = _company(subscription_status="trialing", trial_expires_at=end)
    assert derive_commercial_access(c) == "expired"
    assert subscription_access_for_company(c) == "trial_expired"


def test_demo_past_end_is_expired():
    end = datetime.now(timezone.utc) - timedelta(days=1)
    c = _company(subscription_status="demo", trial_expires_at=end)
    assert derive_commercial_access(c) == "expired"


def test_normalize_operating_model():
    assert normalize_operating_model("pharmacy_retail") == "PHARMACY_RETAIL"
    with pytest.raises(ValueError):
        normalize_operating_model("INVALID")

