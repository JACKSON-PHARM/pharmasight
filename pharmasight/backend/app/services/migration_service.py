"""
Migration Service - Manages database migrations across all tenants.

Centralized migration system (locked architecture):
- /database/migrations with ordered SQL files (001_*.sql, 002_*.sql, ...)
- schema_migrations table in every tenant DB
- On provisioning: run all migrations
- On deploy/startup: detect and apply missing migrations for ALL tenants
"""
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

# Resolved at import (used by MigrationService and discovery)
_MIGRATIONS_DIR_CANDIDATES = [
    Path(__file__).resolve().parent.parent.parent.parent / "database" / "migrations",  # pharmasight/database/migrations
    Path(__file__).resolve().parent.parent.parent / "database" / "migrations",          # repo root database/migrations
    Path.cwd() / "database" / "migrations",
    Path.cwd() / "pharmasight" / "database" / "migrations",
]


def _get_migrations_dir() -> Path:
    """Return first existing database/migrations dir so migrations run on any deploy layout (e.g. Render)."""
    for d in _MIGRATIONS_DIR_CANDIDATES:
        if d.is_dir():
            return d
    fallback = _MIGRATIONS_DIR_CANDIDATES[0]
    logger.warning(
        "Migrations dir not found (tried %s). App tables may be missing. Fix: ensure 'database/migrations' is deployed.",
        [str(p) for p in _MIGRATIONS_DIR_CANDIDATES],
    )
    return fallback


def _ensure_schema_migrations(conn) -> None:
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.close()


def _get_applied_versions(conn) -> Set[str]:
    cur = conn.cursor()
    cur.execute("SELECT version FROM schema_migrations")
    applied = {r[0] for r in cur.fetchall()}
    cur.close()
    return applied


def _discover_migration_files() -> List[tuple[str, Path]]:
    """Return ordered (version, path) for migrations. Version = stem (e.g. 001_initial)."""
    migrations_dir = _get_migrations_dir()
    if not migrations_dir.is_dir():
        return []
    out = []
    for p in sorted(migrations_dir.iterdir()):
        if p.suffix.lower() != ".sql":
            continue
        stem = p.stem
        if re.match(r"^\d{3}_", stem):
            out.append((stem, p))
    return out


def get_public_table_count(database_url: str) -> int:
    """
    Return number of tables in public schema.
    Used to enforce initialize-only on empty DBs and to verify migrations created tables.
    """
    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        n = cur.fetchone()[0]
        cur.close()
        return int(n)
    finally:
        conn.close()


def _baseline_existing_db(conn) -> Optional[str]:
    """
    If DB has app tables (companies) but no migrations recorded, mark 001_initial applied.
    Returns version baseline'd or None.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'companies'
        )
    """)
    has_companies = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM schema_migrations")
    n = cur.fetchone()[0]
    cur.close()
    if not has_companies or n > 0:
        return None
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES ('001_initial', NOW()) ON CONFLICT (version) DO NOTHING"
    )
    cur.close()
    return "001_initial"


def run_migrations_for_url(database_url: str) -> List[str]:
    """
    Run all missing migrations on the given tenant DB URL.
    Ensures schema_migrations exists, optionally baselines existing DBs, then runs ordered files.
    Returns list of versions applied this run. Always brings DB to latest version.
    """
    applied_this_run: List[str] = []
    conn = psycopg2.connect(database_url)

    try:
        _ensure_schema_migrations(conn)
        baseline = _baseline_existing_db(conn)
        if baseline:
            applied_this_run.append(baseline)

        applied = _get_applied_versions(conn)
        files = _discover_migration_files()
        if not files:
            print("  [Migrations] WARNING: No migration files found. App tables may be missing.")
            logger.warning(
                "No migration files found in %s. App tables (companies, users, branches, etc.) will not exist. Check that 'database/migrations' is present in the deployed app.",
                _get_migrations_dir(),
            )
        for version, path in files:
            if version in applied:
                continue
            print(f"  [Migrations] Applying {version}...")
            sql = path.read_text(encoding="utf-8", errors="replace")
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = conn.cursor()
            try:
                cur.execute(sql)
            except Exception as e:
                cur.close()
                conn.close()
                raise RuntimeError(f"Migration {version} failed: {e}") from e
            cur.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, NOW()) ON CONFLICT (version) DO NOTHING",
                (version,),
            )
            cur.close()
            applied.add(version)
            applied_this_run.append(version)
            print(f"  [Migrations]   -> {version} OK")
            logger.info("Applied migration %s on %s", version, database_url[:50])

    finally:
        conn.close()

    return applied_this_run


