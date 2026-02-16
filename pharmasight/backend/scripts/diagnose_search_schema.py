"""
Diagnose search schema: migrations, indexes, constraints.
Run: python scripts/diagnose_search_schema.py
Uses DATABASE_URL or tenant DB from config.
"""
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    from app.config import settings
    import psycopg2

    url = os.environ.get("DATABASE_URL") or settings.database_connection_string
    if not url:
        print("No DATABASE_URL or database_connection_string configured")
        return 1

    conn = psycopg2.connect(url)
    cur = conn.cursor()

    print("=== Schema Diagnostic for Search Speed ===\n")

    # 1. Migrations
    cur.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version")
    rows = cur.fetchall()
    print("Applied migrations:")
    for r in rows:
        print(f"  {r[0]} @ {r[1]}")
    has_023 = any("023" in str(r[0]) for r in rows)
    has_024 = any("024" in str(r[0]) for r in rows)
    print(f"\n  023 (snapshot tables): {'OK' if has_023 else 'MISSING'}")
    print(f"  024 (search snapshot + GIN): {'OK' if has_024 else 'MISSING'}")

    # 2. UNIQUE constraints on snapshot tables
    cur.execute("""
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid IN (
            'inventory_balances'::regclass,
            'item_branch_purchase_snapshot'::regclass,
            'item_branch_search_snapshot'::regclass
        )
        AND contype = 'u'
    """)
    rows = cur.fetchall()
    print("\nUNIQUE constraints on snapshot tables:")
    for r in rows:
        print(f"  {r[0]}: {r[1]} -> {r[2]}")
    if not rows:
        print("  NONE - migrations 023/024 may not have run correctly")

    # 3. Indexes on items
    cur.execute("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'items' AND indexname LIKE 'idx_%'
    """)
    rows = cur.fetchall()
    print("\nIndexes on items:")
    for r in rows:
        print(f"  {r[0]}")
    has_trgm = any("trgm" in str(r[0]) for r in rows)
    print(f"  GIN trigram (for ILIKE): {'OK' if has_trgm else 'MISSING'}")

    # 4. pg_trgm extension
    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    has_trgm_ext = cur.fetchone() is not None
    print(f"\npg_trgm extension: {'OK' if has_trgm_ext else 'MISSING'}")

    # 5. Snapshot table row counts
    for t in ["inventory_balances", "item_branch_purchase_snapshot", "item_branch_search_snapshot"]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            n = cur.fetchone()[0]
            print(f"\n{t}: {n} rows")
        except Exception as e:
            print(f"\n{t}: table missing or error - {e}")

    cur.close()
    conn.close()
    print("\n=== Done ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
