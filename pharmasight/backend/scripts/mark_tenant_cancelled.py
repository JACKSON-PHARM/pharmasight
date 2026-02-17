"""
Mark a tenant as cancelled so migrations (and the app) skip its deleted database.

Use this after you delete a Supabase/tenant project: the app still has the tenant
in the master DB and will try to run migrations against its database_url, which
fails with "Tenant or user not found". Marking the tenant as cancelled stops
migrations from running for it (only 'trial' and 'active' tenants are migrated).

Usage (from pharmasight/backend):
  python scripts/mark_tenant_cancelled.py 755e905c-7e95-4648-bb18-0ea88ec9d1ca
  python scripts/mark_tenant_cancelled.py "PHARMASIGHT MEDS LTD"
  python scripts/mark_tenant_cancelled.py --list   # list tenants with database_url set
"""
import argparse
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant


def main():
    parser = argparse.ArgumentParser(description="Mark a tenant as cancelled (skip migrations for deleted DBs)")
    parser.add_argument(
        "tenant",
        nargs="?",
        help="Tenant ID (UUID) or name (e.g. 'PHARMASIGHT MEDS LTD')",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all tenants that have a database_url (and their status)",
    )
    parser.add_argument(
        "--clear-url",
        action="store_true",
        help="Also set database_url to NULL so the tenant is never considered for migration",
    )
    args = parser.parse_args()

    db = MasterSessionLocal()
    try:
        if args.list:
            tenants = db.query(Tenant).filter(
                Tenant.database_url.isnot(None),
                Tenant.database_url != "",
            ).all()
            if not tenants:
                print("No tenants with database_url set.")
                return 0
            print("Tenants with database_url (migration will run for trial/active):")
            for t in tenants:
                print(f"  {t.id}  {t.name!r}  status={t.status}")
            return 0

        if not args.tenant:
            parser.error("Provide tenant ID or name, or use --list")
            return 1

        tenant_arg = args.tenant.strip()
        # Try by UUID first
        tenant = db.query(Tenant).filter(Tenant.id == tenant_arg).first()
        if not tenant:
            tenant = db.query(Tenant).filter(Tenant.name == tenant_arg).first()
        if not tenant:
            # Case-insensitive name match
            tenant = db.query(Tenant).filter(Tenant.name.ilike(tenant_arg)).first()
        if not tenant:
            print(f"Tenant not found: {args.tenant}")
            return 1

        old_status = tenant.status
        tenant.status = "cancelled"
        if args.clear_url:
            tenant.database_url = None
        db.commit()
        print(f"Tenant {tenant.name!r} ({tenant.id}) set to status=cancelled (was {old_status}).")
        if args.clear_url:
            print("  database_url cleared.")
        print("Restart the app; migrations will no longer run for this tenant.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
