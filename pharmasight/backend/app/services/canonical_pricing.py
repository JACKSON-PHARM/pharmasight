"""
Canonical Pricing Service — Single Source of Truth

All pricing MUST flow through this service.
Source of Truth: inventory_ledger; when no ledger records exist, items.default_cost_per_base is used.
"""
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func, desc
from sqlalchemy.orm import Session
from sqlalchemy.sql import func as sql_func

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

    @staticmethod
    def get_best_available_cost_batch(
        db: Session,
        item_ids: List[UUID],
        branch_id: UUID,
        company_id: UUID
    ) -> Dict[UUID, Decimal]:
        """
        Batch version: get best available cost for many items in a few queries.
        Returns dict item_id -> cost (Decimal). Missing items get 0.
        """
        if not item_ids:
            return {}
        result = {iid: None for iid in item_ids}

        # 1) Last purchase cost per item (one query with row_number)
        last_purchase_subq = (
            db.query(
                InventoryLedger.item_id,
                InventoryLedger.unit_cost,
                sql_func.row_number()
                .over(
                    partition_by=InventoryLedger.item_id,
                    order_by=desc(InventoryLedger.created_at)
                )
                .label('rn')
            )
            .filter(
                InventoryLedger.item_id.in_(item_ids),
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.company_id == company_id,
                InventoryLedger.transaction_type == 'PURCHASE',
                InventoryLedger.quantity_delta > 0
            )
        ).subquery()
        last_purchases = (
            db.query(last_purchase_subq.c.item_id, last_purchase_subq.c.unit_cost)
            .filter(last_purchase_subq.c.rn == 1)
            .all()
        )
        for row in last_purchases:
            result[row.item_id] = Decimal(str(row.unit_cost)) if row.unit_cost else Decimal('0')

        # 2) Opening balance for items still missing
        missing = [iid for iid in item_ids if result[iid] is None]
        if missing:
            opening = (
                db.query(InventoryLedger.item_id, InventoryLedger.unit_cost)
                .filter(
                    InventoryLedger.item_id.in_(missing),
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.transaction_type == 'OPENING_BALANCE',
                    InventoryLedger.reference_type == 'OPENING_BALANCE'
                )
                .all()
            )
            for row in opening:
                if result[row.item_id] is None:
                    result[row.item_id] = Decimal(str(row.unit_cost)) if row.unit_cost else Decimal('0')

        # 3) Weighted average for items still missing
        missing = [iid for iid in item_ids if result[iid] is None]
        if missing:
            wavg = (
                db.query(
                    InventoryLedger.item_id,
                    (func.sum(InventoryLedger.quantity_delta * InventoryLedger.unit_cost)
                     / func.sum(InventoryLedger.quantity_delta)).label('avg_cost')
                )
                .filter(
                    InventoryLedger.item_id.in_(missing),
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.quantity_delta > 0
                )
                .group_by(InventoryLedger.item_id)
                .all()
            )
            for row in wavg:
                if result[row.item_id] is None and row.avg_cost is not None:
                    result[row.item_id] = Decimal(str(row.avg_cost))

        # 4) Item default_cost_per_base for items still missing
        missing = [iid for iid in item_ids if result[iid] is None]
        if missing:
            defaults = (
                db.query(Item.id, Item.default_cost_per_base)
                .filter(Item.id.in_(missing), Item.company_id == company_id)
                .all()
            )
            for row in defaults:
                if result[row.id] is None and row.default_cost_per_base is not None:
                    result[row.id] = Decimal(str(row.default_cost_per_base))

        # 5) Zero for any remaining
        return {iid: (result[iid] if result[iid] is not None else Decimal('0')) for iid in item_ids}

    @staticmethod
    def get_cost_per_retail_for_valuation_batch(
        db: Session,
        item_ids: List[UUID],
        branch_id: UUID,
        company_id: UUID,
    ) -> Dict[UUID, Decimal]:
        """
        Get cost per RETAIL unit for stock valuation. Respects three-tier units.
        - PURCHASE ledger: unit_cost is already per retail → use as-is
        - OPENING_BALANCE / default: unit_cost is per wholesale → cost_per_retail = cost / pack_size
        Formula: value = quantity_retail * cost_per_retail (e.g. 98 tablets * 0.54 = 52.92 when cost is 54/packet of 100)
        """
        if not item_ids:
            return {}
        items = {i.id: i for i in db.query(Item).filter(Item.id.in_(item_ids)).all()}
        result = {}

        # 1) Last PURCHASE cost (already per retail)
        last_purchase_subq = (
            db.query(
                InventoryLedger.item_id,
                InventoryLedger.unit_cost,
                sql_func.row_number()
                .over(
                    partition_by=InventoryLedger.item_id,
                    order_by=desc(InventoryLedger.created_at),
                )
                .label("rn"),
            )
            .filter(
                InventoryLedger.item_id.in_(item_ids),
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.company_id == company_id,
                InventoryLedger.transaction_type == "PURCHASE",
                InventoryLedger.quantity_delta > 0,
            )
        ).subquery()
        for row in (
            db.query(last_purchase_subq.c.item_id, last_purchase_subq.c.unit_cost)
            .filter(last_purchase_subq.c.rn == 1)
            .all()
        ):
            result[row.item_id] = Decimal(str(row.unit_cost)) if row.unit_cost else Decimal("0")

        # 2) OPENING_BALANCE / weighted avg / default: cost is per WHOLESALE → divide by pack_size
        missing = [iid for iid in item_ids if iid not in result]
        if missing:
            cost_raw = CanonicalPricingService.get_best_available_cost_batch(
                db, missing, branch_id, company_id
            )
            for iid in missing:
                cost = cost_raw.get(iid) or Decimal("0")
                item = items.get(iid)
                pack_size = max(1, int(getattr(item, "pack_size", None) or 1))
                result[iid] = cost / Decimal(str(pack_size))

        return result
