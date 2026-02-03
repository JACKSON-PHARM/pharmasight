"""
Pricing Service - Cost-based pricing with batch awareness
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import Optional, Dict
from uuid import UUID
from decimal import Decimal, ROUND_HALF_UP
from app.models import (
    Item, ItemPricing, CompanyPricingDefault,
    InventoryLedger
)
from app.services.inventory_service import InventoryService
from app.services.item_units_helper import get_unit_multiplier_from_item


class PricingService:
    """Service for calculating recommended selling prices"""

    @staticmethod
    def get_item_cost(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        use_fefo: bool = True
    ) -> Optional[Decimal]:
        """
        Get unit cost for item (FEFO batch or last purchase)
        
        Priority:
        1. FEFO batch cost (if use_fefo=True and stock available)
        2. Last purchase cost
        3. Item default cost
        
        Returns:
            Decimal: Cost per base unit, or None if not available
        """
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
    def get_markup_percent(
        db: Session,
        item_id: UUID,
        company_id: UUID
    ) -> Decimal:
        """
        Get markup percentage for item
        
        Priority:
        1. Item-specific markup
        2. Company default markup
        
        Returns:
            Decimal: Markup percentage (e.g., 30.00 for 30%)
        """
        # Check item-specific pricing
        item_pricing = db.query(ItemPricing).filter(
            ItemPricing.item_id == item_id
        ).first()
        
        if item_pricing and item_pricing.markup_percent:
            return Decimal(str(item_pricing.markup_percent))
        
        # Fallback to company default
        company_defaults = db.query(CompanyPricingDefault).filter(
            CompanyPricingDefault.company_id == company_id
        ).first()
        
        if company_defaults:
            return Decimal(str(company_defaults.default_markup_percent))
        
        # Ultimate fallback
        return Decimal("30.00")

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
        tier: str = "retail"
    ) -> Optional[Dict]:
        """
        Calculate recommended selling price for item
        
        Args:
            item_id: Item ID
            branch_id: Branch ID
            company_id: Company ID
            unit_name: Sale unit (tablet, box, etc.)
            tier: Pricing tier to use ('supplier', 'wholesale', or 'retail'). Defaults to 'retail'
        
        Returns:
            Dict with:
            - recommended_unit_price (in sale unit)
            - unit_cost_used (per base unit)
            - markup_percent
            - margin_percent
            - batch_reference (batch info if FEFO)
            - base_unit_price (per base unit)
            - pricing_tier (which tier was used)
            - pricing_unit (unit for the tier price)
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
            
            # Get cost for margin calculation
            unit_cost = PricingService.get_item_cost(db, item_id, branch_id, use_fefo=True)
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
        
        # Get cost (FEFO batch preferred)
        unit_cost = PricingService.get_item_cost(db, item_id, branch_id, use_fefo=True)
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
