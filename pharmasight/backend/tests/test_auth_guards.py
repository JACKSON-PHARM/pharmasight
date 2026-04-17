"""Tests for tenant↔company auth guards (Option B)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.utils.auth_guards import (
    assert_effective_company_matches_tenant,
    assert_jwt_company_claim_matches_tenant,
    assert_tenant_company_link,
)


def _tenant(company_id):
    return SimpleNamespace(id=uuid.uuid4(), company_id=company_id)


def test_tenant_must_have_company():
    with pytest.raises(RuntimeError, match="Missing tenant resolution"):
        assert_tenant_company_link(None)

    t = _tenant(None)
    with pytest.raises(RuntimeError, match="no company_id"):
        assert_tenant_company_link(t)


def test_auth_requires_company_link():
    t = _tenant(None)
    with pytest.raises(RuntimeError, match="no company_id"):
        assert_tenant_company_link(t)


def test_valid_tenant_company_link():
    cid = uuid.uuid4()
    t = _tenant(cid)
    assert_tenant_company_link(t)


def test_jwt_claim_mismatch_fails():
    cid = uuid.uuid4()
    t = _tenant(cid)
    with pytest.raises(RuntimeError, match="JWT company_id"):
        assert_jwt_company_claim_matches_tenant(t, str(uuid.uuid4()))


def test_effective_company_mismatch_fails():
    cid = uuid.uuid4()
    t = _tenant(cid)
    with pytest.raises(RuntimeError, match="tenant-company mismatch"):
        assert_effective_company_matches_tenant(t, uuid.uuid4())


def test_valid_effective_and_claim():
    cid = uuid.uuid4()
    t = _tenant(cid)
    assert_jwt_company_claim_matches_tenant(t, str(cid))
    assert_effective_company_matches_tenant(t, cid)
