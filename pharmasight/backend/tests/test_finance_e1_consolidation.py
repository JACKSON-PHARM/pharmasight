"""
E1 consolidation gates: finance endpoints must not call reports.view directly.
Legacy access flows only through resolves_finance_permission / deny_unless_finance_permission.
"""
from pathlib import Path

# Modules refactored in E1 + consolidation (finance-sensitive read paths)
_E1_FINANCE_API_FILES = (
    "app/api/cashbook.py",
    "app/api/reports.py",
    "app/api/insurance_management.py",
    "app/api/customer_management.py",
    "app/api/expenses.py",
    "app/api/sales.py",
    "app/api/items.py",
    "app/api/supplier_management.py",
)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_finance_api_files_do_not_check_reports_view_directly():
    """Direct reports.view checks bypass finance namespace governance."""
    offenders = []
    for rel in _E1_FINANCE_API_FILES:
        path = _BACKEND_ROOT / rel
        text = path.read_text(encoding="utf-8")
        if '"reports.view"' in text or "'reports.view'" in text:
            offenders.append(rel)
    assert not offenders, f"Remove direct reports.view checks; use deny_unless_finance_permission: {offenders}"


def test_finance_governance_access_module_exists():
    path = _BACKEND_ROOT / "app/finance/governance/access.py"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "require_finance_branch" in text
    assert "resolve_finance_access_context" in (
        _BACKEND_ROOT / "app/finance/governance/context.py"
    ).read_text(encoding="utf-8")
