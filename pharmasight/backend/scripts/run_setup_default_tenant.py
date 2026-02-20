"""
Run the default-tenant setup: insert/update a tenant in the master DB whose
database_url equals this app's DATABASE_URL so stamp/signature/PO PDF work
without X-Tenant-* headers.

Usage (from backend directory):
  python scripts/run_setup_default_tenant.py
"""
import sys
from pathlib import Path

# Ensure backend root is on path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from sqlalchemy import text
from app.config import settings
from app.database_master import master_engine


def main():
    url = settings.database_connection_string
    if not url:
        print("ERROR: DATABASE_URL is not set in .env")
        sys.exit(1)

    sql = """
    INSERT INTO tenants (
        id,
        name,
        subdomain,
        database_url,
        status,
        admin_email
    ) VALUES (
        'a0000000-0000-0000-0000-000000000001'::uuid,
        'Default (Development)',
        'default',
        :database_url,
        'active',
        'dev@localhost'
    )
    ON CONFLICT (subdomain) DO UPDATE SET
        database_url = EXCLUDED.database_url,
        name = EXCLUDED.name,
        status = EXCLUDED.status,
        updated_at = CURRENT_TIMESTAMP;
    """
    with master_engine.connect() as conn:
        conn.execute(text(sql), {"database_url": url})
        conn.commit()
    print("Default tenant setup complete. Stamp/signature/PO approve will work without tenant headers.")


if __name__ == "__main__":
    main()
