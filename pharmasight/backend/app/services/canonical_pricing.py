"""
Canonical Pricing Service — Single Source of Truth

All pricing MUST flow through this service.
Source of Truth: inventory_ledger; when no ledger records exist, items.default_cost_per_base is used.
"""
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, desc
from sqlalchemy.orm import Session

from app.models import InventoryLedger, Item


class CanonicalPricingService:
    """
    Centralized pricing service enforcing inventory_ledger as single source of truth.
    
    RULES:
    1. Cost comes from inventory_ledger (PURCHASE or OPENING_BALANCE transactions)
    2. NO reads from items.default_cost or items.*_price_per_*
    3. Sale price must be configured separately (markup, price list, etc.) — NOT from items table
    """
    
    @staticmethod
    def get_last_purchase_cost(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        company_id: UUID
    ) -> Optional[Decimal]:
        """
        Get last purchase cost from inventory_ledger (most recent PURCHASE transaction).
        
        Returns:
            Decimal: unit_cost from most recent PURCHASE, or None if no purchases
        """
        last_purchase = (
            db.query(InventoryLedger)
            .filter(
                and_(
                    InventoryLedger.item_id == item_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.transaction_type == 'PURCHASE',
                    InventoryLedger.quantity_delta > 0
                )
            )
            .order_by(desc(InventoryLedger.created_at))
            .first()
        )
        
        if last_purchase:
            return Decimal(str(last_purchase.unit_cost))
        
        return None
    
    @staticmethod
    def get_opening_balance_cost(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        company_id: UUID
    ) -> Optional[Decimal]:
        """
        Get cost from OPENING_BALANCE ledger entry.
        
        Returns:
            Decimal: unit_cost from OPENING_BALANCE, or None if no opening balance
        """
        opening_balance = (
            db.query(InventoryLedger)
            .filter(
                and_(
                    InventoryLedger.item_id == item_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.transaction_type == 'OPENING_BALANCE',
                    InventoryLedger.reference_type == 'OPENING_BALANCE'
                )
            )
            .first()
        )
        
        if opening_balance:
            return Decimal(str(opening_balance.unit_cost))
        
        return None
    
    @staticmethod
    def get_weighted_average_cost(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        company_id: UUID
    ) -> Optional[Decimal]:
        """
        Get weighted average cost from all positive inventory movements (PURCHASE + OPENING_BALANCE).
        
        Formula: SUM(quantity_delta * unit_cost) / SUM(quantity_delta) WHERE quantity_delta > 0
        
        Returns:
            Decimal: weighted average cost, or None if no positive movements
        """
        result = (
            db.query(
                func.sum(InventoryLedger.quantity_delta * InventoryLedger.unit_cost).label('total_cost'),
                func.sum(InventoryLedger.quantity_delta).label('total_quantity')
            )
            .filter(
                and_(
                    InventoryLedger.item_id == item_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.quantity_delta > 0
                )
            )
            .first()
        )
        
        if result and result.total_quantity and result.total_quantity > 0:
            return Decimal(str(result.total_cost)) / Decimal(str(result.total_quantity))
        
        return None
    
    @staticmethod
    def get_best_available_cost(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        company_id: UUID
    ) -> Decimal:
        """
        Get best available cost with fallback priority:
        1. Last purchase cost (most recent PURCHASE transaction)
        2. Opening balance cost (OPENING_BALANCE transaction)
        3. Weighted average cost (all positive movements)
        4. items.default_cost_per_base (when no ledger data)
        5. Zero (if no ledger data and no default)
        
        Returns:
            Decimal: Best available cost (never None; returns 0 if no data)
        """
        # Try last purchase
        cost = CanonicalPricingService.get_last_purchase_cost(db, item_id, branch_id, company_id)
        if cost is not None:
            return cost
        
        # Try opening balance
        cost = CanonicalPricingService.get_opening_balance_cost(db, item_id, branch_id, company_id)
        if cost is not None:
            return cost
        
        # Try weighted average
        cost = CanonicalPricingService.get_weighted_average_cost(db, item_id, branch_id, company_id)
        if cost is not None:
            return cost
        
        # Fallback: item default (only when no ledger history)
        item = db.query(Item).filter(
            Item.id == item_id,
            Item.company_id == company_id,
        ).first()
        if item and item.default_cost_per_base is not None:
            return Decimal(str(item.default_cost_per_base))
        
        return Decimal('0')
