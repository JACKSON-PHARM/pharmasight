#!/usr/bin/env python3
"""
CI guard: Option B — no tenant-based entitlement drift; tenant model imports only in approved modules.

Exit 1 if forbidden patterns or disallowed imports are found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"

# Files that may import the Tenant ORM (infra / routing / migration / admin / storage resolution).
TENANT_IMPORT_ALLOW = frozenset(
    {
        APP / "models" / "tenant.py",
        APP / "dependencies.py",
        APP / "services" / "migration_service.py",
        APP / "services" / "onboarding_service.py",
        APP / "services" / "demo_signup_service.py",
        APP / "services" / "tenant_provisioning.py",
        APP / "api" / "tenants.py",
        APP / "api" / "onboarding.py",
        APP / "api" / "auth.py",
        APP / "services" / "admin_auth_service.py",
        APP / "api" / "purchases.py",
    }
)

IMPORT_LINE = re.compile(r"^\s*from\s+app\.models\.tenant\s+import\s+", re.MULTILINE)


def _norm(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p


def check_forbidden_patterns() -> list[str]:
    errors: list[str] = []
    roots = [APP / "api", APP / "services"]
    patterns = [
        (re.compile(r"Tenant\.status"), "Tenant.status"),
        (re.compile(r"Tenant\.plan_type"), "Tenant.plan_type"),
        (re.compile(r"Tenant\.trial"), "Tenant.trial"),
        (re.compile(r"TenantSubscription"), "TenantSubscription"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for rx, label in patterns:
                if rx.search(text):
                    errors.append(f"{label} referenced in {path.relative_to(BACKEND)}")
    return errors


def check_tenant_import_drift() -> list[str]:
    errors: list[str] = []
    for path in APP.rglob("*.py"):
        p = _norm(path)
        if p in TENANT_IMPORT_ALLOW:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if IMPORT_LINE.search(text):
            errors.append(f"Disallowed 'from app.models.tenant import' in {path.relative_to(BACKEND)}")
    return errors


def main() -> int:
    errs = check_forbidden_patterns() + check_tenant_import_drift()
    if errs:
        print("Option B guard failures:\n", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("Option B guards: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
