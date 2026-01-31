"""
Provision a tenant database (migrations-only) and set tenant.database_url.

Locked model: each tenant = own Supabase project. Human creates project, admin
pastes DB URL. We run migrations and register. DB URL is immutable after provision.

Usage:
  python provision_tenant_db.py "PHARMASIGHT MEDS LTD" --url "postgresql://user:pass@host:5432/postgres"
  python provision_tenant_db.py --subdomain pharmasight-meds-ltd --url "postgresql://..."
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant
from app.services.tenant_provisioning import provision_tenant_db_from_url


def main(
    name_or_subdomain: str | None = None,
    *,
    subdomain: str | None = None,
    url: str | None = None,
) -> None:
    if not url or not url.strip():
        print("ERROR: --url is required. Create a Supabase project, then pass its direct Postgres URL.")
        sys.exit(1)

    db = MasterSessionLocal()
    try:
        if subdomain:
            tenant = db.query(Tenant).filter(Tenant.subdomain == subdomain).first()
        elif name_or_subdomain:
            s = name_or_subdomain.strip()
            by_name = db.query(Tenant).filter(Tenant.name.ilike(f"%{s}%")).first()
            by_sub = db.query(Tenant).filter(Tenant.subdomain == s.lower().replace(" ", "")).first()
            tenant = by_name or by_sub
        else:
            tenant = db.query(Tenant).filter(Tenant.name.ilike("%PHARMASIGHT MEDS LTD%")).first()

        if not tenant:
            print("No tenant found. Pass name or --subdomain.")
            sys.exit(1)

        print(f"Provisioning tenant DB for: {tenant.name} ({tenant.subdomain})")
        out = provision_tenant_db_from_url(tenant, db, url.strip())
        print(f"✓ Tenant DB provisioned: {tenant.database_name}")
        print(f"  database_url: {out[:60]}...")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Provision tenant database (--url required)")
    p.add_argument("name", nargs="?", help="Tenant name or subdomain")
    p.add_argument("--subdomain", "-s", help="Tenant subdomain")
    p.add_argument("--url", "-u", required=True, help="Existing Postgres URL (e.g. new Supabase project)")
    args = p.parse_args()
    main(args.name, subdomain=args.subdomain, url=args.url)
