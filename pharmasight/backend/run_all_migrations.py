"""
Run all pending database migrations (default DB + all tenant DBs).

Same logic as backend startup. Migrations are transmitted to:
  1) Master DB (default DATABASE_URL) – where the tenants table lives.
  2) Every tenant DB – each tenant row in master must have database_url set to that
     tenant's Supabase project (e.g. PHARMASIGHT MEDS LTD, pharmasightsolutions's Project).
     Only tenants with status 'trial' or 'active' are migrated.

Usage (from pharmasight/backend):
  python run_all_migrations.py
  python run_all_migrations.py --url "postgresql://..."   # run on one DB only

Requires: DATABASE_URL or Supabase env vars set; tenant DBs are read from the master DB.
"""
import argparse
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.services.migration_service import MigrationService, run_migrations_for_url


def main(url_only: str | None = None):
    print("Running pending migrations...")
    applied_default = []
    applied_tenants = {}

    if url_only:
        # Run only on the given URL (e.g. tenant Supabase DB)
        try:
            applied = run_migrations_for_url(url_only.strip())
            if applied:
                print(f"  Applied: {applied}")
            else:
                print("  Already up to date.")
        except Exception as e:
            print(f"  ERROR: {e}")
            raise
        return

    # 1) Default / master DB
    try:
        default_url = settings.database_connection_string
    except Exception:
        default_url = ""
    if default_url:
        try:
            applied_default = run_migrations_for_url(default_url)
            if applied_default:
                print(f"  Default DB: applied {applied_default}")
            else:
                print("  Default DB: already up to date")
        except Exception as e:
            print(f"  Default DB: ERROR - {e}")
            raise
    else:
        print("  Default DB: skipped (no DATABASE_URL / connection string)")

    # 2) All tenant DBs (each tenant = one Supabase project; list comes from master DB)
    svc = MigrationService()
    tenants_with_db = svc.get_all_tenants_with_db()
    tenants_to_migrate = [t for t in tenants_with_db if (t.status or "").lower() in ("trial", "active")]
    if tenants_to_migrate:
        print(f"  Tenant DBs to migrate: {len(tenants_to_migrate)}")
        for t in tenants_to_migrate:
            host = "(unknown)"
            if t.database_url:
                try:
                    from urllib.parse import urlparse
                    host = urlparse(t.database_url).hostname or "(no host)"
                except Exception:
                    pass
            print(f"    - {t.name!r} (id={t.id}) -> {host}")
    else:
        print("  No tenant DBs with database_url and status trial/active (check master tenants table).")

    out = svc.run_migrations_all_tenant_dbs()
    if out["applied"]:
        for tid, versions in out["applied"].items():
            print(f"  Tenant {tid}: applied {versions}")
            applied_tenants[tid] = versions
    if out["errors"]:
        for tid, err in out["errors"].items():
            print(f"  Tenant {tid}: ERROR - {err}")
        if not out["applied"]:
            raise RuntimeError(f"Tenant migrations had errors: {out['errors']}")

    if not applied_default and not applied_tenants:
        print("No new migrations to apply.")
    else:
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run pending DB migrations (default + tenants, or one URL)")
    parser.add_argument("--url", "-u", help="Run migrations only on this database URL (e.g. tenant Supabase URI)")
    args = parser.parse_args()
    try:
        main(url_only=args.url)
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)
