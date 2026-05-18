"""
E2.5 architectural governance invariants.
"""
from pathlib import Path

import pytest

from app.finance.governance.classification import AUDIT, EXECUTIVE, classification_allows
from app.finance.governance.registry import FINANCE_GOVERNANCE_REGISTRY, introspect_registry
from app.finance.governance.telemetry import ALL_TELEMETRY_EVENTS
from app.finance.governance.permissions import LEGACY_FINANCE_PERMISSION_ALIASES

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_GOVERNANCE_DIR = _BACKEND_ROOT / "app/finance/governance"

_FINANCE_API_FILES = (
    "app/api/cashbook.py",
    "app/api/reports.py",
    "app/api/insurance_management.py",
    "app/api/customer_management.py",
    "app/api/expenses.py",
    "app/api/sales.py",
    "app/api/items.py",
    "app/api/supplier_management.py",
)

_BANNED_API_PATTERNS = (
    '"reports.view"',
    "'reports.view'",
    "assert_finance_branch_access(",
    "resolves_finance_permission(",
    "deny_unless_finance_permission(db, user.id,",
)


def test_governance_modules_present():
    for name in (
        "telemetry.py",
        "registry.py",
        "enforcement.py",
        "query_scope.py",
        "decorators.py",
        "request_context.py",
    ):
        assert (_GOVERNANCE_DIR / name).is_file()


def test_telemetry_event_catalog_complete():
    expected = {
        "finance_access_denied",
        "finance_scope_denied",
        "finance_classification_denied",
        "finance_permission_granted",
        "finance_audit_scope_used",
        "finance_executive_scope_used",
        "finance_company_scope_used",
        "deprecated_permission_fallback_used",
    }
    assert expected == set(ALL_TELEMETRY_EVENTS)


def test_registry_covers_all_finance_api_registry_ids():
    """Every registry_id referenced in finance API modules must exist in the registry."""
    import re

    referenced = set()
    for rel in _FINANCE_API_FILES:
        text = (_BACKEND_ROOT / rel).read_text(encoding="utf-8")
        referenced.update(re.findall(r'registry_id="([a-z0-9_.]+)"', text))
    missing = referenced - set(FINANCE_GOVERNANCE_REGISTRY.keys())
    assert not missing, f"Registry missing entries: {missing}"


def test_registry_entries_have_legacy_flag_aligned():
    for spec in FINANCE_GOVERNANCE_REGISTRY.values():
        expected = spec.permission in LEGACY_FINANCE_PERMISSION_ALIASES
        assert spec.legacy_fallback == expected, spec.registry_id


def test_finance_api_files_avoid_governance_drift():
    offenders = []
    for rel in _FINANCE_API_FILES:
        text = (_BACKEND_ROOT / rel).read_text(encoding="utf-8")
        for pattern in _BANNED_API_PATTERNS:
            if pattern in text:
                offenders.append(f"{rel}: {pattern}")
    assert not offenders, offenders


def test_finance_api_use_unified_context_enforcement():
    offenders = []
    for rel in _FINANCE_API_FILES:
        text = (_BACKEND_ROOT / rel).read_text(encoding="utf-8")
        uses_unified = any(
            token in text
            for token in (
                "resolve_finance_access_context",
                "guard_finance_report_access",
                "guard_finance_branch_query_param",
                "require_finance_branch",
                "deny_unless_finance_permission",
            )
        )
        if not uses_unified:
            offenders.append(rel)
    assert not offenders, offenders


def test_enforcement_is_single_assertion_entry():
    enforcement = (_GOVERNANCE_DIR / "enforcement.py").read_text(encoding="utf-8")
    assert "def assert_finance_access(" in enforcement
    context = (_GOVERNANCE_DIR / "context.py").read_text(encoding="utf-8")
    enforcement_file = (_GOVERNANCE_DIR / "enforcement.py").read_text(encoding="utf-8")
    assert "assert_finance_access" in enforcement_file
    assert "def assert_access(" in context


def test_telemetry_emit_never_raises():
    from unittest.mock import patch
    from uuid import uuid4

    from app.finance.governance.telemetry import emit_finance_governance_event, FINANCE_PERMISSION_GRANTED

    with patch("app.finance.governance.telemetry.logger") as mock_logger:
        mock_logger.info.side_effect = RuntimeError("sink down")
        emit_finance_governance_event(
            FINANCE_PERMISSION_GRANTED,
            user_id=uuid4(),
            company_id=uuid4(),
        )


def test_classification_audit_not_linear_superset_of_executive():
    assert not classification_allows(EXECUTIVE, AUDIT)
    assert classification_allows(AUDIT, EXECUTIVE)


def test_introspect_registry_serializable():
    rows = introspect_registry()
    assert len(rows) == len(FINANCE_GOVERNANCE_REGISTRY)
    assert all("registry_id" in r for r in rows)
