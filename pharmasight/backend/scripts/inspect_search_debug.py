"""
Run search-debug logic against the DB and print result (no HTTP/auth).
Use same company_id, branch_id, and q as the failing search.

Usage (from backend directory):
  python scripts/inspect_search_debug.py
"""
import json
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.database import SessionLocal
from app.models import Item, ItemBranchSnapshot, InventoryLedger

COMPANY_ID = "9c71915e-3e59-45d5-9719-56d2322ff673"
BRANCH_ID = "bec5d46a-7f21-45ef-945c-8c68171aa386"
SEARCH_Q = "test it"
LIMIT = 10


def main():
    from uuid import UUID
    company_id = UUID(COMPANY_ID)
    branch_id = UUID(BRANCH_ID)
    search_term_pattern = f"%{SEARCH_Q.lower()}%"

    db = SessionLocal()
    try:
        rows = (
            db.query(ItemBranchSnapshot)
            .filter(
                ItemBranchSnapshot.company_id == company_id,
                ItemBranchSnapshot.branch_id == branch_id,
                ItemBranchSnapshot.search_text.ilike(search_term_pattern),
            )
            .order_by(
                (ItemBranchSnapshot.current_stock <= 0).asc(),
                ItemBranchSnapshot.name.asc(),
            )
            .limit(LIMIT)
            .all()
        )

        debug_list = []
        for snap in rows:
            item = db.query(Item).filter(
                Item.id == snap.item_id,
                Item.company_id == company_id,
            ).first()
            ledger_rows = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.item_id == snap.item_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.company_id == company_id,
                )
                .order_by(InventoryLedger.created_at.asc())
                .all()
            )
            debug_list.append({
                "item_id": str(snap.item_id),
                "name": snap.name,
                "sku": snap.sku,
                "snapshot": {
                    "last_purchase_price": float(snap.last_purchase_price) if snap.last_purchase_price is not None else None,
                    "average_cost": float(snap.average_cost) if snap.average_cost is not None else None,
                    "effective_selling_price": float(snap.effective_selling_price) if snap.effective_selling_price is not None else None,
                    "price_source": snap.price_source,
                    "selling_price": float(snap.selling_price) if snap.selling_price is not None else None,
                    "margin_percent": float(snap.margin_percent) if snap.margin_percent is not None else None,
                    "promotion_active": bool(snap.promotion_active) if snap.promotion_active is not None else False,
                    "promotion_price": float(snap.promotion_price) if snap.promotion_price is not None else None,
                    "floor_price": float(snap.floor_price) if snap.floor_price is not None else None,
                    "current_stock": float(snap.current_stock) if snap.current_stock is not None else 0,
                    "last_purchase_date": snap.last_purchase_date.isoformat() if snap.last_purchase_date else None,
                    "updated_at": snap.updated_at.isoformat() if snap.updated_at else None,
                },
                "ledger": [
                    {
                        "transaction_type": le.transaction_type,
                        "reference_type": le.reference_type,
                        "unit_cost": float(le.unit_cost) if le.unit_cost is not None else None,
                        "quantity_delta": float(le.quantity_delta) if le.quantity_delta is not None else None,
                        "remaining_quantity": int(le.remaining_quantity) if le.remaining_quantity is not None else None,
                        "created_at": le.created_at.isoformat() if le.created_at else None,
                    }
                    for le in ledger_rows
                ],
                "item_units": {
                    "pack_size": int(item.pack_size) if item and item.pack_size is not None else 1,
                    "retail_unit": (item.retail_unit or "").strip() if item else None,
                    "wholesale_unit": (item.wholesale_unit or item.base_unit if item else "").strip() if item else None,
                    "supplier_unit": (item.supplier_unit or "").strip() if item else None,
                } if item else {},
            })

        out = {
            "query": {"q": SEARCH_Q, "company_id": COMPANY_ID, "branch_id": BRANCH_ID},
            "count": len(debug_list),
            "debug": debug_list,
        }
        print(json.dumps(out, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
    sys.exit(0)
