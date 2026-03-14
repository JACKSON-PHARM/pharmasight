"""
Unit tests for PLATFORM_ADMIN impersonation.

- Only PLATFORM_ADMIN can call impersonation endpoints (401 without admin token).
- Impersonation token has short expiry and impersonation claim.
- Log helper is exercised (optional integration test with DB).
"""
import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import pytest
from datetime import datetime, timezone

from app.utils.auth_internal import (
    create_impersonation_access_token,
    decode_internal_token,
    CLAIM_IMPERSONATION,
    CLAIM_EXP,
    IMPERSONATION_TOKEN_EXPIRE_MINUTES,
)


# --- Token creation and expiry ---


def test_impersonation_token_has_impersonation_claim():
    """Token returned by create_impersonation_access_token must contain impersonation=true."""
    token = create_impersonation_access_token(
        user_id="11111111-1111-1111-1111-111111111111",
        email="user@company.com",
        tenant_subdomain=None,
        company_id="22222222-2222-2222-2222-222222222222",
        impersonated_by="admin_session_xyz",
    )
    payload = decode_internal_token(token)
    assert payload is not None
    assert payload.get(CLAIM_IMPERSONATION) is True
    assert payload.get("sub") == "11111111-1111-1111-1111-111111111111"
    assert payload.get("company_id") == "22222222-2222-2222-2222-222222222222"
    assert payload.get("impersonated_by") == "admin_session_xyz"


def test_impersonation_token_expires_short():
    """Impersonation token must expire in 15 minutes (or configured short window)."""
    token = create_impersonation_access_token(
        user_id="11111111-1111-1111-1111-111111111111",
        email="u@c.com",
        tenant_subdomain=None,
        company_id="22222222-2222-2222-2222-222222222222",
        impersonated_by="admin",
    )
    payload = decode_internal_token(token)
    assert payload is not None
    exp = payload.get(CLAIM_EXP)
    assert exp is not None
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    delta_minutes = (exp_dt - now).total_seconds() / 60
    assert 14 <= delta_minutes <= 16  # ~15 min


def test_impersonation_token_custom_expiry():
    """Custom expires_minutes is respected."""
    token = create_impersonation_access_token(
        user_id="11111111-1111-1111-1111-111111111111",
        email="u@c.com",
        tenant_subdomain=None,
        company_id="22222222-2222-2222-2222-222222222222",
        impersonated_by="admin",
        expires_minutes=5,
    )
    payload = decode_internal_token(token)
    assert payload is not None
    exp = payload.get(CLAIM_EXP)
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    delta_minutes = (exp_dt - now).total_seconds() / 60
    assert 4 <= delta_minutes <= 6


# --- API: only PLATFORM_ADMIN can impersonate ---


def test_impersonate_company_without_admin_token_returns_401():
    """POST /api/admin/impersonate/{company_id} without admin token must return 401."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # No Authorization header -> get_current_admin raises 401
    response = client.post(
        "/api/admin/impersonate/11111111-1111-1111-1111-111111111111",
        json={},
    )
    assert response.status_code == 401


def test_impersonate_user_without_admin_token_returns_401():
    """POST /api/admin/impersonate-user/{user_id} without admin token must return 401."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/admin/impersonate-user/11111111-1111-1111-1111-111111111111",
        json={},
    )
    assert response.status_code == 401


def test_impersonate_company_with_invalid_admin_token_returns_401():
    """POST /api/admin/impersonate/{company_id} with invalid Bearer token returns 401."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/admin/impersonate/11111111-1111-1111-1111-111111111111",
        headers={"Authorization": "Bearer invalid-token"},
        json={},
    )
    assert response.status_code == 401
