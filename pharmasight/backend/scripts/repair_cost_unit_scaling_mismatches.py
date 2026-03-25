#!/usr/bin/env python3
"""
Repair unit-cost scaling mismatches that cause exaggerated COGS / wrong item cost display.

Scope today (based on your findings):
1) P -ALAXIN: incoming batch cost stored at the wrong unit basis for batch_number='TIAFN066'
   - Detect origin ledger rows (PURCHASE/ADJUSTMENT, quantity_delta>0) for that batch
   - Correct unit_cost by dividing by item.pack_size (e.g. packet price -> per retail/base unit)
   - Repair posted SALE ledger rows for the same batch_number by applying the corrected unit_cost
   - Recompute sales_invoice_items.unit_cost_used from repaired SALE ledger totals

2) MARA MOJA 100`S: item_branch_purchase_snapshot.last_purchase_price is wrong unit basis
   - Set last_purchase_price in item_branch_purchase_snapshot to the latest purchase-like ledger unit_cost
   - Refresh item_branch_snapshot for the item+branch so search prices correct

Safety:
- Default mode is DRY RUN (no writes).
- Use --apply to persist changes.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import normalize_postgres_url, settings
from app.models import (
    InventoryLedger,
    Item,
    ItemBranchPurchaseSnapshot,
    SalesInvoice,
    SalesInvoiceItem,
)
from app.services.item_units_helper import get_unit_multiplier_from_item
from app.services.snapshot_refresh_service import SnapshotRefreshService


def _d(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def _q4(x: Decimal) -> Decimal:
    # Ledger columns are NUMERIC(20,4) in most places; keep stable rounding.
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass
class LedgerRowPlan:
    kind: str  # "origin" or "sale"
    ledger_id: UUID
    batch_number: Optional[str]
    transaction_type: str
    reference_type: Optional[str]
    reference_id: Optional[UUID]
    unit_cost_old: Decimal
    unit_cost_new: Decimal
    quantity_delta: Decimal
    total_cost_old: Decimal
    total_cost_new: Decimal
    created_at: datetime
    invoice_no: Optional[str] = None


def _get_latest_purchase_like_cost(
    db: Session, company_id: UUID, branch_id: UUID, item_id: UUID
) -> tuple[Optional[Decimal], Optional[datetime]]:
    row = (
        db.query(InventoryLedger.unit_cost, InventoryLedger.created_at)
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.transaction_type.in_(["PURCHASE", "ADJUSTMENT"]),
            InventoryLedger.quantity_delta > 0,
            InventoryLedger.unit_cost > 0,
        )
        .order_by(InventoryLedger.created_at.desc())
        .first()
    )
    if not row:
        return None, None
    return _d(row.unit_cost), row.created_at


def _collect_inventory_ledger_plans_for_batch(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    item: Item,
    batch_number: str,
) -> tuple[list[LedgerRowPlan], set[UUID]]:
    """
    Build a plan for:
    - origin rows: transaction_type IN (PURCHASE, ADJUSTMENT), quantity_delta>0
    - sale rows: transaction_type=SALE, reference_type=sales_invoice, batch_number=batch_number
    """
    pack_size = max(1, int(item.pack_size or 1))

    # origin rows: fix incoming cost stored on ledger
    origin_rows = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item.id,
            InventoryLedger.batch_number == batch_number,
            InventoryLedger.transaction_type.in_(["PURCHASE", "ADJUSTMENT"]),
            InventoryLedger.quantity_delta > 0,
            InventoryLedger.unit_cost > 0,
        )
        .order_by(InventoryLedger.created_at.asc())
        .all()
    )

    plans: list[LedgerRowPlan] = []
    affected_invoice_ids: set[UUID] = set()

    for r in origin_rows:
        uc_old = _d(r.unit_cost)
        uc_new = _q4(uc_old / Decimal(str(pack_size)))
        qty = _d(r.quantity_delta)
        plans.append(
            LedgerRowPlan(
                kind="origin",
                ledger_id=r.id,
                batch_number=r.batch_number,
                transaction_type=r.transaction_type,
                reference_type=r.reference_type,
                reference_id=r.reference_id,
                unit_cost_old=uc_old,
                unit_cost_new=uc_new,
                quantity_delta=qty,
                total_cost_old=_d(r.total_cost),
                total_cost_new=_q4(uc_new * qty),
                created_at=r.created_at,
            )
        )

    # sale rows: fix posted COGS valuation
    sale_rows = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item.id,
            InventoryLedger.batch_number == batch_number,
            InventoryLedger.transaction_type == "SALE",
            InventoryLedger.reference_type == "sales_invoice",
        )
        .order_by(InventoryLedger.created_at.asc())
        .all()
    )

    for r in sale_rows:
        uc_old = _d(r.unit_cost)
        uc_new = _q4(uc_old / Decimal(str(pack_size)))
        qty_delta = _d(r.quantity_delta)
        abs_qty = abs(qty_delta)
        if r.reference_id is not None:
            affected_invoice_ids.add(r.reference_id)
        plans.append(
            LedgerRowPlan(
                kind="sale",
                ledger_id=r.id,
                batch_number=r.batch_number,
                transaction_type=r.transaction_type,
                reference_type=r.reference_type,
                reference_id=r.reference_id,
                unit_cost_old=uc_old,
                unit_cost_new=uc_new,
                quantity_delta=qty_delta,
                total_cost_old=_d(r.total_cost),
                total_cost_new=_q4(uc_new * abs_qty),
                created_at=r.created_at,
            )
        )

    return plans, affected_invoice_ids


def _plan_sales_invoice_item_unit_cost_used(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    item: Item,
    batch_number: str,
    affected_invoice_ids: set[UUID],
) -> dict[UUID, dict[str, Decimal]]:
    """
    Returns:
      invoice_id -> {old_unit_cost_used, new_unit_cost_used, qty_base, line_total_exclusive(optional)}
    Assumption (based on your cases): each invoice has at most one SalesInvoiceItem for this item.
    """
    if not affected_invoice_ids:
        return {}

    out: dict[UUID, dict[str, Decimal]] = {}

    # For each invoice, compute current total COGS and the portion from the bad batch.
    for inv_id in affected_invoice_ids:
        items = (
            db.query(SalesInvoiceItem)
            .filter(
                SalesInvoiceItem.sales_invoice_id == inv_id,
                SalesInvoiceItem.item_id == item.id,
            )
            .all()
        )

        if len(items) != 1:
            # Keep this invoice out of auto plan to avoid wrong line assignment.
            continue

        line = items[0]
        mult = get_unit_multiplier_from_item(item, (line.unit_name or "").strip())
        if mult is None or mult <= 0:
            continue
        qty_base = _d(line.quantity) * _d(mult)

        if qty_base <= 0:
            continue

        current_total_cost = (
            db.query(func.coalesce(func.sum(InventoryLedger.total_cost), 0))
            .filter(
                InventoryLedger.company_id == company_id,
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.reference_type == "sales_invoice",
                InventoryLedger.reference_id == inv_id,
                InventoryLedger.item_id == item.id,
                InventoryLedger.transaction_type == "SALE",
            )
            .scalar()
        )
        current_total_cost = _d(current_total_cost)

        bad_rows = (
            db.query(InventoryLedger)
            .filter(
                InventoryLedger.company_id == company_id,
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.reference_type == "sales_invoice",
                InventoryLedger.reference_id == inv_id,
                InventoryLedger.item_id == item.id,
                InventoryLedger.transaction_type == "SALE",
                InventoryLedger.batch_number == batch_number,
            )
            .all()
        )

        bad_current_total_cost = sum((_d(r.total_cost) for r in bad_rows), Decimal("0"))
        pack_size = max(1, int(item.pack_size or 1))
        bad_new_total_cost = Decimal("0")
        for r in bad_rows:
            uc_new = _q4(_d(r.unit_cost) / Decimal(str(pack_size)))
            bad_new_total_cost += _q4(uc_new * abs(_d(r.quantity_delta)))

        new_total_cost = current_total_cost - bad_current_total_cost + bad_new_total_cost
        new_unit_cost_used = _q4(new_total_cost / qty_base)
        old_unit_cost_used = _d(line.unit_cost_used)

        out[inv_id] = {
            "line_unit_cost_used_old": old_unit_cost_used,
            "line_unit_cost_used_new": new_unit_cost_used,
            "qty_base": qty_base,
        }

    return out


def _print_plans(plans: list[LedgerRowPlan], invoice_id_to_no: dict[UUID, str]) -> None:
    print(f"\n--- Ledger rows planned ({len(plans)}) ---")
    origin = [p for p in plans if p.kind == "origin"]
    sale = [p for p in plans if p.kind == "sale"]
    print(f"Origin updates: {len(origin)}")
    print(f"Sale updates:    {len(sale)}")

    # Print origin first, then sale.
    for p in origin + sale:
        inv_no = None
        if p.reference_id and p.reference_id in invoice_id_to_no:
            inv_no = invoice_id_to_no[p.reference_id]
        inv_no_str = f" invoice_no={inv_no}" if inv_no else ""
        print(
            f"  [{p.kind}] ledger_id={str(p.ledger_id)[:8]} batch={p.batch_number!r} "
            f"tt={p.transaction_type} ref_type={p.reference_type!r}{inv_no_str} "
            f"qty_delta={p.quantity_delta} unit_cost {p.unit_cost_old} -> {p.unit_cost_new} "
            f"total_cost {p.total_cost_old} -> {p.total_cost_new} created_at={p.created_at.isoformat()}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Repair unit-cost scaling mismatches (dry-run by default).")
    p.add_argument("--company-id", required=True, help="UUID")
    p.add_argument("--branch-id", required=True, help="UUID")
    p.add_argument("--p-alaxin-item-id", required=True, help="UUID for P -ALAXIN item")
    p.add_argument("--p-alaxin-batch-number", default="TIAFN066", help="Bad batch_number to fix (default: TIAFN066)")
    p.add_argument("--mara-moja-item-id", required=True, help="UUID for MARA MOJA item")
    p.add_argument("--apply", action="store_true", help="Persist changes (default: DRY RUN)")
    args = p.parse_args()

    company_id = UUID(str(args.company_id).strip())
    branch_id = UUID(str(args.branch_id).strip())
    p_alaxin_item_id = UUID(str(args.p_alaxin_item_id).strip())
    mara_moja_item_id = UUID(str(args.mara_moja_item_id).strip())
    batch_number = str(args.p_alaxin_batch_number).strip()

    url = normalize_postgres_url(settings.database_connection_string)
    if not url:
        print("ERROR: No database URL in settings.database_connection_string.")
        sys.exit(1)

    engine = create_engine(url, pool_pre_ping=True)

    with Session(engine) as db:
        p_alaxin_item = db.query(Item).filter(Item.id == p_alaxin_item_id, Item.company_id == company_id).first()
        mara_item = db.query(Item).filter(Item.id == mara_moja_item_id, Item.company_id == company_id).first()

        if not p_alaxin_item:
            print(f"ERROR: P-ALAXIN item not found: {p_alaxin_item_id}")
            sys.exit(1)
        if not mara_item:
            print(f"ERROR: MARA MOJA item not found: {mara_moja_item_id}")
            sys.exit(1)

        print("\n=== Cost unit scaling repair plan ===")
        print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
        print(f"Company: {str(company_id)}")
        print(f"Branch:  {str(branch_id)}")

        # --- P-ALAXIN batch repairs ---
        p_plans, affected_invoice_ids = _collect_inventory_ledger_plans_for_batch(
            db, company_id=company_id, branch_id=branch_id, item=p_alaxin_item, batch_number=batch_number
        )

        invoice_id_to_no = {}
        if affected_invoice_ids:
            rows = (
                db.query(SalesInvoice.id, SalesInvoice.invoice_no)
                .filter(
                    SalesInvoice.company_id == company_id,
                    SalesInvoice.branch_id == branch_id,
                    SalesInvoice.id.in_(list(affected_invoice_ids)),
                )
                .all()
            )
            for rid, ino in rows:
                invoice_id_to_no[rid] = ino or str(rid)

        _print_plans(p_plans, invoice_id_to_no)

        # Plan sales_invoice_items unit_cost_used
        item_line_plan = _plan_sales_invoice_item_unit_cost_used(
            db,
            company_id=company_id,
            branch_id=branch_id,
            item=p_alaxin_item,
            batch_number=batch_number,
            affected_invoice_ids=affected_invoice_ids,
        )

        print("\n--- sales_invoice_items.unit_cost_used planned ---")
        if not item_line_plan:
            print("  (No eligible invoice lines found / multiple lines per invoice not handled automatically.)")
        else:
            for inv_id, meta in item_line_plan.items():
                inv_no = invoice_id_to_no.get(inv_id, str(inv_id))
                print(
                    f"  invoice={inv_no} old_unit_cost_used={meta['line_unit_cost_used_old']} "
                    f"-> new_unit_cost_used={meta['line_unit_cost_used_new']} (qty_base={meta['qty_base']})"
                )

        # --- MARA MOJA snapshot repairs ---
        print("\n=== MARA MOJA snapshot repair ===")
        mara_purch_snap = (
            db.query(ItemBranchPurchaseSnapshot)
            .filter(
                ItemBranchPurchaseSnapshot.company_id == company_id,
                ItemBranchPurchaseSnapshot.branch_id == branch_id,
                ItemBranchPurchaseSnapshot.item_id == mara_item.id,
            )
            .first()
        )
        if not mara_purch_snap:
            print("  Purchase snapshot row not found; cannot repair in this script.")
            sys.exit(1)

        ledger_cost, ledger_cost_dt = _get_latest_purchase_like_cost(db, company_id, branch_id, mara_item.id)
        ledger_cost = _q4(ledger_cost) if ledger_cost is not None else None

        old_last_purchase_price = _d(mara_purch_snap.last_purchase_price)
        print(f"  Old item_branch_purchase_snapshot.last_purchase_price={old_last_purchase_price}")
        print(f"  Ledger-derived latest purchase-like unit_cost={ledger_cost}")

        mara_snapshot_plan_ok = ledger_cost is not None and ledger_cost > 0 and ledger_cost != old_last_purchase_price
        if not mara_snapshot_plan_ok:
            print("  No snapshot update needed (or ledger cost not available / same value).")

        if args.apply:
            # ---------------- Apply writes ----------------
            # 1) Update inventory_ledger unit_cost/total_cost for origin + sale rows
            for plan in p_plans:
                row = db.query(InventoryLedger).filter(InventoryLedger.id == plan.ledger_id).first()
                if not row:
                    continue
                row.unit_cost = plan.unit_cost_new
                row.total_cost = plan.total_cost_new

            # 2) Update SalesInvoiceItem.unit_cost_used for eligible lines
            for inv_id, meta in item_line_plan.items():
                lines = db.query(SalesInvoiceItem).filter(
                    SalesInvoiceItem.sales_invoice_id == inv_id,
                    SalesInvoiceItem.item_id == p_alaxin_item.id,
                ).all()
                # We only update when exactly one line exists (as in planning).
                if len(lines) != 1:
                    continue
                lines[0].unit_cost_used = meta["line_unit_cost_used_new"]

            # 3) Update MARA MOJA purchase snapshot
            if mara_snapshot_plan_ok and ledger_cost is not None and ledger_cost > 0:
                mara_purch_snap.last_purchase_price = ledger_cost
                if ledger_cost_dt is not None:
                    mara_purch_snap.last_purchase_date = ledger_cost_dt

            # 4) Refresh item_branch_snapshot (search display) for MARA MOJA, and optionally P-ALAXIN
            SnapshotRefreshService.refresh_item_sync(db, company_id, branch_id, mara_item.id)
            SnapshotRefreshService.refresh_item_sync(db, company_id, branch_id, p_alaxin_item.id)

            db.commit()
            print("\n=== Apply complete ===")
        else:
            print("\n=== Dry run complete ===")
            print("Re-run with --apply to persist the listed changes.")


if __name__ == "__main__":
    main()

