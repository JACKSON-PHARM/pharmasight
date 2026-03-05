"""
Item branch snapshot service — write-time computed item_branch_snapshot.

Unified snapshot: inventory state, pricing inputs, effective_selling_price,
activity metadata (last order/sale/order_book dates). Reads from ledger,
legacy purchase/search snapshots (until deprecated), and pricing tables.
"""
import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, and_, text
from sqlalchemy.orm import Session

from app.models import (
    Item,
    ItemBranchSnapshot,
    ItemBranchPurchaseSnapshot,
    ItemBranchSearchSnapshot,
    InventoryBalance,
    InventoryLedger,
    ItemPricing,
    CompanyPricingDefault,
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
    """
    Last purchase-like unit cost from inventory ledger (single source of truth).
    Considers the most recent row where:
    - transaction_type is PURCHASE or ADJUSTMENT
    - quantity_delta > 0 (stock added)
    - unit_cost > 0 (ignore zero-cost adjustments)
    Same transaction sees just-written rows.
    """
    row = (
        db.query(InventoryLedger.unit_cost)
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.transaction_type.in_(["PURCHASE", "ADJUSTMENT"]),
            InventoryLedger.quantity_delta > 0,
            InventoryLedger.unit_cost > 0,
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

    # last_purchase_price from ledger (latest costed movement)
    last_purchase_price = _get_last_purchase_price_from_ledger(db, company_id, branch_id, item_id)

    # average_cost: prefer last_purchase_price; else get_best_available_cost (which can fall back
    # to items.default_cost_per_base when there is no ledger history for this branch).
    cost = CanonicalPricingService.get_best_available_cost(db, item_id, branch_id, company_id)
    average_cost = float(last_purchase_price) if last_purchase_price is not None else (float(cost) if cost is not None else None)
    # When there is no ledger movement yet for this branch but we have a default cost from Excel
    # (items.default_cost_per_base via CanonicalPricingService), promote that into last_purchase_price
    # so branch snapshots and item search always have a cost for pricing/UI.
    if last_purchase_price is None and average_cost is not None and average_cost > 0:
        last_purchase_price = average_cost

    # Margin and pricing inputs (for effective_selling_price and audit)
    margin_percent = PricingService.get_markup_percent(db, item_id, company_id)
    margin_val = float(margin_percent) if margin_percent is not None else None
    floor_price = float(item.floor_price_retail) if getattr(item, "floor_price_retail", None) is not None else None
    min_margin = PricingService.get_min_margin_percent(db, item_id, company_id)
    minimum_margin = float(min_margin) if min_margin is not None else None

    # Pricing input copies
    item_pricing = db.query(ItemPricing).filter(ItemPricing.item_id == item_id).first()
    default_item_margin = float(item_pricing.markup_percent) if item_pricing and item_pricing.markup_percent is not None else None
    company_defaults = db.query(CompanyPricingDefault).filter(CompanyPricingDefault.company_id == company_id).first()
    company_margin = float(company_defaults.default_markup_percent) if company_defaults and company_defaults.default_markup_percent is not None else None
    branch_margin = None  # No branch_margins table; leave NULL

    # Promotion from item (promo_price_retail, promo_start_date, promo_end_date)
    now_date = datetime.now(timezone.utc).date()
    promo_price = float(item.promo_price_retail) if getattr(item, "promo_price_retail", None) is not None else None
    promo_start = item.promo_start_date if getattr(item, "promo_start_date", None) else None
    promo_end = item.promo_end_date if getattr(item, "promo_end_date", None) else None
    promotion_active = bool(
        promo_price is not None and promo_price > 0
        and promo_start is not None and promo_end is not None
        and promo_start <= now_date <= promo_end
    )
    if not promotion_active:
        promo_price = None
        promo_start = None
        promo_end = None

    # Computed selling price (margin-based); enforce floor
    if average_cost is not None and margin_percent is not None:
        selling_price = float(Decimal(str(average_cost)) * (Decimal("1") + Decimal(str(margin_percent)) / Decimal("100")))
    else:
        selling_price = None
    if floor_price is not None and (selling_price is None or selling_price < floor_price):
        selling_price = floor_price

    # Effective selling price and source: promotion > floor > margin
    if promotion_active and promo_price is not None:
        effective_selling_price = promo_price
        price_source = "promotion"
    elif floor_price is not None and selling_price is not None and selling_price == floor_price:
        effective_selling_price = floor_price
        price_source = "floor"
    elif selling_price is not None:
        effective_selling_price = selling_price
        price_source = "company_margin" if company_margin is not None else "default_margin"
    else:
        effective_selling_price = selling_price
        price_source = None

    # Legacy snapshots: last_purchase_date, last_supplier_id; activity dates
    purchase_snap = (
        db.query(ItemBranchPurchaseSnapshot.last_purchase_date, ItemBranchPurchaseSnapshot.last_supplier_id)
        .filter(
            ItemBranchPurchaseSnapshot.item_id == item_id,
            ItemBranchPurchaseSnapshot.branch_id == branch_id,
            ItemBranchPurchaseSnapshot.company_id == company_id,
        )
        .first()
    )
    last_purchase_date = purchase_snap.last_purchase_date if purchase_snap else None
    last_supplier_id = str(purchase_snap.last_supplier_id) if purchase_snap and purchase_snap.last_supplier_id else None

    search_snap = (
        db.query(
            ItemBranchSearchSnapshot.last_order_date,
            ItemBranchSearchSnapshot.last_sale_date,
            ItemBranchSearchSnapshot.last_order_book_date,
            ItemBranchSearchSnapshot.last_quotation_date,
        )
        .filter(
            ItemBranchSearchSnapshot.item_id == item_id,
            ItemBranchSearchSnapshot.branch_id == branch_id,
            ItemBranchSearchSnapshot.company_id == company_id,
        )
        .first()
    )
    last_order_date = search_snap.last_order_date if search_snap else None
    last_sale_date = search_snap.last_sale_date if search_snap else None
    last_order_book_date = search_snap.last_order_book_date if search_snap else None
    last_quotation_date = search_snap.last_quotation_date if search_snap else None

    next_expiry = _get_next_expiry_date(db, item_id, branch_id, company_id)
    search_text = _search_text_for_item(item)

    base_unit = (item.base_unit or "piece").strip() or "piece"
    sku = (item.sku or "").strip() or None
    vat_rate = float(item.vat_rate) if item.vat_rate is not None else None
    vat_category = (item.vat_category or "ZERO_RATED").strip() or None
    pack_size = max(1, int(item.pack_size or 1))
    name = (item.name or "").strip() or ""
    retail_unit = (getattr(item, "retail_unit", None) or "piece").strip() or "piece"
    supplier_unit = (getattr(item, "supplier_unit", None) or "piece").strip() or "piece"
    wholesale_unit = (getattr(item, "wholesale_unit", None) or "piece").strip() or "piece"
    wholesale_units_per_supplier = float(getattr(item, "wholesale_units_per_supplier", None) or 1)

    db.execute(
        text("""
            INSERT INTO item_branch_snapshot (
                company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category,
                current_stock, average_cost, last_purchase_price, selling_price, margin_percent,
                next_expiry_date, search_text,
                last_purchase_date, last_supplier_id,
                last_order_date, last_sale_date, last_order_book_date, last_quotation_date,
                default_item_margin, branch_margin, company_margin, floor_price, minimum_margin,
                promotion_price, promotion_start, promotion_end, promotion_active,
                effective_selling_price, price_source,
                retail_unit, supplier_unit, wholesale_unit, wholesale_units_per_supplier,
                updated_at
            )
            VALUES (
                :company_id, :branch_id, :item_id, :name, :pack_size, :base_unit, :sku, :vat_rate, :vat_category,
                :current_stock, :average_cost, :last_purchase_price, :selling_price, :margin_percent,
                :next_expiry_date, :search_text,
                :last_purchase_date, :last_supplier_id,
                :last_order_date, :last_sale_date, :last_order_book_date, :last_quotation_date,
                :default_item_margin, :branch_margin, :company_margin, :floor_price, :minimum_margin,
                :promotion_price, :promotion_start, :promotion_end, :promotion_active,
                :effective_selling_price, :price_source,
                :retail_unit, :supplier_unit, :wholesale_unit, :wholesale_units_per_supplier,
                NOW()
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
                last_purchase_date = EXCLUDED.last_purchase_date,
                last_supplier_id = EXCLUDED.last_supplier_id,
                last_order_date = EXCLUDED.last_order_date,
                last_sale_date = EXCLUDED.last_sale_date,
                last_order_book_date = EXCLUDED.last_order_book_date,
                last_quotation_date = EXCLUDED.last_quotation_date,
                default_item_margin = EXCLUDED.default_item_margin,
                branch_margin = EXCLUDED.branch_margin,
                company_margin = EXCLUDED.company_margin,
                floor_price = EXCLUDED.floor_price,
                minimum_margin = EXCLUDED.minimum_margin,
                promotion_price = EXCLUDED.promotion_price,
                promotion_start = EXCLUDED.promotion_start,
                promotion_end = EXCLUDED.promotion_end,
                promotion_active = EXCLUDED.promotion_active,
                effective_selling_price = EXCLUDED.effective_selling_price,
                price_source = EXCLUDED.price_source,
                retail_unit = EXCLUDED.retail_unit,
                supplier_unit = EXCLUDED.supplier_unit,
                wholesale_unit = EXCLUDED.wholesale_unit,
                wholesale_units_per_supplier = EXCLUDED.wholesale_units_per_supplier,
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
            "last_purchase_date": last_purchase_date,
            "last_supplier_id": last_supplier_id,
            "last_order_date": last_order_date.isoformat() if last_order_date else None,
            "last_sale_date": last_sale_date.isoformat() if last_sale_date else None,
            "last_order_book_date": last_order_book_date,
            "last_quotation_date": last_quotation_date.isoformat() if last_quotation_date else None,
            "default_item_margin": default_item_margin,
            "branch_margin": branch_margin,
            "company_margin": company_margin,
            "floor_price": floor_price,
            "minimum_margin": minimum_margin,
            "promotion_price": promo_price,
            "promotion_start": promo_start,
            "promotion_end": promo_end,
            "promotion_active": promotion_active,
            "effective_selling_price": effective_selling_price,
            "price_source": price_source,
            "retail_unit": retail_unit,
            "supplier_unit": supplier_unit,
            "wholesale_unit": wholesale_unit,
            "wholesale_units_per_supplier": wholesale_units_per_supplier,
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
