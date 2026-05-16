"""Branch operational manifest (compiled branch operational truth)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.branch_operational_manifest import (
    REASON_MODULE_ENABLED_WORKSTATION_NOT_READY,
    REASON_MODULE_NOT_LICENSED,
    REASON_WORKSTATION_READY,
    compile_branch_operational_manifest,
)


class _FakeQuery:
    def __init__(self, branch, stores):
        self._branch = branch
        self._stores = stores

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._stores

    def first(self):
        return self._branch


class _FakeSession:
    def __init__(self, branch, stores):
        self._branch = branch
        self._stores = stores

    def query(self, model):
        return _FakeQuery(self._branch, self._stores)


def test_manifest_triage_active_when_clinic_enabled(monkeypatch):
    company_id = uuid4()
    branch_id = uuid4()
    branch = SimpleNamespace(id=branch_id, company_id=company_id, name="HQ")

    def fake_enabled(db, cid, mod):
        return mod == "clinic"

    monkeypatch.setattr(
        "app.services.branch_operational_manifest.is_module_enabled_compiled",
        fake_enabled,
    )

    db = _FakeSession(branch, [])
    out = compile_branch_operational_manifest(db, company_id=company_id, branch_id=branch_id)
    assert out["contract"] == "compiled_branch_operational_truth"
    assert "governance" in out and "inventory_linkage" in out

    triage = next(s for s in out["stations"] if s["code"] == "TRIAGE")
    assert triage["operational"]["status"] == "active"
    assert triage["operational"]["activation_reason"] == REASON_WORKSTATION_READY
    assert triage["operational"]["workstation"] is True
    assert triage["governance"]["module_enabled"] is True

    lab = next(s for s in out["stations"] if s["code"] == "LAB")
    assert lab["operational"]["status"] == "off"
    assert lab["operational"]["activation_reason"] == REASON_MODULE_NOT_LICENSED
    assert lab["operational"]["selectable_for_intake"] is False


def test_manifest_lab_routing_only_with_store_and_debug(monkeypatch):
    company_id = uuid4()
    branch_id = uuid4()
    branch = SimpleNamespace(id=branch_id, company_id=company_id, name="HQ")
    store = SimpleNamespace(id=uuid4(), code="LAB", is_active=True, name="Lab store")

    def fake_enabled(db, cid, mod):
        return mod in ("clinic", "lab")

    monkeypatch.setattr(
        "app.services.branch_operational_manifest.is_module_enabled_compiled",
        fake_enabled,
    )

    db = _FakeSession(branch, [store])
    out = compile_branch_operational_manifest(
        db, company_id=company_id, branch_id=branch_id, include_debug=True
    )
    lab = next(s for s in out["stations"] if s["code"] == "LAB")
    assert lab["operational"]["status"] == "routing_only"
    assert lab["operational"]["activation_reason"] == REASON_MODULE_ENABLED_WORKSTATION_NOT_READY
    assert lab["inventory"]["stock"] is True
    assert lab["inventory"]["department_store_id"] == str(store.id)
    assert lab["derivation"]["rules_applied"]
    assert out["debug"]["compiler"] == "branch_operational_manifest"
