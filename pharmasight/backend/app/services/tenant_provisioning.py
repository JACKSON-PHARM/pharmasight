"""
Tenant DB provisioning for database-per-tenant architecture.

Provisioning model (locked):
- Supabase project creation: MANUAL. Human creates project, admin pastes DB URL.
- Tenant DB provisioning: AUTOMATED. Accepts existing Postgres DB URL, applies
  schema via migrations, stores tenant.database_url in master. DB URL is
  IMMUTABLE after provisioning.

Authority: locked architecture. One Supabase project per tenant.

Initialize flow (admin UI): empty DB only. Verify tables exist before marking provisioned.
"""
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.dependencies import _session_factory_for_url
from app.models.tenant import Tenant
from app.models.user import User
from app.services.migration_service import (
    get_public_table_count,
    run_migrations_for_url,
)
from app.utils.username_generator import generate_username_from_name

logger = logging.getLogger(__name__)


def _sanitize_db_name(subdomain: str) -> str:
    """Produce a safe Postgres database name from subdomain."""
    s = re.sub(r"[^a-z0-9_]", "_", str(subdomain).lower().strip())
    return s or "tenant"


def provision_tenant_db_from_url(
    tenant: Tenant,
    master_db: Session,
    database_url: str,
) -> str:
    """
    Run migrations on an *existing* database and set tenant.database_url.

    Use when CREATE DATABASE is not available (e.g. Supabase). Human creates
    Supabase project, admin pastes DB URL. We run migrations and register.

    - database_url is IMMUTABLE after provisioning; reject if already set.
    - Connects to database_url, runs all migrations from /database/migrations.
    - Updates tenant.database_name and tenant.database_url in master, commits.

    Returns:
        database_url (same as input).
    """
    if tenant.database_url:
        raise RuntimeError(
            f"Tenant {tenant.name} already has database_url; DB URL is immutable after provisioning."
        )

    dbname = f"pharmasight_{_sanitize_db_name(tenant.subdomain)}"
    run_migrations_for_url(database_url)

    tenant.database_name = dbname
    tenant.database_url = database_url
    master_db.commit()

    logger.info("Provisioned tenant DB (from URL): %s (%s)", tenant.name, dbname)
    return database_url


def _username_for_tenant(tenant: Tenant, tenant_db: Session) -> str:
    """Generate username from tenant admin info. Uses tenant DB for uniqueness."""
    try:
        return generate_username_from_name(tenant.admin_full_name or "", db_session=tenant_db)
    except Exception:
        pass
    email_local = tenant.admin_email.split("@")[0]
    name_parts = email_local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    if len(name_parts) >= 2:
        try:
            return generate_username_from_name(" ".join(name_parts), db_session=tenant_db)
        except Exception:
            pass
    return f"{email_local[0].upper()}-{email_local.upper()[:10]}"


def initialize_tenant_database(
    tenant: Tenant,
    master_db: Session,
    database_url: str,
) -> dict:
    """
    Initialize tenant database (admin-driven flow). STRICT.

    - Connects to database_url, checks public table count.
    - If count > 0: raise RuntimeError "Database already initialized. Refusing to run migrations."
    - If count == 0: run migrations, verify tables exist, create initial tenant admin user,
      then persist database_url, database_name, is_provisioned, provisioned_at in master.
    - On any failure, do NOT mark tenant as provisioned.

    Allowed when database_url is null OR database_url set but DB has zero tables (re-init).
    """
    url = database_url.strip()
    n = get_public_table_count(url)
    if n > 0:
        raise RuntimeError("Database already initialized. Refusing to run migrations.")

    run_migrations_for_url(url)
    n_after = get_public_table_count(url)
    if n_after == 0:
        raise RuntimeError("Migrations ran but no tables found. Initialization failed.")

    dbname = f"pharmasight_{_sanitize_db_name(tenant.subdomain)}"
    factory = _session_factory_for_url(url)
    tenant_db = factory()
    try:
        username = _username_for_tenant(tenant, tenant_db)
        temp_id = uuid.uuid4()
        user = User(
            id=temp_id,
            email=tenant.admin_email,
            username=username,
            full_name=tenant.admin_full_name,
            phone=tenant.phone,
            is_active=True,
            is_pending=True,
            password_set=False,
        )
        tenant_db.add(user)
        tenant_db.commit()
    except Exception as e:
        tenant_db.rollback()
        raise RuntimeError(f"Failed to create initial tenant admin user: {e}") from e
    finally:
        tenant_db.close()

    now = datetime.now(timezone.utc)
    tenant.database_name = dbname
    tenant.database_url = url
    tenant.is_provisioned = True
    tenant.provisioned_at = now
    master_db.commit()

    logger.info("Initialized tenant DB: %s (%s), is_provisioned=True", tenant.name, dbname)
    return {"database_name": dbname, "provisioned_at": now}
