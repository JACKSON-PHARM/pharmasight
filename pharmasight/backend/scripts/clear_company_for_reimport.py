"""
Clear company-specific data so you can run an Excel import afresh.

Uses app.services.clear_for_reimport_service.run_clear() for the actual delete.
Use the API when possible: POST /api/excel/clear-for-reimport (body: {"company_id": "uuid"}).
The API only allows clear when there are no live transactions.

Usage (from repo root or from backend/):
  python -m pharmasight.backend.scripts.clear_company_for_reimport <company_id>
  python -m pharmasight.backend.scripts.clear_company_for_reimport <company_id> --yes

Or from backend/:
  python scripts/clear_company_for_reimport.py <company_id> [--yes]

Requires: DATABASE_URL or Supabase env vars set (tenant DB).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

# Add backend to path when run as script
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import settings
from app.services.clear_for_reimport_service import run_clear


def _valid_uuid(s: str) -> UUID:
    try:
        return UUID(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid UUID: {s}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clear company data for a fresh Excel re-import (items, inventory, purchases, sales, etc.).",
        epilog="Example: python scripts/clear_company_for_reimport.py 9c71915e-3e59-45d5-9719-56d2322ff673 --yes",
    )
    parser.add_argument(
        "company_id",
        type=_valid_uuid,
        nargs="?",
        default=None,
        help="Company UUID to clear (e.g. 9c71915e-3e59-45d5-9719-56d2322ff673)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show row counts that would be deleted; do not delete",
    )
    args = parser.parse_args()

    if args.company_id is None:
        parser.print_help()
        print("\nYou must provide company_id. Get it from the app (e.g. API response when logged in) or from DB: SELECT id, name FROM companies;")
        return 1

    if not settings.database_connection_string:
        print("ERROR: DATABASE_URL (or Supabase DB env vars) not set. Cannot connect to tenant DB.")
        return 1

    company_id = args.company_id
    if args.dry_run:
        print(f"Dry-run: would delete company data for company_id={company_id}")
        _ok, msgs = run_clear(company_id, dry_run=True)
        for m in msgs:
            print(f"  {m}")
        return 0

    if not args.yes:
        print(f"This will PERMANENTLY delete all items, inventory, purchases, sales, and related data for company {company_id}.")
        print("Companies, branches, and users will NOT be deleted.")
        try:
            confirm = input("Type 'yes' to continue: ").strip().lower()
        except EOFError:
            confirm = ""
        if confirm != "yes":
            print("Aborted.")
            return 0

    print(f"Clearing company data for {company_id}...")
    ok, messages = run_clear(company_id)
    for m in messages:
        print(f"  {m}")
    if ok:
        print("Done. You can now run an Excel import afresh.")
    else:
        print("Clear failed; check errors above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
