#!/usr/bin/env python3
"""
Audit one item's cost/price storage: confirm values are per retail (base) unit, not per packet.

Use when a user sees e.g. purchase_price 115 (price of 1 packet) displayed as price per tablet,
so selling 1 packet suggests 115 * 28 = wrong total.

Checks:
  1) schema_migrations: was 066 applied?
  2) items.default_cost_per_base: should be per retail (after 066).
  3) inventory_ledger: unit_cost for OPENING_BALANCE / PURCHASE should be per retail.
  4) item_branch_snapshot: average_cost, effective_selling_price should be per retail.

Run from pharmasight/backend with PYTHONPATH=.
  python -m scripts.audit_item_cost_units 9d6e6bc9-dca9-4fac-97c1-deac8570474c
"""
import sys
from uuid import UUID

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.audit_item_cost_units <item_id>")
        sys.exit(1)
    item_id = sys.argv[1]
    try:
        UUID(item_id)
    except ValueError:
        print("Invalid item_id UUID:", item_id)
        sys.exit(1)

    try:
        from sqlalchemy import text
        from app.database import SessionLocal
    except ImportError as e:
        print("Import error. Run from backend with PYTHONPATH=.", e)
        sys.exit(1)

    db = SessionLocal()
    try:
        # 1) Migration 066 applied?
        row = db.execute(
            text("SELECT version, applied_at FROM schema_migrations WHERE version = '066_backfill_ledger_opening_balance_default_cost_snapshot'")
        ).fetchone()
        if row:
            print("1) Migration 066: APPLIED at", row[1])
        else:
            print("1) Migration 066: NOT APPLIED (or different version name)")

        # 2) Item master: pack_size, default_cost_per_base
        item = db.execute(
            text("SELECT id, name, pack_size, default_cost_per_base, retail_unit, wholesale_unit FROM items WHERE id = :id"),
            {"id": item_id},
        ).fetchone()
        if not item:
            print("Item not found:", item_id)
            return
        name, pack_size, default_cost, retail_unit, wholesale_unit = item[1], item[2], item[3], item[4], item[5]
        pack_size = int(pack_size or 1)
        print(f"\n2) Item: {name}")
        print(f"   pack_size={pack_size}, retail_unit={retail_unit}, wholesale_unit={wholesale_unit}")
        print(f"   default_cost_per_base={default_cost}")
        if pack_size > 1 and default_cost is not None:
            as_packet = float(default_cost) * pack_size
            print(f"   (if this were per tablet: 1 packet would cost {as_packet:.2f})")

        # 3) Ledger: unit_cost by transaction type
        ledger = db.execute(
            text("""
                SELECT transaction_type, reference_type, branch_id, unit_cost, quantity_delta, created_at
                FROM inventory_ledger
                WHERE item_id = :id
                ORDER BY branch_id, created_at DESC
                LIMIT 20
            """),
            {"id": item_id},
        ).fetchall()
        print(f"\n3) inventory_ledger (last 20 rows):")
        if not ledger:
            print("   No rows.")
        else:
            for r in ledger:
                tt, ref, bid, uc, qty, created = r[0], r[1], r[2], r[3], r[4], str(r[5])[:19]
                uc_val = float(uc) if uc is not None else None
                if uc_val is not None and pack_size > 1:
                    as_packet = uc_val * pack_size
                    print(f"   {tt} {ref} branch={str(bid)[:8]} unit_cost={uc_val:.4f} qty_delta={qty} (if per tablet -> 1 packet={as_packet:.2f}) {created}")
                else:
                    print(f"   {tt} {ref} branch={str(bid)[:8]} unit_cost={uc_val} qty_delta={qty} {created}")

        # 4) Snapshot per branch
        snap = db.execute(
            text("""
                SELECT branch_id, average_cost, last_purchase_price, selling_price, effective_selling_price, updated_at
                FROM item_branch_snapshot
                WHERE item_id = :id
            """),
            {"id": item_id},
        ).fetchall()
        print(f"\n4) item_branch_snapshot (all branches):")
        if not snap:
            print("   No rows (snapshot missing for this item).")
        else:
            for r in snap:
                bid, avg, lpp, sell, eff, updated = r[0], r[1], r[2], r[3], r[4], str(r[5])[:19]
                avg_f = float(avg) if avg is not None else None
                eff_f = float(eff) if eff is not None else None
                if pack_size > 1 and (avg_f is not None or eff_f is not None):
                    avg_packet = (avg_f * pack_size) if avg_f else None
                    eff_packet = (eff_f * pack_size) if eff_f else None
                    print(f"   branch={str(bid)[:8]} average_cost={avg_f} effective_selling_price={eff_f} (if per tablet -> 1 packet cost={avg_packet} sale={eff_packet}) {updated}")
                else:
                    print(f"   branch={str(bid)[:8]} average_cost={avg_f} effective_selling_price={eff_f} {updated}")

        print("\n--- Interpretation ---")
        print("After migration 066, unit_cost and default_cost_per_base should be per RETAIL (e.g. per tablet).")
        print("So for pack_size=28, packet price 115 -> per-tablet should be 115/28 ~ 4.11.")
        print("If you still see 115 in snapshot or API, either 066 did not run, or snapshot was not refreshed for that branch.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