def ensure_master_tenant_storage_columns(database_url: str) -> bool:
    """
    Ensure the tenants table (master DB only) has supabase_storage_url and supabase_storage_service_role_key.
    Run this on the default/master DB URL before querying Tenant. Idempotent (ADD COLUMN IF NOT EXISTS).
    Returns True if run (and no error), False if skipped (e.g. no tenants table).
    """
    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'tenants'
            )
        """)
        if not cur.fetchone()[0]:
            cur.close()
            conn.close()
            return False
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur.execute("""
            ALTER TABLE tenants
                ADD COLUMN IF NOT EXISTS supabase_storage_url TEXT,
                ADD COLUMN IF NOT EXISTS supabase_storage_service_role_key TEXT
        """)
        cur.close()
        conn.close()
        logger.info("Master DB: ensured tenants.supabase_storage_* columns exist")
        return True
    except Exception as e:
        logger.warning("ensure_master_tenant_storage_columns failed: %s", e)
        raise


class MigrationService:
    """Service for applying migrations to all tenant databases."""

    def __init__(self):
        self.migrations_dir = str(_get_migrations_dir())

    def get_all_tenants_with_db(self) -> List[Tenant]:
        """Tenants that have database_url set (for migration runs)."""
        db = MasterSessionLocal()
        try:
            return db.query(Tenant).filter(Tenant.database_url.isnot(None), Tenant.database_url != "").all()
        finally:
            db.close()

    def get_all_tenants(self, db, status_filter: Optional[str] = None) -> List[Tenant]:
        """Get all active tenants"""
        query = db.query(Tenant)
        
        if status_filter:
            query = query.filter(Tenant.status == status_filter)
        else:
            # Only migrate active tenants (not suspended/cancelled)
            query = query.filter(Tenant.status.in_(['trial', 'active']))
        
        return query.all()
    
    def get_tenant_schema_version(self, database_url: str) -> Optional[str]:
        """Get current schema version from tenant database"""
        try:
            conn = psycopg2.connect(database_url)
            cursor = conn.cursor()
            
            # Check if migrations table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'schema_migrations'
                )
            """)
            
            if not cursor.fetchone()[0]:
                # Create migrations table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version VARCHAR(50) PRIMARY KEY,
                        applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                return None
            
            # Get latest version
            cursor.execute("""
                SELECT version FROM schema_migrations 
                ORDER BY applied_at DESC 
                LIMIT 1
            """)
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            return result[0] if result else None
        
        except Exception as e:
            logger.warning("Error getting schema version: %s", e)
            return None

    def run_migrations_all_tenant_dbs(self) -> Dict:
        """
        Apply missing migrations for ALL tenants with database_url (startup/deploy).
        Only runs for tenants with status trial or active (respects subscription/cancelled).
        Returns { "applied": { tenant_id: [versions] }, "errors": { tenant_id: str } }.
        """
        applied: Dict[str, List[str]] = {}
        errors: Dict[str, str] = {}
        tenants_with_db = self.get_all_tenants_with_db()
        # Only migrate active tenants (trial, active); skip suspended/cancelled
        tenants_to_migrate = [t for t in tenants_with_db if (t.status or "").lower() in ("trial", "active")]
        for t in tenants_to_migrate:
            try:
                ran = run_migrations_for_url(t.database_url)
                if ran:
                    applied[str(t.id)] = ran
            except Exception as e:
                err_str = str(e)
                if "Network is unreachable" in err_str and "supabase.co" in (t.database_url or ""):
                    err_str += " (On Render, use Supabase connection pooler URL instead of db.xxx.supabase.co – see RENDER.md)"
                if "Tenant or user not found" in err_str:
                    err_str += " (Supabase project was deleted; point tenant at single DB or run: python scripts/mark_tenant_cancelled.py <tenant_id_or_name>)"
                errors[str(t.id)] = err_str
                logger.exception("Migrations failed for tenant %s: %s", t.name, e)
        return {"applied": applied, "errors": errors}

    def apply_migration(
        self,
        tenant: Tenant,
        migration_sql: str,
        version: str
    ) -> Dict:
        """
        Apply a migration to a single tenant database
        
        Returns:
            Dict with status: 'success', 'failed', 'skipped'
        """
        if not tenant.database_url:
            return {
                "status": "failed",
                "error": "No database URL configured",
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name
            }
        
        try:
            conn = psycopg2.connect(tenant.database_url)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            
            # Check if migration already applied
            current_version = self.get_tenant_schema_version(tenant.database_url)
            if current_version == version:
                cursor.close()
                conn.close()
                return {
                    "status": "skipped",
                    "message": "Migration already applied",
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name
                }
            
            # Apply migration
            cursor.execute(migration_sql)
            
            # Record migration
            cursor.execute("""
                INSERT INTO schema_migrations (version, applied_at)
                VALUES (%s, %s)
                ON CONFLICT (version) DO NOTHING
            """, (version, datetime.utcnow()))
            
            cursor.close()
            conn.close()
            
            return {
                "status": "success",
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "version": version
            }
        
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name
            }
    
    def run_migration_for_all_tenants(
        self,
        migration_sql: str,
        version: str,
        tenant_ids: Optional[List[str]] = None
    ) -> Dict:
        """
        Run a migration for all tenants
        
        Args:
            migration_sql: SQL to execute
            version: Migration version identifier
            tenant_ids: Optional list of tenant IDs to migrate (if None, migrate all)
        
        Returns:
            Dict with results per tenant
        """
        db = MasterSessionLocal()
        results = []
        
        try:
            if tenant_ids:
                tenants = db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()
            else:
                tenants = self.get_all_tenants(db)
            
            for tenant in tenants:
                result = self.apply_migration(tenant, migration_sql, version)
                results.append(result)
            
            return {
                "total": len(tenants),
                "success": len([r for r in results if r["status"] == "success"]),
                "failed": len([r for r in results if r["status"] == "failed"]),
                "skipped": len([r for r in results if r["status"] == "skipped"]),
                "results": results
            }
        
        finally:
            db.close()
    
    def get_migration_status(self) -> Dict:
        """Get migration status for all tenants"""
        db = MasterSessionLocal()
        status_report = []
        
        try:
            tenants = self.get_all_tenants(db)
            
            for tenant in tenants:
                version = self.get_tenant_schema_version(tenant.database_url) if tenant.database_url else None
                status_report.append({
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name,
                    "subdomain": tenant.subdomain,
                    "schema_version": version,
                    "database_configured": bool(tenant.database_url)
                })
            
            return {
                "total_tenants": len(tenants),
                "tenants": status_report
            }
        
        finally:
            db.close()


# Example usage:
# """
# # Apply a migration to all tenants
# migration_service = MigrationService()
# 
# migration_sql = """
#     ALTER TABLE items ADD COLUMN IF NOT EXISTS new_field VARCHAR(255);
# """
# 
# result = migration_service.run_migration_for_all_tenants(
#     migration_sql=migration_sql,
#     version="20240127_add_new_field"
# )
# 
# print(f"Success: {result['success']}, Failed: {result['failed']}")
# 
# # Get status
# status = migration_service.get_migration_status()
# """
