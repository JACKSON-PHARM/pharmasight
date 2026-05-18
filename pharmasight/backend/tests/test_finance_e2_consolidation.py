"""
E2 consolidation gates: finance APIs must use FinanceAccessContext pattern.
"""
from pathlib import Path

_E2_FINANCE_API_FILES = (
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


def test_finance_api_files_use_context_pattern():
    offenders = []
    for rel in _E2_FINANCE_API_FILES:
        text = (_BACKEND_ROOT / rel).read_text(encoding="utf-8")
        has_resolve = "resolve_finance_access_context" in text
        has_guard = (
            "guard_finance_report_access" in text
            or "guard_finance_branch_query_param" in text
            or "require_finance_branch" in text
        )
        has_deny = "deny_unless_finance_permission" in text
        if not (has_resolve or has_guard or has_deny):
            offenders.append(rel)
        if "assert_finance_branch_access" in text:
            offenders.append(f"{rel} (direct assert_finance_branch_access)")
        if 'deny_unless_finance_permission(db, user.id,' in text:
            offenders.append(f"{rel} (E1 deny signature)")
    assert not offenders, f"Migrate to E2 context: {offenders}"


def test_context_engine_modules_exist():
    for name in ("context.py", "classification.py", "scope.py", "report_context.py"):
        assert (_BACKEND_ROOT / "app/finance/governance" / name).is_file()
