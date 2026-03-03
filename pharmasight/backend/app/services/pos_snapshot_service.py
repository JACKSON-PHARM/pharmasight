"""
Item branch snapshot service — write-time computed item_branch_snapshot.

Refreshes one row per (item_id, branch_id) with: current_stock, average_cost,
last_purchase_price, selling_price, margin_percent, next_expiry_date, search_text.
Called from GRN, sale, adjustment, pricing update, item edit (dual-write).
Used for single-SELECT item search across the app (sales, quotations, inventory, etc.).
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, and_, text
from sqlalchemy.orm import Session

from app.models import (
    Item,
    ItemBranchSnapshot,
    InventoryBalance,
    InventoryLedger,
)
from app.services.canonical_pricing import CanonicalPricingService
from app.services.pricing_service import PricingService


# Common drug name -> search abbreviations so short queries (e.g. ABZ) match (e.g. albendazole)
_SEARCH_ABBREVIATIONS = (
    ("albendazole", "abz"),
    ("paracetamol", "pcm panadol"),
    ("amoxicillin", "amox"),
    ("metronidazole", "flagyl"),
    ("ciprofloxacin", "cipro"),
    ("ibuprofen", "ibu"),
    ("omeprazole", "omep"),
    ("co-trimoxazole", "septrin cotrim"),
    ("artemether", "art"),
    ("lumefantrine", "lum"),
)


def _search_text_for_item(item: Item) -> str:
    """Lower(name + sku + barcode + description) plus common drug abbreviations so e.g. 'ABZ' matches albendazole."""
    name = (item.name or "").strip().lower()
    sku = (item.sku or "").strip().lower()
    barcode = (item.barcode or "").strip().lower()
    description = (getattr(item, "description", None) or "").strip().lower()
    parts = [name, sku, barcode, description]
    # Append abbreviations when item name or description contains the full drug name (e.g. albendazole -> abz)
    name_and_desc = f" {name} {description} "
    for full_name, abbrs in _SEARCH_ABBREVIATIONS:
        if full_name in name_and_desc:
            parts.append(abbrs)
    return " ".join(p for p in parts if p)


def _get_next_expiry_date(
    db: Session, item_id: UUID, branch_id: UUID, company_id: UUID
) -> date | None:
    """Minimum expiry_date from ledger batches that have remaining quantity > 0."""
    # Subquery: (batch_number, expiry_date) with positive remaining qty
    subq = (
        db.query(
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
            func.sum(InventoryLedger.quantity_delta).label("remaining"),
        )
        .filter(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.company_id == company_id,
            )
        )
        .group_by(InventoryLedger.batch_number, InventoryLedger.expiry_date)
        .having(func.sum(InventoryLedger.quantity_delta) > 0)
        .subquery()
    )
    row = (
        db.query(func.min(subq.c.expiry_date))
        .filter(subq.c.expiry_date.isnot(None))
        .scalar()
    )
    if row is None:
        return None
    return row if isinstance(row, date) else row.date() if hasattr(row, "date") else None


def _get_last_purchase_price_from_ledger(
    db: Session, company_id: UUID, branch_id: UUID, item_id: UUID
) -> float | None:
    """Last purchase unit cost from inventory ledger (single source of truth). Same transaction sees just-written rows."""
    row = (
        db.query(InventoryLedger.unit_cost)
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.transaction_type == "PURCHASE",
        )
        .order_by(InventoryLedger.created_at.desc())
        .limit(1)
        .first()
    )
    return float(row.unit_cost) if row and row.unit_cost is not None else None


def refresh_pos_snapshot_for_item(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    item_id: UUID,
) -> None:
    """
    Compute and upsert one row in item_branch_snapshot.
    Uses: inventory_balances (current_stock), ledger (average_cost, next_expiry, last_purchase_price),
    pricing (selling_price, margin_percent), item (name, pack_size, base_unit, sku, vat_rate, vat_category, search_text).
    Last purchase price comes from the ledger (latest PURCHASE for item/branch)—single source of truth; same
    transaction sees the row we just wrote, so no read-from-another-table or read-after-write issues.
    Call in same transaction as the write that changed data.
    """
    item = db.query(Item).filter(
        Item.id == item_id,
        Item.company_id == company_id,
    ).first()
    if not item:
        raise ValueError(
            f"Item {item_id} not found for company {company_id}; cannot refresh item_branch_snapshot"
        )

    # current_stock from inventory_balances
    bal = (
        db.query(InventoryBalance.current_stock)
        .filter(
            InventoryBalance.item_id == item_id,
            InventoryBalance.branch_id == branch_id,
            InventoryBalance.company_id == company_id,
        )
        .first()
    )
    current_stock = float(bal.current_stock or 0) if bal else 0

    # last_purchase_price from ledger (latest PURCHASE) — single source of truth, same transaction sees new rows
    last_purchase_price = _get_last_purchase_price_from_ledger(db, company_id, branch_id, item_id)

    # average_cost: prefer last_purchase_price so search shows the cost just keyed (adjustment or purchase);
    # else get_best_available_cost (weighted avg / opening / default). This ensures manual adjustment cost appears in search.
    cost = CanonicalPricingService.get_best_available_cost(db, item_id, branch_id, company_id)
    average_cost = float(last_purchase_price) if last_purchase_price is not None else (float(cost) if cost is not None else None)

    # selling_price and margin_percent from pricing logic; enforce floor_price_retail minimum
    margin_percent = PricingService.get_markup_percent(db, item_id, company_id)
    if average_cost is not None and margin_percent is not None:
        selling_price = float(Decimal(str(average_cost)) * (Decimal("1") + Decimal(str(margin_percent)) / Decimal("100")))
    else:
        selling_price = None
    floor_price = float(item.floor_price_retail) if getattr(item, "floor_price_retail", None) is not None else None
    if floor_price is not None and (selling_price is None or selling_price < floor_price):
        selling_price = floor_price
    margin_val = float(margin_percent) if margin_percent is not None else None

    next_expiry = _get_next_expiry_date(db, item_id, branch_id, company_id)
    search_text = _search_text_for_item(item)

    base_unit = (item.base_unit or "piece").strip() or "piece"
    sku = (item.sku or "").strip() or None
    vat_rate = float(item.vat_rate) if item.vat_rate is not None else None
    vat_category = (item.vat_category or "ZERO_RATED").strip() or None
    pack_size = max(1, int(item.pack_size or 1))
    name = (item.name or "").strip() or ""

    db.execute(
        text("""
            INSERT INTO item_branch_snapshot (
                company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category,
                current_stock, average_cost, last_purchase_price, selling_price, margin_percent,
                next_expiry_date, search_text, updated_at
            )
            VALUES (
                :company_id, :branch_id, :item_id, :name, :pack_size, :base_unit, :sku, :vat_rate, :vat_category,
                :current_stock, :average_cost, :last_purchase_price, :selling_price, :margin_percent,
                :next_expiry_date, :search_text, NOW()
            )
            ON CONFLICT (item_id, branch_id) DO UPDATE SET
                name = EXCLUDED.name,
                pack_size = EXCLUDED.pack_size,
                base_unit = EXCLUDED.base_unit,
                sku = EXCLUDED.sku,
                vat_rate = EXCLUDED.vat_rate,
                vat_category = EXCLUDED.vat_category,
                current_stock = EXCLUDED.current_stock,
                average_cost = EXCLUDED.average_cost,
                last_purchase_price = EXCLUDED.last_purchase_price,
                selling_price = EXCLUDED.selling_price,
                margin_percent = EXCLUDED.margin_percent,
                next_expiry_date = EXCLUDED.next_expiry_date,
                search_text = EXCLUDED.search_text,
                updated_at = NOW()
        """),
        {
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "item_id": str(item_id),
            "name": name,
            "pack_size": pack_size,
            "base_unit": base_unit,
            "sku": sku,
            "vat_rate": vat_rate,
            "vat_category": vat_category,
            "current_stock": current_stock,
            "average_cost": average_cost,
            "last_purchase_price": last_purchase_price,
            "selling_price": selling_price,
            "margin_percent": margin_val,
            "next_expiry_date": next_expiry.isoformat() if next_expiry else None,
            "search_text": search_text,
        },
    )


def refresh_pos_snapshot_for_item_safe(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    item_id: UUID,
) -> None:
    """
    Call refresh_pos_snapshot_for_item; on failure log and do not raise.
    Use from write paths so missing table (migration not run) does not break GRN/sale/adjustment.
    """
    try:
        refresh_pos_snapshot_for_item(db, company_id, branch_id, item_id)
    except Exception as e:
        logger.warning("POS snapshot refresh failed for item %s branch %s: %s", item_id, branch_id, e)


def refresh_pos_snapshot_for_item_all_branches_safe(
    db: Session,
    company_id: UUID,
    item_id: UUID,
) -> None:
    """Refresh POS snapshot for an item in every branch of the company (e.g. after item edit)."""
    from app.models import Branch
    branches = db.query(Branch.id).filter(Branch.company_id == company_id, Branch.is_active == True).all()
    for (branch_id,) in branches:
        refresh_pos_snapshot_for_item_safe(db, company_id, branch_id, item_id)
