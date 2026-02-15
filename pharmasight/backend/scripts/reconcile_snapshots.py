"""
Reconcile inventory_balances and item_branch_purchase_snapshot with ledger.
Run from pharmasight/backend: python scripts/reconcile_snapshots.py [--url DATABASE_URL]
"""
import argparse
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings


def reconcile_inventory_balances(db):
    """Find (item_id, branch_id) where ledger SUM != inventory_balances.current_stock."""
    rows = db.execute(
        text("""
            SELECT l.item_id, l.branch_id, l.company_id,
                   COALESCE(SUM(l.quantity_delta), 0) AS ledger_stock,
                   COALESCE(ib.current_stock, 0) AS snapshot_stock
            FROM inventory_ledger l
            LEFT JOIN inventory_balances ib ON ib.item_id = l.item_id AND ib.branch_id = l.branch_id
            GROUP BY l.item_id, l.branch_id, l.company_id, ib.current_stock
            HAVING ABS(COALESCE(SUM(l.quantity_delta), 0) - COALESCE(ib.current_stock, 0)) > 0.0001
        """)
    ).fetchall()
    return rows


def main():
    parser = argparse.ArgumentParser(description="Reconcile snapshot tables with ledger")
    parser.add_argument("--url", "-u", help="Database URL (default: DATABASE_URL env)")
    args = parser.parse_args()
    url = args.url or (getattr(settings, "DATABASE_URL", None) or settings.database_url)
    if not url:
        print("ERROR: No database URL. Set DATABASE_URL or use --url")
        sys.exit(1)

    engine = create_engine(url)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        drift = reconcile_inventory_balances(db)
        if drift:
            print(f"DRIFT: {len(drift)} (item_id, branch_id) pairs where ledger != snapshot")
            for r in drift[:20]:
                print(f"  item={r[0]} branch={r[1]} ledger={r[3]} snapshot={r[4]}")
        else:
            print("OK: inventory_balances in sync with ledger")
    finally:
        db.close()


if __name__ == "__main__":
    main()
