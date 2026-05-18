"""
Unit tests for finance governance permission registry and legacy shim (E1).
"""
from app.finance.governance.permissions import (
    FINANCE_PERMISSION_NAMES,
    LEGACY_FINANCE_PERMISSION_ALIASES,
)


def test_finance_permission_registry_includes_core_namespaces():
    assert "finance.cashbook.view_branch" in FINANCE_PERMISSION_NAMES
    assert "wholesale.ar.view" in FINANCE_PERMISSION_NAMES
    assert "hospital.insurance.view" in FINANCE_PERMISSION_NAMES
    assert "retail.till.operate" in FINANCE_PERMISSION_NAMES


def test_gl_permissions_reserved_without_legacy_aliases():
    assert "finance.gl.view" in FINANCE_PERMISSION_NAMES
    assert LEGACY_FINANCE_PERMISSION_ALIASES.get("finance.gl.view") is None
    assert LEGACY_FINANCE_PERMISSION_ALIASES.get("finance.gl.post") is None


def test_reports_view_maps_to_operational_and_cashbook_branch():
    assert "reports.view" in LEGACY_FINANCE_PERMISSION_ALIASES["finance.reports.operational"]
    assert "reports.view" in LEGACY_FINANCE_PERMISSION_ALIASES["finance.cashbook.view_branch"]


def test_cashbook_reconcile_requires_settings_edit_legacy_not_reports_view():
    aliases = LEGACY_FINANCE_PERMISSION_ALIASES["finance.cashbook.reconcile_branch"]
    assert "settings.edit" in aliases
    assert "reports.view" not in aliases


def test_wholesale_ar_view_legacy_paths():
    aliases = LEGACY_FINANCE_PERMISSION_ALIASES["wholesale.ar.view"]
    assert "customers.view" in aliases
    assert "reports.view" in aliases
