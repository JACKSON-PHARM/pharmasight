"""
Heuristic API route audit for PharmaSight.

Purpose:
- Enumerate FastAPI routes from selected API modules.
- For each route, detect (via text heuristics):
  - permission checks (e.g. _user_has_permission / require_* deps)
  - company scoping signals (e.g. get_current_user / require_document_belongs_to_user_company)
  - tenant/module/plan gating (e.g. get_tenant_plan_context / tenant_modules)

This is not a formal static analyzer. It is meant to quickly surface risky endpoints
for manual review before implementing the entitlements/module system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


# Match FastAPI decorators even when formatting spans multiple lines.
# Captures:
# - HTTP method (group 1)
# - route path (group 2), expected to start with '/'
RE_DECORATOR = re.compile(
    r"@router\.(get|post|put|delete|patch|options)\(\s*['\"](/[^'\"]*)['\"]",
    flags=re.DOTALL,
)


@dataclass
class RouteRow:
    module: str
    method: str
    route: str
    permissions: str
    company_scoping: str
    tenant_plan: str
    file: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _find_route_blocks(text: str) -> List[tuple[str, str, int, int]]:
    """
    Find each route decorator and return tuples:
      (method, route_path, block_start_index, block_end_index_exclusive)

    Blocks are defined as:
      from this decorator match start up to (but not including) the next decorator match start.
    """
    matches = list(RE_DECORATOR.finditer(text))
    blocks: List[tuple[str, str, int, int]] = []
    for i, m in enumerate(matches):
        method = m.group(1).upper()
        route_path = m.group(2)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((method, route_path, start, end))
    return blocks


def _scan_block(block_text: str) -> tuple[str, str, str]:
    """
    Return:
    - permissions: Yes/No (heuristic)
    - company_scoping: Explicit / Likely via auth/RLS claim / Missing/Unclear
    - tenant_plan: Yes if demo/plan/module gating markers found
    """
    has_permission_checks = any(
        marker in block_text
        for marker in (
            "_user_has_permission",
            "require_settings_edit",
            "require_reports_view_and_branch",
        )
    )

    uses_auth = any(
        marker in block_text for marker in ("get_current_user", "Depends(get_current_user")
    )

    # document-level company protection
    uses_doc_company = "require_document_belongs_to_user_company" in block_text

    # explicit company_id filtering signals
    explicit_company = bool(
        re.search(
            r"filter\([^\n]*company_id|where\([^\n]*company_id|Company\.id",
            block_text,
            flags=re.MULTILINE,
        )
    )

    if uses_doc_company or explicit_company:
        company_scoping = "Yes (explicit/company check)"
    elif uses_auth:
        company_scoping = "Likely via auth/RLS claim (no explicit filter detected)"
    else:
        company_scoping = "Missing/Unclear company_id scoping"

    tenant_plan_markers = (
        "get_tenant_plan_context",
        "plan_ctx.get",
        "plan_type",
        "demo_expires_at",
        "demo",
        "TenantModule",
        "tenant_modules",
        "product_limit",
        "branch_limit",
        "user_limit",
    )
    tenant_plan = (
        "Yes (demo/plan context found)"
        if any(m in block_text for m in tenant_plan_markers)
        else "No"
    )

    permissions = (
        "Yes (permission checks found)"
        if has_permission_checks
        else ("No (auth only or none)" if uses_auth else "No")
    )
    return permissions, company_scoping, tenant_plan


def audit() -> None:
    base = Path("pharmasight/backend/app/api")

    modules = {
        "items.py": ("pharmacy-related", "/api/items"),
        "sales.py": ("billing-related", "/api/sales"),
        "purchases.py": ("billing-related", "/api/purchases"),
        "inventory.py": ("inventory-related", "/api/inventory"),
        "quotations.py": ("pharmacy-related", "/api/quotations"),
        "stock_take.py": ("inventory-related", "/api/stock-take"),
        "order_book.py": ("inventory-related", "/api/order-book"),
        "branch_inventory.py": ("inventory-related", "/api/branch-inventory"),
    }

    rows: List[RouteRow] = []

    for file_name, (module_name, prefix) in modules.items():
        path = base / file_name
        if not path.exists():
            continue

        text = _read(path)
        blocks = _find_route_blocks(text)
        for method, route_path, start, end in blocks:
            block_text = text[start:end]
            permissions, company_scoping, tenant_plan = _scan_block(block_text)

            rows.append(
                RouteRow(
                    module=module_name,
                    method=method,
                    route=prefix + route_path,
                    permissions=permissions,
                    company_scoping=company_scoping,
                    tenant_plan=tenant_plan,
                    file=file_name,
                )
            )

    rows.sort(key=lambda r: (r.module, r.route, r.method))

    def sh(s: str, n: int = 200) -> str:
        s = str(s)
        return s if len(s) <= n else s[: n - 1] + "..."

    # Markdown tables per requested grouping
    module_order = ["pharmacy-related", "inventory-related", "billing-related"]
    for mod in module_order:
        mod_rows = [r for r in rows if r.module == mod]
        if not mod_rows:
            continue

        print(f"# {mod}")
        print(
            "| Method | Route | Permissions checked? | Company scoping? | Tenant/plan/module check? |"
        )
        print("|---|---|---|---|---|")
        for r in mod_rows:
            print(
                f"| {r.method} | {sh(r.route, 200)} | {r.permissions} | {sh(r.company_scoping, 120)} | {r.tenant_plan} |"
            )
        print("")

    # Heuristic flags (for manual review)
    missing_perm = [r for r in rows if r.permissions.startswith("No")]
    state_changing = {"POST", "PUT", "PATCH", "DELETE"}
    missing_perm_state = [r for r in missing_perm if r.method in state_changing]
    missing_company = [r for r in rows if r.company_scoping.startswith("Missing/Unclear")]

    print("## Heuristic flags (for manual review)")
    print(
        f"- Routes missing explicit permission checks (and no permission markers found): {len(missing_perm)}"
    )
    print(
        f"- State-changing routes (POST/PUT/PATCH/DELETE) missing explicit permission checks: {len(missing_perm_state)}"
    )
    for r in missing_perm_state[:30]:
        print(f"- {r.method} {r.route} ({r.file})")

    print(f"\n- Routes missing/unclear company_id scoping signals: {len(missing_company)}")
    for r in missing_company[:30]:
        print(f"- {r.method} {r.route} ({r.file})")


if __name__ == "__main__":
    audit()

