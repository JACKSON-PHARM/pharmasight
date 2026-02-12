"""
Inventory Service - Stock calculation and FEFO allocation
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional, Dict, Tuple
from datetime import date
from uuid import UUID
from decimal import Decimal
from app.models import InventoryLedger, Item, Branch
from app.schemas.inventory import StockBalance, BatchStock, StockAvailability, UnitBreakdown
from app.services.item_units_helper import get_unit_multiplier_from_item


class InventoryService:
    """Service for inventory calculations and FEFO allocation"""

    @staticmethod
    def get_current_stock(
        db: Session,
        item_id: UUID,
        branch_id: UUID
    ) -> float:
        """
        Get current stock balance in base (retail) units.
        e.g. 98 tablets in stock returns 98.0; no decimals for partial packs.
        """
        result = db.query(
            func.coalesce(func.sum(InventoryLedger.quantity_delta), 0)
        ).filter(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id
            )
        ).scalar()
        return float(result) if result is not None else 0.0

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
                "quantity": float(r.quantity),
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
        Get stock availability with unit breakdown and batch breakdown.
        Base = retail; breakdown e.g. "0 cartons, 0 packs, 98 tablets".
        """
        # Get item; units from item columns (items table is source of truth)
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return None
        
        wholesale_name = (item.wholesale_unit or item.base_unit or "piece").strip() or "piece"
        retail_name = (item.retail_unit or "").strip() or "piece"
        supplier_name = (item.supplier_unit or "").strip()
        pack = max(1, int(item.pack_size or 1))
        wups = max(0.0001, float(item.wholesale_units_per_supplier or 1))
        # Multipliers to base (retail): how many retail units per 1 unit of this tier
        units_list = [(retail_name, 1.0, True)]  # retail -> 1
        if wholesale_name and wholesale_name.lower() != retail_name.lower():
            units_list.append((wholesale_name, float(pack), False))  # 1 wholesale = pack_size retail
        if supplier_name and supplier_name.lower() != wholesale_name.lower():
            units_list.append((supplier_name, float(pack) * wups, False))  # 1 supplier = pack*wups retail
        # Sort by multiplier desc (largest first for breakdown)
        units_list.sort(key=lambda x: x[1], reverse=True)
        
        total_base_units = InventoryService.get_current_stock(db, item_id, branch_id)  # in retail
        unit_breakdown = []
        remaining = total_base_units
        
        for unit_name, multiplier, is_default in units_list:
            if multiplier <= 0:
                continue
            whole_units = int(remaining // multiplier)
            remainder = remaining % multiplier
            if whole_units > 0 or (whole_units == 0 and is_default):
                display_parts = []
                if whole_units > 0:
                    display_parts.append(f"{whole_units} {unit_name}")
                remainder_int = int(round(remainder))
                if remainder_int > 0:
                    display_parts.append(f"{remainder_int} {retail_name}")
                unit_breakdown.append(UnitBreakdown(
                    unit_name=unit_name,
                    multiplier=multiplier,
                    whole_units=whole_units,
                    remainder_base_units=remainder_int,
                    display=" + ".join(display_parts) if display_parts else f"0 {retail_name}"
                ))
            remaining = remainder
        
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
        quantity_needed: float,
        unit_name: str
    ) -> List[Dict]:
        """
        Allocate stock using FEFO (First Expiry First Out).
        quantity_needed is in base (retail) units (e.g. 20 for 20 tablets).
        """
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            raise ValueError(f"Item {item_id} not found")
        multiplier = get_unit_multiplier_from_item(item, unit_name)
        if multiplier is None:
            raise ValueError(f"Unit '{unit_name}' not found for item {item_id}")
        
        quantity_needed = float(quantity_needed)
        if quantity_needed <= 0:
            return []
        
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
            available = float(batch.available)
            if available <= 0:
                continue
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
    ) -> float:
        """
        Convert quantity from given unit to base (retail) units.
        e.g. 20 tablets -> 20; 1 pack (pack_size 100) -> 100; no decimals needed.
        """
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            raise ValueError(f"Item {item_id} not found")
        mult = get_unit_multiplier_from_item(item, unit_name)
        if mult is None:
            raise ValueError(f"Unit '{unit_name}' not found for item {item_id}")
        return float(quantity) * float(mult)

    @staticmethod
    def check_stock_availability(
        db: Session,
        item_id: UUID,
        branch_id: UUID,
        quantity: float,
        unit_name: str
    ) -> Tuple[bool, float, float]:
        """
        Check if stock is available.
        Returns (is_available, available_stock_retail_units, required_retail_units).
        """
        required_base = InventoryService.convert_to_base_units(db, item_id, quantity, unit_name)
        available_base = InventoryService.get_current_stock(db, item_id, branch_id)
        return (available_base >= required_base, available_base, required_base)

    @staticmethod
    def get_stock_display(
        db: Session,
        item_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get stock display using 3-tier units (base = retail).
        Stock in base = retail qty. Display e.g. "0 cartons, 0 packs, 98 tablets" when only 98 tablets.
        """
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return "0"
        total_retail = InventoryService.get_current_stock(db, item_id, branch_id)  # retail (base) qty
        wholesale_unit = getattr(item, "wholesale_unit", None) or item.base_unit or "piece"
        retail_unit = getattr(item, "retail_unit", None) or "piece"
        supplier_unit = getattr(item, "supplier_unit", None) or "piece"
        pack_size = max(1, int(getattr(item, "pack_size", None) or 1))
        wups = max(0.0001, float(getattr(item, "wholesale_units_per_supplier", None) or 1))
        units_per_supplier = pack_size * wups
        supplier_whole = int(total_retail // units_per_supplier) if units_per_supplier >= 1 else 0
        remainder_after_supplier = total_retail - (supplier_whole * units_per_supplier)
        wholesale_whole = int(remainder_after_supplier // pack_size) if pack_size >= 1 else 0
        retail_remainder = int(remainder_after_supplier % pack_size) if pack_size >= 1 else int(total_retail)
        parts = []
        if supplier_whole > 0:
            parts.append(f"{supplier_whole} {supplier_unit}")
        if wholesale_whole > 0:
            parts.append(f"{wholesale_whole} {wholesale_unit}")
        if retail_remainder > 0 or not parts:
            parts.append(f"{retail_remainder} {retail_unit}")
        return " + ".join(parts) if parts else "0"
