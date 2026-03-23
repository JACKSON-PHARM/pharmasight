#!/usr/bin/env python3
"""
Backfill sales_invoice_items.unit_cost_used from posted SALE ledger (ledger is source of truth).

For each BATCHED/PAID invoice line:
  unit_cost_used = SUM(inventory_ledger.total_cost) / qty_base
where qty_base = quantity (sale unit) × multiplier_to_retail, matching batch logic.

Does NOT insert or alter ledger rows.

Usage:
  cd pharmasight/backend
  ..\\venv\\Scripts\\python scripts\\reconcile_sales_line_unit_cost_from_ledger.py [--dry-run] [--company-id UUID]

Optional:
  --invoice-id UUID   only reconcile one invoice
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, selectinload

from app.config import normalize_postgres_url, settings
from app.models import InventoryLedger, SalesInvoice, SalesInvoiceItem
from app.services.inventory_service import InventoryService
from app.services.item_units_helper import get_unit_multiplier_from_item

SNAPSHOT_VS_LEDGER_WARN_THRESHOLD = Decimal("0.01")


def ledger_line_total(db: Session, invoice_id: UUID, item_id: UUID) -> Decimal:
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
    return Decimal(str(q or 0))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--company-id", default="", help="Limit to this company UUID")
    p.add_argument("--invoice-id", default="", help="Only this invoice UUID")
    args = p.parse_args()

    print("reconcile_sales_line_unit_cost_from_ledger: starting...", flush=True)

    url = normalize_postgres_url(settings.database_connection_string)
    if not url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print("Connecting to database...", flush=True)
    engine = create_engine(url, pool_pre_ping=True)
    updated = 0
    warned = 0
    skipped = 0

    with Session(engine) as db:
        q = (
            db.query(SalesInvoice)
            .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
            .filter(SalesInvoice.status.in_(["BATCHED", "PAID"]))
        )
        if args.company_id:
            q = q.filter(SalesInvoice.company_id == UUID(args.company_id.strip()))
        if args.invoice_id:
            q = q.filter(SalesInvoice.id == UUID(args.invoice_id.strip()))
        print("Loading invoices (this can take a while)...", flush=True)
        invoices = q.all()
        print(f"Loaded {len(invoices)} invoices. Processing lines...", flush=True)

        for inv in invoices:
            for line in inv.items or []:
                item = line.item
                if not item:
                    skipped += 1
                    continue
                try:
                    qty_base = Decimal(
                        str(
                            InventoryService.convert_to_base_units(
                                db, line.item_id, float(line.quantity), line.unit_name or ""
                            )
                        )
                    )
                except Exception:
                    skipped += 1
                    continue
                if qty_base <= 0:
                    skipped += 1
                    continue

                led = ledger_line_total(db, inv.id, line.item_id)
                if led <= 0:
                    skipped += 1
                    continue

                new_uc = led / qty_base
                old_uc = line.unit_cost_used
                old_snap = (old_uc or Decimal("0")) * qty_base if old_uc is not None else Decimal("0")
                line_rev = line.line_total_exclusive or Decimal("0")
                diff = abs(old_snap - led)
                if line_rev > 0 and diff > (SNAPSHOT_VS_LEDGER_WARN_THRESHOLD * line_rev):
                    warned += 1
                    print(
                        f"FLAG invoice={inv.invoice_no} item={line.item_name} "
                        f"snap_cogs={old_snap} ledger={led} line_excl={line_rev}"
                    )

                if old_uc is not None and abs(Decimal(str(old_uc)) - new_uc) < Decimal("0.0001"):
                    continue

                if not args.dry_run:
                    line.unit_cost_used = new_uc
                updated += 1

        if not args.dry_run:
            db.commit()

    print(f"\nDone. lines_updated={updated} flags={warned} skipped={skipped} dry_run={args.dry_run}\n")


if __name__ == "__main__":
    main()
