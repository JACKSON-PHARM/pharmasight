"""
Inventory Service - Stock calculation and FEFO allocation
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional, Dict, Tuple
from datetime import date
from uuid import UUID
from decimal import Decimal
from app.models import InventoryLedger, Item, ItemUnit, Branch
from app.schemas.inventory import StockBalance, BatchStock, StockAvailability, UnitBreakdown


class InventoryService:
    """Service for inventory calculations and FEFO allocation"""

    @staticmethod
    def get_current_stock(
        db: Session,
        item_id: UUID,
        branch_id: UUID
    ) -> int:
        """
        Get current stock balance in base units
        
        Returns:
            int: Total stock in base units (can be negative if oversold)
        """
        result = db.query(
            func.coalesce(func.sum(InventoryLedger.quantity_delta), 0)
        ).filter(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id
            )
        ).scalar()
        
        return int(result) if result else 0

    @staticmethod
    def get_stock_by_batch(
        db: Session,
        item_id: UUID,
        branch_id: UUID
    ) -> List[Dict]:
        """
        Get stock breakdown by batch (FEFO-ready)
        
        Returns:
            List of dicts with batch_number, expiry_date, quantity, unit_cost, total_cost
        """
        results = db.query(
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
            func.sum(InventoryLedger.quantity_delta).label('quantity'),
            func.avg(InventoryLedger.unit_cost).label('unit_cost'),
            func.sum(InventoryLedger.total_cost).label('total_cost')
        ).filter(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id
            )
        ).group_by(
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date
        ).having(
            func.sum(InventoryLedger.quantity_delta) > 0
        ).order_by(
            InventoryLedger.expiry_date.asc().nulls_last(),  # FEFO: earliest expiry first
            InventoryLedger.batch_number.asc()
        ).all()
        
        return [
            {
                "batch_number": r.batch_number,
                "expiry_date": r.expiry_date,
                "quantity": int(r.quantity),
                "unit_cost": float(r.unit_cost),
                "total_cost": float(r.total_cost)
            }
            for r in results
        ]

    @staticmethod
    def get_stock_availability(
        db: Session,
        item_id: UUID,
        branch_id: UUID
    ) -> Optional[StockAvailability]:
        """
        Get stock availability with unit breakdown and batch breakdown
        
        Returns:
            StockAvailability with unit breakdown (e.g., "8 boxes + 40 tablets")
        """
        # Get item and units
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return None
        
        units = db.query(ItemUnit).filter(
            ItemUnit.item_id == item_id
        ).order_by(ItemUnit.multiplier_to_base.desc()).all()
        
        # Get total stock in base units
        total_base_units = InventoryService.get_current_stock(db, item_id, branch_id)
        
        # Build unit breakdown
        unit_breakdown = []
        remaining = total_base_units
        
        for unit in units:
            multiplier = float(unit.multiplier_to_base)
            whole_units = int(remaining // multiplier)
            remainder = int(remaining % multiplier)
            
            if whole_units > 0 or (whole_units == 0 and unit.is_default):
                display_parts = []
                if whole_units > 0:
                    display_parts.append(f"{whole_units} {unit.unit_name}")
                if remainder > 0:
                    display_parts.append(f"{remainder} {item.base_unit}")
                
                unit_breakdown.append(UnitBreakdown(
                    unit_name=unit.unit_name,
                    multiplier=multiplier,
                    whole_units=whole_units,
                    remainder_base_units=remainder,
                    display=" + ".join(display_parts) if display_parts else f"0 {item.base_unit}"
                ))
        
        # Get batch breakdown
        batch_data = InventoryService.get_stock_by_batch(db, item_id, branch_id)
        batch_breakdown = [
            BatchStock(
                batch_number=b.get("batch_number"),
                expiry_date=b.get("expiry_date"),
                quantity=b["quantity"],
                unit_cost=Decimal(str(b["unit_cost"])),
                total_cost=Decimal(str(b["total_cost"]))
            )
            for b in batch_data
        ]
        
        return StockAvailability(
            item_id=item_id,
            item_name=item.name,
            base_unit=item.base_unit,
            total_base_units=total_base_units,
            unit_breakdown=unit_breakdown,
            batch_breakdown=batch_breakdown
        )

    @staticmethod
    def allocate_stock_fefo(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        quantity_needed: int,
        unit_name: str
    ) -> List[Dict]:
        """
        Allocate stock using FEFO (First Expiry First Out)
        
        Args:
            item_id: Item to allocate
            branch_id: Branch
            quantity_needed: Quantity needed in base units
            unit_name: Unit name for reference
        
        Returns:
            List of allocation dicts with:
            - batch_number
            - expiry_date
            - quantity (base units)
            - unit_cost
            - ledger_entry_id (for reference)
        """
        # Get item unit multiplier
        item_unit = db.query(ItemUnit).filter(
            and_(
                ItemUnit.item_id == item_id,
                ItemUnit.unit_name == unit_name
            )
        ).first()
        
        if not item_unit:
            raise ValueError(f"Unit '{unit_name}' not found for item {item_id}")
        
        # Get available batches (FEFO order)
        batches = db.query(
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
            InventoryLedger.unit_cost,
            InventoryLedger.id.label('ledger_entry_id'),
            func.sum(InventoryLedger.quantity_delta).label('available')
        ).filter(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id
            )
        ).group_by(
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
            InventoryLedger.unit_cost,
            InventoryLedger.id
        ).having(
            func.sum(InventoryLedger.quantity_delta) > 0
        ).order_by(
            InventoryLedger.expiry_date.asc().nulls_last(),  # FEFO
            InventoryLedger.batch_number.asc()
        ).all()
        
        allocations = []
        remaining = quantity_needed
        
        for batch in batches:
            if remaining <= 0:
                break
            
            available = int(batch.available)
            if available <= 0:
                continue
            
            # Take what we need from this batch
            take = min(remaining, available)
            
            allocations.append({
                "batch_number": batch.batch_number,
                "expiry_date": batch.expiry_date,
                "quantity": take,
                "unit_cost": float(batch.unit_cost),
                "ledger_entry_id": batch.ledger_entry_id
            })
            
            remaining -= take
        
        if remaining > 0:
            raise ValueError(
                f"Insufficient stock. Needed {quantity_needed} base units, "
                f"but only {quantity_needed - remaining} available."
            )
        
        return allocations

    @staticmethod
    def convert_to_base_units(
        db: Session,
        item_id: UUID,
        quantity: float,
        unit_name: str
    ) -> int:
        """
        Convert quantity from given unit to base units
        
        Args:
            item_id: Item ID
            quantity: Quantity in given unit
            unit_name: Unit name (box, carton, etc.)
        
        Returns:
            int: Quantity in base units
        """
        item_unit = db.query(ItemUnit).filter(
            and_(
                ItemUnit.item_id == item_id,
                ItemUnit.unit_name == unit_name
            )
        ).first()
        
        if not item_unit:
            raise ValueError(f"Unit '{unit_name}' not found for item {item_id}")
        
        return int(quantity * float(item_unit.multiplier_to_base))

    @staticmethod
    def check_stock_availability(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        quantity: float,
        unit_name: str
    ) -> Tuple[bool, int, int]:
        """
        Check if stock is available
        
        Returns:
            Tuple of (is_available, available_stock_base_units, required_base_units)
        """
        required_base = InventoryService.convert_to_base_units(
            db, item_id, quantity, unit_name
        )
        available_base = InventoryService.get_current_stock(db, item_id, branch_id)
        
        return (available_base >= required_base, available_base, required_base)

