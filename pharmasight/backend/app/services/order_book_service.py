"""
Order Book Service - Automatic order book management
"""
import logging
import math
from typing import Optional, List, Dict
from uuid import UUID
from decimal import Decimal
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models import (
    DailyOrderBook, Item, InventoryLedger, Supplier,
    SalesInvoiceItem, SalesInvoice
)
from app.services.inventory_service import InventoryService
from app.services.snapshot_service import SnapshotService
from app.services.item_units_helper import get_unit_multiplier_from_item

logger = logging.getLogger(__name__)


class OrderBookService:
    """Service for managing automatic order book entries"""
    
    @staticmethod
    def check_and_add_to_order_book(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        user_id: UUID,
        is_auto: bool = True
    ) -> Optional[DailyOrderBook]:
        """
        Check if item should be added to order book after a sale.
        
        Criteria:
        1. Item must have had at least one sale before
        2. Current stock (in retail units) < pack_size (supplier unit size)
        3. Quantity to order ≤ monthly sales (in supplier units, rounded up)
        
        Args:
            is_auto: True if auto-generated from sale, False if manual
        
        Returns:
            DailyOrderBook entry if added, None otherwise
        """
        # Get item with 3-tier unit info
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            logger.warning(f"Item {item_id} not found for order book check")
            return None
        
        # Check if item has had sales before (at least one sale in history)
        has_sales = db.query(SalesInvoiceItem).join(
            SalesInvoice, SalesInvoiceItem.sales_invoice_id == SalesInvoice.id
        ).filter(
            and_(
                SalesInvoiceItem.item_id == item_id,
                SalesInvoice.company_id == company_id,
                SalesInvoice.branch_id == branch_id,
                SalesInvoice.status.in_(["BATCHED", "PAID"])
            )
        ).first() is not None
        
        if not has_sales:
            logger.debug(f"Item {item.name} ({item_id}) has no sales history - skipping order book")
            return None
        
        # Get current stock in retail units (base units)
        stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            and_(
                InventoryLedger.item_id == item_id,
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.company_id == company_id
            )
        )
        current_stock = stock_query.scalar() or Decimal('0')
        current_stock_retail_units = float(current_stock)
        
        # Get pack_size (supplier unit size)
        pack_size = item.pack_size or 1
        if pack_size < 1:
            pack_size = 1

        # Calculate monthly sales (last 30 days) in retail/base units - needed for both rules
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        monthly_sales_items = (
            db.query(SalesInvoiceItem.quantity, SalesInvoiceItem.unit_name)
            .join(SalesInvoice, SalesInvoiceItem.sales_invoice_id == SalesInvoice.id)
            .filter(
                and_(
                    SalesInvoiceItem.item_id == item_id,
                    SalesInvoice.company_id == company_id,
                    SalesInvoice.branch_id == branch_id,
                    SalesInvoice.status.in_(["BATCHED", "PAID"]),
                    SalesInvoice.created_at >= thirty_days_ago
                )
            )
            .all()
        )
        
        # Convert each sale quantity to retail/base units and sum
        monthly_sales_retail_units = Decimal('0')
        for sale_item in monthly_sales_items:
            try:
                # Convert sale unit quantity to base/retail units
                quantity_base = InventoryService.convert_to_base_units(
                    db, item_id, float(sale_item.quantity), sale_item.unit_name
                )
                monthly_sales_retail_units += Decimal(str(quantity_base))
            except (ValueError, AttributeError) as e:
                logger.debug(f"Could not convert sales quantity for order book (assuming sale unit = retail unit): {e}")
                # Fallback: assume sale unit = retail unit (common case)
                monthly_sales_retail_units += Decimal(str(sale_item.quantity))
            except Exception as e:
                logger.warning(f"Unexpected error converting sales quantity: {e}")
                # Fallback: use quantity as-is
                monthly_sales_retail_units += Decimal(str(sale_item.quantity))
        
        monthly_sales_float = float(monthly_sales_retail_units)

        # Rule 1: stock < pack_size (below one wholesale unit)
        # Rule 2: stock < monthly_sales/2 when monthly_sales > 0 (accumulated sales over month)
        # Rule 3: stock fell to zero after sale - add even without monthly sales data
        below_one_wholesale = current_stock_retail_units < pack_size
        below_half_monthly = monthly_sales_float > 0 and current_stock_retail_units < (monthly_sales_float / 2)
        stock_fell_to_zero = current_stock_retail_units <= 0
        if not below_one_wholesale and not below_half_monthly and not stock_fell_to_zero:
            logger.debug(
                f"Item {item.name} ({item_id}) stock ({current_stock_retail_units}) does not meet thresholds "
                f"(pack_size={pack_size}, monthly_sales/2={monthly_sales_float/2 if monthly_sales_float > 0 else 0}) - skipping order book"
            )
            return None

        # Calculate quantity needed in retail units
        if stock_fell_to_zero and monthly_sales_float <= 0:
            # Rule 3: Stock fell to zero, no monthly sales data - order at least 1 pack
            quantity_needed_retail_units = pack_size
        elif below_one_wholesale:
            # Rule 1: Bring stock up to at least pack_size
            quantity_needed_retail_units = max(pack_size - current_stock_retail_units, 0)
        else:
            # Rule 2: Triggered by below_half_monthly - order enough to reach half of monthly sales
            quantity_needed_retail_units = max((monthly_sales_float / 2) - current_stock_retail_units, 0)

        # Cap at monthly sales (if we have sales data)
        if monthly_sales_float > 0:
            quantity_needed_retail_units = min(quantity_needed_retail_units, monthly_sales_float)
        
        if quantity_needed_retail_units <= 0:
            logger.debug(f"Item {item.name} ({item_id}) quantity_needed is 0 - skipping order book")
            return None
        
        # Convert to supplier units and round up
        # If we need 10 tablets and pack_size is 30, we need 1 pack
        # If we need 35 tablets (more than 1.5 packs), we need 2 packs
        quantity_needed_supplier_units = quantity_needed_retail_units / pack_size
        
        # Round up to next supplier unit:
        # - If <= 1.5 packs, order 1 pack
        # - If > 1.5 packs, round up to next whole pack
        if quantity_needed_supplier_units <= 0:
            packs_needed = 0
        elif quantity_needed_supplier_units <= 1.5:
            packs_needed = 1
        else:
            # More than 1.5 packs - round up to next whole pack
            packs_needed = int(quantity_needed_supplier_units) + (1 if quantity_needed_supplier_units % 1 > 0 else 0)
        
        if packs_needed <= 0:
            logger.debug(f"Item {item.name} ({item_id}) packs_needed is 0 - skipping order book")
            return None

        # Order in wholesale units by default (last unit costs are per wholesale); 1 wholesale = pack_size retail
        quantity_needed_wholesale = max(1, math.ceil(float(quantity_needed_retail_units) / pack_size))
        wholesale_unit_name = (item.wholesale_unit or item.base_unit or "unit").strip() or "unit"

        # Supplier with lowest unit cost (per wholesale), or item default from import
        supplier_id = OrderBookService.get_supplier_lowest_unit_cost(db, item_id, company_id)

        # Entry date: today (items unique per branch, item, entry_date)
        entry_date_today = datetime.utcnow().date()

        # Check if entry already exists for this date (PENDING or ORDERED)
        existing_filter = [
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.item_id == item_id,
            DailyOrderBook.status.in_(["PENDING", "ORDERED"])
        ]
        if hasattr(DailyOrderBook, "entry_date"):
            existing_filter.append(DailyOrderBook.entry_date == entry_date_today)
        existing_entry = db.query(DailyOrderBook).filter(and_(*existing_filter)).first()

        if existing_entry and existing_entry.status == "ORDERED":
            logger.debug(
                f"Item {item.name} ({item_id}) already has an ORDERED entry in the order book - skipping"
            )
            return None

        # Determine reason based on is_auto flag
        reason = "AUTO_SALE" if is_auto else "MANUAL_ADD"

        if existing_entry:
            # Update existing entry (increase quantity if needed); normalize to wholesale
            existing_qty_wholesale = float(existing_entry.quantity_needed)
            try:
                mult = get_unit_multiplier_from_item(item, (existing_entry.unit_name or "").strip() or "unit")
                if mult and float(mult) > 0:
                    # quantity in existing unit -> retail = qty * mult; wholesale = retail / pack_size
                    existing_qty_wholesale = existing_qty_wholesale * float(mult) / pack_size
            except (ValueError, TypeError, ZeroDivisionError):
                pass
            max_wholesale = max(int(existing_qty_wholesale) + (1 if existing_qty_wholesale % 1 else 0), quantity_needed_wholesale)

            existing_entry.quantity_needed = Decimal(str(max_wholesale))
            existing_entry.unit_name = wholesale_unit_name
            existing_entry.reason = reason
            existing_entry.source_reference_type = None
            existing_entry.source_reference_id = None
            if supplier_id:
                existing_entry.supplier_id = supplier_id
            existing_entry.updated_at = datetime.utcnow()

            db.commit()
            db.refresh(existing_entry)
            logger.info(
                f"✅ Updated order book entry for {item.name} ({item_id}): "
                f"{max_wholesale} {wholesale_unit_name} (stock: {current_stock_retail_units})"
            )
            return existing_entry
        else:
            # Create new entry in wholesale units (date-unique: one per branch, item, entry_date)
            create_kw = dict(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                supplier_id=supplier_id,
                quantity_needed=Decimal(str(quantity_needed_wholesale)),
                unit_name=wholesale_unit_name,
                reason=reason,
                source_reference_type=None,
                source_reference_id=None,
                priority=7 if is_auto else 5,
                status="PENDING",
                created_by=user_id
            )
            if hasattr(DailyOrderBook, "entry_date"):
                create_kw["entry_date"] = entry_date_today
            order_book_entry = DailyOrderBook(**create_kw)
            db.add(order_book_entry)
            db.flush()
            SnapshotService.upsert_search_snapshot_last_order_book(
                db, company_id, branch_id, item_id, order_book_entry.created_at or datetime.utcnow()
            )
            db.commit()
            db.refresh(order_book_entry)

            logger.info(
                f"✅ Added to order book: {item.name} ({item_id}) - "
                f"{quantity_needed_wholesale} {wholesale_unit_name} (stock: {current_stock_retail_units})"
            )
            return order_book_entry
    
    @staticmethod
    def _get_preferred_supplier(
        db: Session,
        item_id: UUID,
        company_id: UUID
    ) -> Optional[UUID]:
        """Alias for backward compatibility; use _get_supplier_lowest_unit_cost."""
        return OrderBookService.get_supplier_lowest_unit_cost(db, item_id, company_id)

    @staticmethod
    def get_supplier_lowest_unit_cost(
        db: Session,
        item_id: UUID,
        company_id: UUID
    ) -> Optional[UUID]:
        """
        Get the supplier with the lowest unit cost for this item (cost per wholesale unit).
        Uses latest invoice line per supplier, normalizes to cost per wholesale for comparison.
        Falls back to item.default_supplier_id (e.g. from Excel import) if no invoice history.
        """
        from app.models.purchase import SupplierInvoice, SupplierInvoiceItem

        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return None

        # All invoice lines for this item from batched invoices (one row per line)
        rows = (
            db.query(
                SupplierInvoice.supplier_id,
                SupplierInvoiceItem.unit_cost_exclusive,
                SupplierInvoiceItem.unit_name,
                SupplierInvoice.invoice_date,
            )
            .join(SupplierInvoiceItem, SupplierInvoiceItem.purchase_invoice_id == SupplierInvoice.id)
            .filter(
                and_(
                    SupplierInvoiceItem.item_id == item_id,
                    SupplierInvoice.company_id == company_id,
                    SupplierInvoice.status == "BATCHED"
                )
            )
            .order_by(SupplierInvoice.invoice_date.desc())
            .all()
        )

        # Per supplier, keep only the most recent line (first after desc order)
        by_supplier = {}
        for r in rows:
            if r.supplier_id not in by_supplier:
                by_supplier[r.supplier_id] = (r.unit_cost_exclusive, r.unit_name)

        if not by_supplier:
            return getattr(item, "default_supplier_id", None)

        pack_size = max(1, int(item.pack_size or 1))
        best_supplier_id = None
        best_cost_per_wholesale = None

        for sup_id, (unit_cost, unit_name) in by_supplier.items():
            try:
                mult = get_unit_multiplier_from_item(item, unit_name or "")
                if mult is None or float(mult) <= 0:
                    continue
                # cost per base (retail) = unit_cost / mult; 1 wholesale = pack_size retail
                cost_per_wholesale = float(unit_cost) / float(mult) * pack_size
            except (ValueError, TypeError, ZeroDivisionError):
                continue
            if best_cost_per_wholesale is None or cost_per_wholesale < best_cost_per_wholesale:
                best_cost_per_wholesale = cost_per_wholesale
                best_supplier_id = sup_id

        if best_supplier_id is not None:
            return best_supplier_id
        return getattr(item, "default_supplier_id", None)

    @staticmethod
    def get_cheapest_supplier_ids_batch(
        db: Session,
        item_ids: List[UUID],
        company_id: UUID
    ) -> Dict[UUID, Optional[UUID]]:
        """
        For each item, return the supplier_id with the lowest unit cost (per wholesale).
        Uses latest invoice line per (item, supplier). Falls back to item.default_supplier_id.
        Returns dict item_id -> supplier_id (or None).
        """
        from app.models.purchase import SupplierInvoice, SupplierInvoiceItem

        if not item_ids:
            return {}
        items = {i.id: i for i in db.query(Item).filter(Item.id.in_(item_ids)).all()}
        rows = (
            db.query(
                SupplierInvoiceItem.item_id,
                SupplierInvoice.supplier_id,
                SupplierInvoiceItem.unit_cost_exclusive,
                SupplierInvoiceItem.unit_name,
                SupplierInvoice.invoice_date,
            )
            .join(SupplierInvoice, SupplierInvoice.id == SupplierInvoiceItem.purchase_invoice_id)
            .filter(
                and_(
                    SupplierInvoiceItem.item_id.in_(item_ids),
                    SupplierInvoice.company_id == company_id,
                    SupplierInvoice.status == "BATCHED"
                )
            )
            .order_by(SupplierInvoice.invoice_date.desc())
            .all()
        )
        # Per (item_id, supplier_id) keep only most recent
        by_item_supplier = {}
        for r in rows:
            key = (r.item_id, r.supplier_id)
            if key not in by_item_supplier:
                by_item_supplier[key] = (r.unit_cost_exclusive, r.unit_name)
        result = {}
        for item_id in item_ids:
            item = items.get(item_id)
            if not item:
                result[item_id] = None
                continue
            by_supplier = {
                sup_id: by_item_supplier[(item_id, sup_id)]
                for (iid, sup_id) in by_item_supplier
                if iid == item_id
            }
            if not by_supplier:
                result[item_id] = getattr(item, "default_supplier_id", None)
                continue
            pack_size = max(1, int(item.pack_size or 1))
            best_supplier_id = None
            best_cost = None
            for sup_id, (unit_cost, unit_name) in by_supplier.items():
                try:
                    mult = get_unit_multiplier_from_item(item, unit_name or "")
                    if mult is None or float(mult) <= 0:
                        continue
                    cost_per_wholesale = float(unit_cost) / float(mult) * pack_size
                except (ValueError, TypeError, ZeroDivisionError):
                    continue
                if best_cost is None or cost_per_wholesale < best_cost:
                    best_cost = cost_per_wholesale
                    best_supplier_id = sup_id
            result[item_id] = best_supplier_id if best_supplier_id is not None else getattr(item, "default_supplier_id", None)
        return result

    @staticmethod
    def process_sale_for_order_book(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        invoice_id: UUID,
        user_id: UUID
    ) -> List[DailyOrderBook]:
        """
        Process a batched sales invoice and check all items for order book.
        
        Only called for BATCHED invoices (which have reduced stock).
        Quotations and non-batched invoices do NOT trigger this.
        
        Returns list of order book entries created/updated.
        """
        invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
        if not invoice:
            return []
        
        # Only process BATCHED invoices (stock has been reduced)
        # Quotations and DRAFT invoices don't reduce stock, so they shouldn't trigger order book
        if invoice.status != "BATCHED":
            logger.debug(f"Invoice {invoice_id} status is {invoice.status}, not BATCHED - skipping order book check")
            return []
        
        entries_created = []
        
        # Get unique items from invoice
        item_ids = {item.item_id for item in invoice.items}
        
        for item_id in item_ids:
            try:
                entry = OrderBookService.check_and_add_to_order_book(
                    db=db,
                    company_id=company_id,
                    branch_id=branch_id,
                    item_id=item_id,
                    user_id=user_id,
                    is_auto=True  # Auto-generated from sale
                )
                if entry:
                    entries_created.append(entry)
            except Exception as e:
                logger.error(
                    f"Error checking order book for item {item_id} after sale: {e}",
                    exc_info=True
                )
                # Continue with other items
                continue
        
        return entries_created
