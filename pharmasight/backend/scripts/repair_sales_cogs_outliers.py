#!/usr/bin/env python3
"""
Repair stale sales COGS outliers in a controlled way.

Default mode is DRY RUN (no writes). Use --apply to persist changes.

Scope and safety:
- Targets only sales lines where captured unit_cost_used is above selling price.
- Requires a valid purchase snapshot cost lower than captured unit cost.
- Repairs only lines with exactly one SALE ledger row (to avoid disturbing true multi-layer FEFO rows).
- Updates both:
  1) sales_invoice_items.unit_cost_used
  2) inventory_ledger.unit_cost/total_cost for the matching SALE row

Usage:
  cd pharmasight/backend
  ..\\venv\\Scripts\\python scripts\\repair_sales_cogs_outliers.py \\
    --branch-id <branch_uuid> \\
    --company-id <company_uuid> \\
    --start-date 2026-03-24 \\
    --end-date 2026-03-24

Apply writes:
  ..\\venv\\Scripts\\python scripts\\repair_sales_cogs_outliers.py ... --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, selectinload

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import normalize_postgres_url, settings
from app.models import InventoryLedger, ItemBranchPurchaseSnapshot, SalesInvoice, SalesInvoiceItem
from app.services.item_units_helper import get_unit_multiplier_from_item


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


@dataclass
class Candidate:
    invoice_id: UUID
    invoice_no: str
    line_id: UUID
    item_id: UUID
    item_name: str
    unit_name: str
    qty_sale: Decimal
    qty_base: Decimal
    unit_price_ex: Decimal
    old_unit_cost: Decimal
    new_unit_cost: Decimal
    old_line_cogs: Decimal
    new_line_cogs: Decimal
    ledger_id: UUID
    ledger_qty_delta: Decimal
    ledger_total_cost_old: Decimal
    ledger_total_cost_new: Decimal


def _load_candidates(
    db: Session,
    branch_id: UUID,
    company_id: UUID,
    start_date: date,
    end_date: date,
) -> tuple[list[Candidate], list[str]]:
    warnings: list[str] = []
    candidates: list[Candidate] = []

    invoices = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
        .filter(
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.company_id == company_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            SalesInvoice.invoice_date.between(start_date, end_date),
        )
        .all()
    )

    for inv in invoices:
        for line in inv.items or []:
            sale_price = _d(line.unit_price_exclusive)
            old_uc = _d(line.unit_cost_used)
            if sale_price <= 0 or old_uc <= 0:
                continue
            if old_uc <= sale_price:
                continue

            ps = (
                db.query(ItemBranchPurchaseSnapshot)
                .filter(
                    ItemBranchPurchaseSnapshot.branch_id == branch_id,
                    ItemBranchPurchaseSnapshot.item_id == line.item_id,
                )
                .first()
            )
            snap_cost = _d(getattr(ps, "last_purchase_price", None))
            if snap_cost <= 0:
                warnings.append(
                    f"Skip {inv.invoice_no} {line.item_name}: missing purchase snapshot cost."
                )
                continue
            if snap_cost >= old_uc:
                warnings.append(
                    f"Skip {inv.invoice_no} {line.item_name}: snapshot cost ({snap_cost}) not lower than old cost ({old_uc})."
                )
                continue

            item = line.item
            if not item:
                warnings.append(f"Skip {inv.invoice_no} line {line.id}: missing item relation.")
                continue
            mult = get_unit_multiplier_from_item(item, (line.unit_name or "").strip())
            if mult is None or mult <= 0:
                warnings.append(
                    f"Skip {inv.invoice_no} {line.item_name}: invalid unit multiplier for unit={line.unit_name!r}."
                )
                continue

            sale_rows = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.transaction_type == "SALE",
                    InventoryLedger.reference_type == "sales_invoice",
                    InventoryLedger.reference_id == inv.id,
                    InventoryLedger.item_id == line.item_id,
                )
                .order_by(InventoryLedger.created_at.asc())
                .all()
            )
            if len(sale_rows) != 1:
                warnings.append(
                    f"Skip {inv.invoice_no} {line.item_name}: has {len(sale_rows)} SALE ledger rows (expected 1)."
                )
                continue

            sale_row = sale_rows[0]
            qty_sale = _d(line.quantity)
            qty_base = qty_sale * _d(mult)
            old_line_cogs = qty_base * old_uc
            new_line_cogs = qty_base * snap_cost

            old_total = _d(sale_row.total_cost)
            sign = Decimal("1") if old_total >= 0 else Decimal("-1")
            new_total = sign * (abs(_d(sale_row.quantity_delta)) * snap_cost)

            candidates.append(
                Candidate(
                    invoice_id=inv.id,
                    invoice_no=inv.invoice_no or str(inv.id),
                    line_id=line.id,
                    item_id=line.item_id,
                    item_name=line.item_name or "?",
                    unit_name=line.unit_name or "",
                    qty_sale=qty_sale,
                    qty_base=qty_base,
                    unit_price_ex=sale_price,
                    old_unit_cost=old_uc,
                    new_unit_cost=snap_cost,
                    old_line_cogs=old_line_cogs,
                    new_line_cogs=new_line_cogs,
                    ledger_id=sale_row.id,
                    ledger_qty_delta=_d(sale_row.quantity_delta),
                    ledger_total_cost_old=old_total,
                    ledger_total_cost_new=new_total,
                )
            )

    return candidates, warnings


def _sales_totals(db: Session, branch_id: UUID, company_id: UUID, start_date: date, end_date: date) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(SalesInvoice.total_exclusive), 0))
        .filter(
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.company_id == company_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            SalesInvoice.invoice_date.between(start_date, end_date),
        )
        .scalar()
    )
    return _d(total)


def main() -> None:
    p = argparse.ArgumentParser(description="Repair stale sales COGS outliers.")
    p.add_argument("--branch-id", required=True)
    p.add_argument("--company-id", required=True)
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--database-url", default=os.getenv("MARGIN_ANALYSIS_DATABASE_URL", ""))
    p.add_argument("--apply", action="store_true", help="Persist changes (default: dry run).")
    args = p.parse_args()

    branch_id = UUID(str(args.branch_id).strip())
    company_id = UUID(str(args.company_id).strip())
    start_date = date.fromisoformat(str(args.start_date).strip()[:10])
    end_date = date.fromisoformat(str(args.end_date).strip()[:10])

    url = (args.database_url or "").strip() or settings.database_connection_string
    if not url:
        print("ERROR: No database URL. Set DATABASE_URL in .env or pass --database-url.")
        sys.exit(1)
    url = normalize_postgres_url(url)

    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as db:
        candidates, warnings = _load_candidates(db, branch_id, company_id, start_date, end_date)
        total_sales = _sales_totals(db, branch_id, company_id, start_date, end_date)

        old_cogs = sum((c.ledger_total_cost_old for c in candidates), Decimal("0"))
        new_cogs = sum((c.ledger_total_cost_new for c in candidates), Decimal("0"))
        cogs_delta = new_cogs - old_cogs

        print("\n=== Sales COGS outlier repair preview ===")
        print(f"Date range: {start_date.isoformat()} -> {end_date.isoformat()}")
        print(f"Branch: {branch_id}")
        print(f"Company: {company_id}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
        print(f"Candidates: {len(candidates)}")
        print(f"Warnings/skips: {len(warnings)}")
        print(f"Current sales (exclusive) in range: {total_sales:.2f}")
        print(f"Outlier COGS old: {old_cogs:.2f}")
        print(f"Outlier COGS new: {new_cogs:.2f}")
        print(f"COGS delta (new-old): {cogs_delta:.2f}")
        if total_sales > 0:
            old_margin_impact = (total_sales - old_cogs) / total_sales * Decimal("100")
            new_margin_impact = (total_sales - new_cogs) / total_sales * Decimal("100")
            print(f"Margin on impacted lines (old): {old_margin_impact:.2f}%")
            print(f"Margin on impacted lines (new): {new_margin_impact:.2f}%")

        if warnings:
            print("\n--- Warnings / skipped lines ---")
            for w in warnings[:100]:
                print(f"  {w}")
            if len(warnings) > 100:
                print(f"  ... and {len(warnings) - 100} more")

        if candidates:
            print("\n--- Candidate details ---")
            for c in candidates:
                print(
                    f"  {c.invoice_no} | {c.item_name[:50]} | qty={c.qty_sale} {c.unit_name} "
                    f"| price={c.unit_price_ex:.2f} | unit_cost {c.old_unit_cost:.2f}->{c.new_unit_cost:.2f} "
                    f"| cogs {c.ledger_total_cost_old:.2f}->{c.ledger_total_cost_new:.2f}"
                )

        if not args.apply:
            print("\nDry run complete. Re-run with --apply to persist changes.")
            return

        if not candidates:
            print("\nNo candidates to apply.")
            return

        try:
            for c in candidates:
                line = db.query(SalesInvoiceItem).filter(SalesInvoiceItem.id == c.line_id).with_for_update().first()
                led = db.query(InventoryLedger).filter(InventoryLedger.id == c.ledger_id).with_for_update().first()
                if not line or not led:
                    raise RuntimeError(f"Missing row during apply for invoice {c.invoice_no}, item {c.item_id}.")
                line.unit_cost_used = c.new_unit_cost
                led.unit_cost = c.new_unit_cost
                led.total_cost = c.ledger_total_cost_new
            db.commit()
            print(f"\nApplied {len(candidates)} repair(s) successfully.")
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    main()

