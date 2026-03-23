#!/usr/bin/env python3
"""
Margin distribution diagnostic for batched/paid sales (matches app unit conversion).

Uses the same multiplier logic as the backend: get_unit_multiplier_from_item (retail /
wholesale / supplier), not a hard-coded "packet" rule.

Usage (from repo root or backend — run with backend on PYTHONPATH):

  cd pharmasight/backend
  ..\\venv\\Scripts\\python scripts\\analyze_margin_distribution.py \\
    --branch-id BEC5D46A-7F21-45EF-945C-8C68171AA386 \\
    --company-id 9C71915E-3E59-45D5-9719-56D2322FF673

Optional:
  --date 2026-03-23     (default: today in local date)
  --database-url ...    override DATABASE_URL (e.g. tenant direct URL)

Requires: DATABASE_URL in .env (same as the API). This talks to Postgres directly;
it does not use a browser token. For tenant-specific DBs, set DATABASE_URL to that
tenant's connection string or pass --database-url.

Environment (optional):
  MARGIN_ANALYSIS_BRANCH_ID
  MARGIN_ANALYSIS_COMPANY_ID
  MARGIN_ANALYSIS_DATE
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

# Backend root on path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, selectinload

from app.config import normalize_postgres_url, settings
from app.models import InventoryLedger, Item, SalesInvoice, SalesInvoiceItem
from app.services.item_units_helper import get_unit_multiplier_from_item


def _d(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return Decimal(str(x))


def ledger_line_cogs(
    db: Session, invoice_id: UUID, item_id: UUID
) -> Decimal:
    """Sum SALE ledger total_cost for this invoice line (multi-batch actual)."""
    q = (
        db.query(func.coalesce(func.sum(InventoryLedger.total_cost), 0))
        .filter(
            InventoryLedger.reference_type == "sales_invoice",
            InventoryLedger.reference_id == invoice_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.transaction_type == "SALE",
        )
        .scalar()
    )
    return _d(q)


def analyze(
    db: Session,
    branch_id: UUID,
    company_id: UUID,
    report_date: date,
) -> None:
    sales_date_key = func.date(func.coalesce(SalesInvoice.batched_at, SalesInvoice.created_at))

    invoices = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
        .filter(
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.company_id == company_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            sales_date_key == report_date,
        )
        .order_by(SalesInvoice.invoice_no)
        .all()
    )

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for inv in invoices:
        inv_no = inv.invoice_no or str(inv.id)[:8]
        for line in inv.items or []:
            item = line.item
            if not item:
                warnings.append(f"Missing item join for line item_id={line.item_id} inv={inv_no}")
                continue

            mult = get_unit_multiplier_from_item(item, (line.unit_name or "").strip())
            if mult is None or mult <= 0:
                warnings.append(
                    f"No multiplier for unit_name={line.unit_name!r} item={line.item_name!r} inv={inv_no}"
                )
                mult = Decimal("0")

            qty = _d(line.quantity)
            qty_base = qty * mult
            uc = _d(line.unit_cost_used)
            line_cogs_from_snapshot = qty_base * uc
            revenue = _d(line.line_total_exclusive)
            price_unit = _d(line.unit_price_exclusive)

            margin_pct = None
            if revenue > 0 and mult > 0:
                margin_pct = (revenue - line_cogs_from_snapshot) / revenue * Decimal("100")
            elif revenue > 0 and mult <= 0:
                margin_pct = None  # cannot interpret COGS without valid unit multiplier

            margin_unit_pct = None
            cost_per_sale_unit = uc * mult if mult > 0 else Decimal("0")
            if price_unit > 0 and mult > 0:
                margin_unit_pct = (price_unit - cost_per_sale_unit) / price_unit * Decimal("100")

            led = ledger_line_cogs(db, inv.id, line.item_id)
            cogs_diff = led - line_cogs_from_snapshot if led else Decimal("0")

            rows.append(
                {
                    "invoice_no": inv_no,
                    "item_id": str(line.item_id),
                    "item_name": line.item_name or (item.name if item else "?"),
                    "unit_name": line.unit_name or "",
                    "quantity": qty,
                    "mult_to_retail": mult,
                    "qty_base": qty_base,
                    "unit_price_exclusive": price_unit,
                    "line_total_exclusive": revenue,
                    "unit_cost_used_per_retail": uc,
                    "cost_per_sale_unit": cost_per_sale_unit,
                    "line_cogs_from_unit_cost_used": line_cogs_from_snapshot,
                    "line_cogs_from_ledger": led,
                    "cogs_diff_ledger_minus_snapshot": cogs_diff,
                    "margin_pct_on_line_revenue": margin_pct,
                    "margin_pct_on_unit_price": margin_unit_pct,
                }
            )

    print(f"\n=== Margin analysis ===")
    print(f"Date (batched/created): {report_date.isoformat()}")
    print(f"Branch: {branch_id}")
    print(f"Company: {company_id}")
    print(f"Invoices: {len(invoices)}  |  Lines: {len(rows)}")

    if warnings:
        print(f"\n--- Warnings ({len(warnings)}) ---")
        for w in warnings[:30]:
            print(f"  {w}")
        if len(warnings) > 30:
            print(f"  ... and {len(warnings) - 30} more")

    if not rows:
        print("\nNo lines found. Check date, branch, company, and DATABASE_URL (tenant DB).")
        return

    # Portfolio (from snapshot COGS)
    total_rev = sum(_d(r["line_total_exclusive"]) for r in rows)
    total_cogs_snap = sum(_d(r["line_cogs_from_unit_cost_used"]) for r in rows)
    total_cogs_led = sum(_d(r["line_cogs_from_ledger"]) for r in rows)
    print("\n--- Portfolio (all lines) ---")
    print(f"Line revenue (sum line_total_exclusive):     {total_rev:.2f}")
    print(f"COGS from unit_cost_used x qty x mult:       {total_cogs_snap:.2f}")
    print(f"COGS from ledger (SALE sum per line):        {total_cogs_led:.2f}")
    if total_rev > 0:
        print(f"Margin % (revenue vs snapshot COGS):       {(total_rev - total_cogs_snap) / total_rev * 100:.2f}%")
        print(f"Margin % (revenue vs ledger COGS):          {(total_rev - total_cogs_led) / total_rev * 100:.2f}%")

    # Buckets on line revenue margin (snapshot)
    buckets = {"<15%": [], "15-25%": [], ">25%": []}
    for r in rows:
        m = r["margin_pct_on_line_revenue"]
        if m is None:
            continue
        mf = float(m)
        if mf < 15:
            buckets["<15%"].append(r)
        elif mf <= 25:
            buckets["15-25%"].append(r)
        else:
            buckets[">25%"].append(r)

    print("\n--- Distribution (margin on line revenue, vs snapshot COGS) ---")
    for name, lst in buckets.items():
        s = sum(float(_d(x["line_total_exclusive"])) for x in lst)
        print(f"  {name}: {len(lst)} lines | line sales: {s:.2f}")

    # Top 10 worst lines by margin
    sorted_rows = sorted(
        rows,
        key=lambda x: float(x["margin_pct_on_line_revenue"] or -9999),
    )
    print("\n--- Top 10 lowest margin lines (snapshot COGS) ---")
    for r in sorted_rows[:10]:
        print(
            f"  {r['invoice_no']} | {r['item_name'][:40]!s} | "
            f"margin {float(r['margin_pct_on_line_revenue'] or 0):.1f}% | "
            f"sales {float(r['line_total_exclusive']):.2f} | "
            f"cogs_snap {float(r['line_cogs_from_unit_cost_used']):.2f} | "
            f"cogs_led {float(r['line_cogs_from_ledger']):.2f}"
        )

    # Aggregate by item name
    by_item: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"sales": Decimal("0"), "cogs_snap": Decimal("0"), "cogs_led": Decimal("0")}
    )
    for r in rows:
        n = r["item_name"] or "?"
        by_item[n]["sales"] += _d(r["line_total_exclusive"])
        by_item[n]["cogs_snap"] += _d(r["line_cogs_from_unit_cost_used"])
        by_item[n]["cogs_led"] += _d(r["line_cogs_from_ledger"])

    item_summary = []
    for name, v in by_item.items():
        sales = v["sales"]
        cogs = v["cogs_snap"]
        m = ((sales - cogs) / sales * Decimal("100")) if sales > 0 else Decimal("0")
        item_summary.append((name, sales, cogs, m))

    item_summary.sort(key=lambda x: float(x[3]))
    print("\n--- Top 10 lowest-margin items (aggregated by item name, snapshot COGS) ---")
    for name, sales, cogs, m in item_summary[:10]:
        print(f"  {name[:50]!s} | margin {float(m):.1f}% | sales {float(sales):.2f} | cogs {float(cogs):.2f}")

    print("\nDone.\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Analyze margin distribution for batched sales.")
    p.add_argument("--branch-id", default=os.getenv("MARGIN_ANALYSIS_BRANCH_ID", ""))
    p.add_argument("--company-id", default=os.getenv("MARGIN_ANALYSIS_COMPANY_ID", ""))
    p.add_argument("--date", default=os.getenv("MARGIN_ANALYSIS_DATE", ""), help="YYYY-MM-DD (default: today)")
    p.add_argument("--database-url", default=os.getenv("MARGIN_ANALYSIS_DATABASE_URL", ""))
    args = p.parse_args()

    if not args.branch_id or not args.company_id:
        print("ERROR: --branch-id and --company-id are required (or set MARGIN_ANALYSIS_* env vars).")
        sys.exit(1)

    branch_id = UUID(str(args.branch_id).strip())
    company_id = UUID(str(args.company_id).strip())

    if args.date:
        report_date = date.fromisoformat(str(args.date).strip()[:10])
    else:
        report_date = date.today()

    url = (args.database_url or "").strip() or settings.database_connection_string
    if not url:
        print("ERROR: No database URL. Set DATABASE_URL in .env or pass --database-url.")
        sys.exit(1)
    url = normalize_postgres_url(url)

    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as db:
        analyze(db, branch_id, company_id, report_date)


if __name__ == "__main__":
    main()
