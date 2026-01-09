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
    InventoryLedger, ItemUnit
)
from app.services.inventory_service import InventoryService


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
        
        # Fallback to item default cost
        item = db.query(Item).filter(Item.id == item_id).first()
        if item and item.default_cost:
            return Decimal(str(item.default_cost))
        
        return None

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
        unit_name: str
    ) -> Optional[Dict]:
        """
        Calculate recommended selling price for item
        
        Args:
            item_id: Item ID
            branch_id: Branch ID
            company_id: Company ID
            unit_name: Sale unit (tablet, box, etc.)
        
        Returns:
            Dict with:
            - recommended_unit_price (in sale unit)
            - unit_cost_used (per base unit)
            - markup_percent
            - margin_percent
            - batch_reference (batch info if FEFO)
            - base_unit_price (per base unit)
        """
        # Get unit multiplier
        item_unit = db.query(ItemUnit).filter(
            and_(
                ItemUnit.item_id == item_id,
                ItemUnit.unit_name == unit_name
            )
        ).first()
        
        if not item_unit:
            raise ValueError(f"Unit '{unit_name}' not found for item {item_id}")
        
        multiplier = Decimal(str(item_unit.multiplier_to_base))
        
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
            "rounding_rule": rounding_rule
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

