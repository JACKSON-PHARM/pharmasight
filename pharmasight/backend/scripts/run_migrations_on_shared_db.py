"""
Run app migrations on the shared DB (DATABASE_URL).

Use this when the master DB is also the default tenant DB (Option A): the same
Supabase project holds tenant-management tables AND must hold app tables
(companies, users, branches, items, etc.). This script applies
pharmasight/database/migrations/*.sql to the database pointed to by DATABASE_URL.

Usage (from pharmasight/ or pharmasight/backend/ with .env loaded):
  python -m pharmasight.backend.scripts.run_migrations_on_shared_db
  python scripts/run_migrations_on_shared_db.py

Requires: DATABASE_URL or SUPABASE_* env vars set (e.g. from pharmasight/.env).
"""
from __future__ import annotations

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import settings
from app.services.migration_service import run_migrations_for_url


def main() -> int:
    url = settings.database_connection_string
    if not url:
        print("ERROR: DATABASE_URL (or SUPABASE_* vars) not set. Set them in pharmasight/.env")
        return 1
    # Mask password in log
    safe = url.split("@")[-1] if "@" in url else url[:50]
    print(f"Running app migrations on DB: ...@{safe}")
    try:
        applied = run_migrations_for_url(url)
        if applied:
            print(f"Applied {len(applied)} migration(s):", ", ".join(applied))
        else:
            print("No new migrations; schema already up to date.")
        return 0
    except Exception as e:
        print("ERROR:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
