"""
Pricing Service - Cost-based pricing with batch awareness
"""
import time
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import Optional, Dict, List, Any
from uuid import UUID
from decimal import Decimal, ROUND_HALF_UP
from app.models import (
    Item, ItemPricing, CompanyPricingDefault, CompanyMarginTier,
    InventoryLedger, ItemBranchPurchaseSnapshot
)
from app.services.inventory_service import InventoryService
from app.services.item_units_helper import get_unit_multiplier_from_item

# Cache for company default markup + margin tiers (per company_id); TTL 60s to cut search markup latency
_MARKUP_CACHE_TTL_S = 60
_markup_cache: Dict[UUID, tuple] = {}  # company_id -> (default_markup, tier_defaults, timestamp)


# Map product_category to default pricing_tier when item.pricing_tier is not set
PRODUCT_CATEGORY_TO_TIER = {
    "PHARMACEUTICAL": "STANDARD",
    "COSMETICS": "BEAUTY_COSMETICS",
    "EQUIPMENT": "EQUIPMENT",
    "SERVICE": "SERVICE",
}


class PricingService:
    """Service for calculating recommended selling prices (cost + category-based margin)."""

    @staticmethod
    def _resolve_pricing_tier(item: Item) -> str:
        """Resolve effective pricing tier: item.pricing_tier else from item.product_category else STANDARD."""
        if item.pricing_tier and str(item.pricing_tier).strip():
            return str(item.pricing_tier).strip().upper()
        if item.product_category and str(item.product_category).strip():
            return PRODUCT_CATEGORY_TO_TIER.get(
                str(item.product_category).strip().upper(), "STANDARD"
            )
        return "STANDARD"

    @staticmethod
    def get_item_cost(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        use_fefo: bool = True,
        batch_id: Optional[UUID] = None,
    ) -> Optional[Decimal]:
        """
        Get unit cost for item (FEFO batch or last purchase).
        Model B support: when batch_id is provided, returns that ledger entry's unit_cost (per base unit).
        """
        # Model B: optional batch-scoped cost resolution
        if batch_id is not None:
            ledger_row = db.query(InventoryLedger).filter(InventoryLedger.id == batch_id).first()
            if not ledger_row:
                raise ValueError(f"Batch not found: {batch_id}")
            if str(ledger_row.branch_id) != str(branch_id):
                raise ValueError("Batch does not belong to branch")
            if str(ledger_row.item_id) != str(item_id):
                raise ValueError("Batch does not belong to item")
            return Decimal(str(ledger_row.unit_cost))

        # Existing behaviour when batch_id is None: FEFO-first, then fallbacks
        # Try FEFO batch cost first
        if use_fefo:
            batches = InventoryService.get_stock_by_batch(db, item_id, branch_id)
            if batches and len(batches) > 0:
                # First batch (FEFO) cost
                return Decimal(str(batches[0]["unit_cost"]))
        
        # Try last purchase cost from ledger
        last_purchase = db.query(InventoryLedger).filter(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.transaction_type == "PURCHASE",
                InventoryLedger.quantity_delta > 0
            )
        ).order_by(InventoryLedger.created_at.desc()).first()
        
        if last_purchase:
            return Decimal(str(last_purchase.unit_cost))
        
        # No fallback to items table — cost from ledger only (CanonicalPricingService)
        from app.services.canonical_pricing import CanonicalPricingService
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return None
        return CanonicalPricingService.get_best_available_cost(db, item_id, branch_id, item.company_id)

    @staticmethod
    def get_item_cost_from_snapshot(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        company_id: UUID,
    ) -> Optional[Decimal]:
        """
        Fast cost lookup from item_branch_purchase_snapshot (updated in same transaction as
        inventory ledger). Use for add-item responses where FEFO is not required and snapshot
        is trusted. Returns last_purchase_price per base unit, or None if not in snapshot.
        """
        row = (
            db.query(ItemBranchPurchaseSnapshot.last_purchase_price)
            .filter(
                ItemBranchPurchaseSnapshot.item_id == item_id,
                ItemBranchPurchaseSnapshot.branch_id == branch_id,
                ItemBranchPurchaseSnapshot.company_id == company_id,
                ItemBranchPurchaseSnapshot.last_purchase_price.isnot(None),
            )
            .first()
        )
        if row and row[0] is not None:
            return Decimal(str(row[0]))
        return None

    @staticmethod
    def get_markup_percent(
        db: Session,
        item_id: UUID,
        company_id: UUID
    ) -> Decimal:
        """
        Get markup (margin) percentage for item.
        Priority: 1) Item-specific markup (item_pricing), 2) Company margin tier for item's pricing_tier, 3) Company default.
        """
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return Decimal("30.00")

        item_pricing = db.query(ItemPricing).filter(ItemPricing.item_id == item_id).first()
        if item_pricing and item_pricing.markup_percent is not None:
            return Decimal(str(item_pricing.markup_percent))

        tier = PricingService._resolve_pricing_tier(item)
        margin_tier = (
            db.query(CompanyMarginTier)
            .filter(
                CompanyMarginTier.company_id == company_id,
                CompanyMarginTier.tier_name == tier,
            )
            .first()
        )
        if margin_tier:
            return Decimal(str(margin_tier.default_margin_percent))

        company_defaults = db.query(CompanyPricingDefault).filter(
            CompanyPricingDefault.company_id == company_id
        ).first()
        if company_defaults:
            return Decimal(str(company_defaults.default_markup_percent))
        return Decimal("30.00")

    @staticmethod
    def get_min_margin_percent(
        db: Session,
        item_id: UUID,
        company_id: UUID
    ) -> Decimal:
        """
        Get minimum allowed margin percentage for item (admin-set floor; user cannot sell below unless allowed).
        Priority: 1) Item-specific min (item_pricing), 2) Company margin tier for item's pricing_tier, 3) Company default.
        """
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return Decimal("0")

        item_pricing = db.query(ItemPricing).filter(ItemPricing.item_id == item_id).first()
        if item_pricing and item_pricing.min_margin_percent is not None:
            return Decimal(str(item_pricing.min_margin_percent))

        tier = PricingService._resolve_pricing_tier(item)
        margin_tier = (
            db.query(CompanyMarginTier)
            .filter(
                CompanyMarginTier.company_id == company_id,
                CompanyMarginTier.tier_name == tier,
            )
            .first()
        )
        if margin_tier:
            return Decimal(str(margin_tier.min_margin_percent))

        company_defaults = db.query(CompanyPricingDefault).filter(
            CompanyPricingDefault.company_id == company_id
        ).first()
        if company_defaults and company_defaults.min_margin_percent is not None:
            return Decimal(str(company_defaults.min_margin_percent))
        return Decimal("0")

    @staticmethod
    def get_markup_percent_batch(
        db: Session,
        item_ids: List[UUID],
        company_id: UUID,
        item_map: Optional[Dict[UUID, Any]] = None,
    ) -> Dict[UUID, Decimal]:
        """Batch resolve markup percent for many items (for search sale_price).
        When item_map is provided (e.g. from search's items_full_map), Item query is skipped to reduce latency.
        """
        if not item_ids:
            return {}
        now = time.time()
        cache_entry = _markup_cache.get(company_id)
        if cache_entry and (now - cache_entry[2]) < _MARKUP_CACHE_TTL_S:
            default_markup, tier_defaults = cache_entry[0], cache_entry[1]
        else:
            cache_entry = None
        if cache_entry is None:
            default_markup = Decimal("30.00")
            company_defaults = db.query(CompanyPricingDefault).filter(
                CompanyPricingDefault.company_id == company_id
            ).first()
            if company_defaults:
                default_markup = Decimal(str(company_defaults.default_markup_percent))
            tier_defaults = {
                row.tier_name: Decimal(str(row.default_margin_percent))
                for row in db.query(CompanyMarginTier).filter(
                    CompanyMarginTier.company_id == company_id
                ).all()
            }
            _markup_cache[company_id] = (default_markup, tier_defaults, now)

        if item_map is None:
            items = db.query(Item).filter(Item.id.in_(item_ids)).all()
            item_map = {i.id: i for i in items}

        pricing_list = db.query(ItemPricing).filter(ItemPricing.item_id.in_(item_ids)).all()
        pricing_map = {p.item_id: p for p in pricing_list}
        result = {}
        for iid in item_ids:
            item = item_map.get(iid)
            if not item:
                result[iid] = default_markup
                continue
            ip = pricing_map.get(iid)
            if ip and ip.markup_percent is not None:
                result[iid] = Decimal(str(ip.markup_percent))
                continue
            tier = PricingService._resolve_pricing_tier(item)
            result[iid] = tier_defaults.get(tier, default_markup)
        return result

    @staticmethod
    def get_rounding_rule(
        db: Session,
        item_id: UUID,
        company_id: UUID
    ) -> str:
        """
        Get rounding rule for item
        
        Returns:
            str: Rounding rule (nearest_1, nearest_5, nearest_10)
        """
        # Check item-specific
        item_pricing = db.query(ItemPricing).filter(
            ItemPricing.item_id == item_id
        ).first()
        
        if item_pricing and item_pricing.rounding_rule:
            return item_pricing.rounding_rule
        
        # Fallback to company default
        company_defaults = db.query(CompanyPricingDefault).filter(
            CompanyPricingDefault.company_id == company_id
        ).first()
        
        if company_defaults:
            return company_defaults.rounding_rule or "nearest_1"
        
        return "nearest_1"

    @staticmethod
    def apply_rounding(
        price: Decimal,
        rounding_rule: str
    ) -> Decimal:
        """
        Apply rounding rule to price
        
        Args:
            price: Price to round
            rounding_rule: nearest_1, nearest_5, or nearest_10
        
        Returns:
            Decimal: Rounded price
        """
        if rounding_rule == "nearest_5":
            return (price / Decimal("5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("5")
        elif rounding_rule == "nearest_10":
            return (price / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10")
        else:  # nearest_1
            return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def calculate_recommended_price(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        company_id: UUID,
        unit_name: str,
        tier: str = "retail",
        batch_id: Optional[UUID] = None,
    ) -> Optional[Dict]:
        """
        Calculate recommended selling price for item.
        Model B support: when batch_id is provided, unit_cost_used is that batch's cost (per base unit).
        """
        # First, try to get 3-tier pricing
        tier_pricing = PricingService.get_price_for_tier(db, item_id, tier, unit_name)
        
        if tier_pricing:
            # Use 3-tier pricing if available
            if "converted_price" in tier_pricing:
                # Price was converted to requested unit
                recommended_unit_price = Decimal(str(tier_pricing["converted_price"]))
                pricing_unit = tier_pricing["converted_unit"]
            else:
                # Price is in original unit, need to convert (items table is source of truth)
                item = db.query(Item).filter(Item.id == item_id).first()
                if not item:
                    raise ValueError(f"Item {item_id} not found")
                target_mult = get_unit_multiplier_from_item(item, unit_name)
                if target_mult is None:
                    raise ValueError(f"Unit '{unit_name}' not found for item {item_id}")
                source_mult = get_unit_multiplier_from_item(item, tier_pricing.get("unit"))
                if source_mult is not None:
                    recommended_unit_price = Decimal(str(tier_pricing["price"])) * (source_mult / target_mult)
                else:
                    recommended_unit_price = Decimal(str(tier_pricing["price"]))
                pricing_unit = unit_name
            
            # Get cost for margin calculation (Model B: optional batch-scoped cost)
            unit_cost = PricingService.get_item_cost(db, item_id, branch_id, use_fefo=True, batch_id=batch_id)
            if not unit_cost:
                unit_cost = Decimal("0")
            
            # Calculate base unit price from recommended price (items table)
            item = db.query(Item).filter(Item.id == item_id).first()
            multiplier = get_unit_multiplier_from_item(item, unit_name) if item else None
            if multiplier and multiplier > 0:
                base_unit_price = recommended_unit_price / multiplier
            else:
                base_unit_price = recommended_unit_price
            
            # Calculate margin
            margin_percent = ((base_unit_price - unit_cost) / unit_cost * Decimal("100")) if unit_cost > 0 else Decimal("0")
            
            # Get batch reference (FEFO)
            batches = InventoryService.get_stock_by_batch(db, item_id, branch_id)
            batch_reference = None
            if batches and len(batches) > 0:
                batch_reference = {
                    "batch_number": batches[0].get("batch_number"),
                    "expiry_date": batches[0].get("expiry_date")
                }
            
            return {
                "recommended_unit_price": recommended_unit_price,
                "unit_cost_used": unit_cost,
                "markup_percent": None,  # Not applicable for fixed 3-tier pricing
                "margin_percent": margin_percent,
                "batch_reference": batch_reference,
                "base_unit_price": base_unit_price,
                "rounding_rule": None,  # Not applicable for fixed 3-tier pricing
                "pricing_tier": tier,
                "pricing_unit": pricing_unit
            }
        
        # Fallback to legacy markup-based pricing if 3-tier not available
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            raise ValueError(f"Item {item_id} not found")
        multiplier = get_unit_multiplier_from_item(item, unit_name)
        if multiplier is None:
            raise ValueError(f"Unit '{unit_name}' not found for item {item_id}")
        
        # Get cost (Model B: optional batch-scoped; else FEFO batch preferred)
        unit_cost = PricingService.get_item_cost(db, item_id, branch_id, use_fefo=True, batch_id=batch_id)
        if not unit_cost:
            return None
        
        # Get markup
        markup_percent = PricingService.get_markup_percent(db, item_id, company_id)
        
        # Calculate base unit price
        base_unit_price = unit_cost * (Decimal("1") + markup_percent / Decimal("100"))
        
        # Get rounding rule
        rounding_rule = PricingService.get_rounding_rule(db, item_id, company_id)
        
        # Apply rounding to base unit price
        base_unit_price = PricingService.apply_rounding(base_unit_price, rounding_rule)
        
        # Convert to sale unit price
        recommended_unit_price = base_unit_price * multiplier
        
        # Calculate margin
        margin_percent = ((base_unit_price - unit_cost) / unit_cost * Decimal("100")) if unit_cost > 0 else Decimal("0")
        
        # Get batch reference (FEFO)
        batches = InventoryService.get_stock_by_batch(db, item_id, branch_id)
        batch_reference = None
        if batches and len(batches) > 0:
            batch_reference = {
                "batch_number": batches[0].get("batch_number"),
                "expiry_date": batches[0].get("expiry_date")
            }
        
        return {
            "recommended_unit_price": recommended_unit_price,
            "unit_cost_used": unit_cost,
            "markup_percent": markup_percent,
            "margin_percent": margin_percent,
            "batch_reference": batch_reference,
            "base_unit_price": base_unit_price,
            "rounding_rule": rounding_rule,
            "pricing_tier": None,  # Legacy pricing
            "pricing_unit": unit_name
        }

    @staticmethod
    def calculate_margin(
        unit_cost: Decimal,
        selling_price: Decimal
    ) -> Dict:
        """
        Calculate margin from cost and selling price
        
        Returns:
            Dict with margin_percent, is_below_cost, is_low_margin
        """
        if unit_cost == 0:
            return {
                "margin_percent": Decimal("0"),
                "is_below_cost": False,
                "is_low_margin": False
            }
        
        margin_percent = ((selling_price - unit_cost) / unit_cost) * Decimal("100")
        is_below_cost = selling_price < unit_cost
        is_low_margin = margin_percent < Decimal("10")  # Less than 10% margin
        
        return {
            "margin_percent": margin_percent,
            "is_below_cost": is_below_cost,
            "is_low_margin": is_low_margin
        }

    @staticmethod
    def get_3tier_pricing(
        db: Session,
        item_id: UUID
    ) -> Optional[Dict]:
        """
        DEPRECATED: 3-tier pricing from items table is no longer supported.
        
        Prices must come from:
        - Cost: inventory_ledger (use CanonicalPricingService)
        - Sale price: external configuration (markup, price list, etc.)
        
        Returns:
            None (deprecated functionality)
        """
        # DEPRECATED: Do not read prices from items table
        # Cost must come from inventory_ledger
        # Sale prices must be configured separately
        return None

    @staticmethod
    def get_price_for_tier(
        db: Session,
        item_id: UUID,
        tier: str,
        unit_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get price for a specific tier (supplier, wholesale, retail) from Item model
        
        Args:
            item_id: Item ID
            tier: 'supplier', 'wholesale', or 'retail'
            unit_name: Optional unit name to convert price to
        
        Returns:
            Dict with price, unit, and optionally converted_price if unit_name provided
        """
        item = db.query(Item).filter(Item.id == item_id).first()
        
        if not item:
            return None
        
        # DEPRECATED: Do not read prices from items table
        # Cost must come from inventory_ledger (use CanonicalPricingService)
        # Sale prices must be configured separately
        return None
