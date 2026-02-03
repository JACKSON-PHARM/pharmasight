"""
Order Book Service - Automatic order book management
"""
import logging
from typing import Optional, List
from uuid import UUID
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models import (
    DailyOrderBook, Item, InventoryLedger, Supplier,
    SalesInvoiceItem, SalesInvoice
)
from app.services.inventory_service import InventoryService

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
        
        # Check if stock < pack_size (less than one full supplier pack)
        if current_stock_retail_units >= pack_size:
            logger.debug(
                f"Item {item.name} ({item_id}) stock ({current_stock_retail_units}) >= pack_size ({pack_size}) - skipping order book"
            )
            return None
        
        # Calculate monthly sales (last 30 days) in retail/base units
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
        
        # Calculate quantity needed in retail units: enough to bring stock to at least pack_size
        quantity_needed_retail_units = max(pack_size - current_stock_retail_units, 0)
        
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
        
        # Convert back to retail units for quantity_needed (for display/calculation)
        quantity_needed_retail_units = packs_needed * pack_size
        
        # Use supplier unit name for the order
        supplier_unit_name = item.supplier_unit or item.base_unit or 'pack'
        
        # Get preferred supplier (from item's last purchase or default)
        supplier_id = OrderBookService._get_preferred_supplier(db, item_id, company_id)
        
        # Check if entry already exists
        existing_entry = db.query(DailyOrderBook).filter(
            and_(
                DailyOrderBook.branch_id == branch_id,
                DailyOrderBook.item_id == item_id,
                DailyOrderBook.status == "PENDING"
            )
        ).first()
        
        # Determine reason based on is_auto flag
        reason = "AUTO_SALE" if is_auto else "MANUAL_ADD"
        
        if existing_entry:
            # Update existing entry (increase quantity if needed)
            # Convert existing quantity to supplier units for comparison
            existing_quantity_supplier_units = float(existing_entry.quantity_needed) / pack_size
            existing_packs = int(existing_quantity_supplier_units) + (1 if existing_quantity_supplier_units % 1 > 0 else 0)
            
            # Take the maximum of existing and new quantity (in supplier units)
            max_packs = max(existing_packs, packs_needed)
            quantity_needed_retail_units = max_packs * pack_size
            
            existing_entry.quantity_needed = Decimal(str(quantity_needed_retail_units))
            existing_entry.unit_name = supplier_unit_name
            existing_entry.reason = reason
            # Remove source_reference fields - not needed
            existing_entry.source_reference_type = None
            existing_entry.source_reference_id = None
            if supplier_id:
                existing_entry.supplier_id = supplier_id
            existing_entry.updated_at = datetime.utcnow()
            
            db.commit()
            db.refresh(existing_entry)
            logger.info(
                f"✅ Updated order book entry for {item.name} ({item_id}): "
                f"{max_packs} {supplier_unit_name} ({quantity_needed_retail_units} {item.retail_unit or 'units'}) "
                f"(stock: {current_stock_retail_units} {item.retail_unit or 'units'}, pack_size: {pack_size})"
            )
            return existing_entry
        else:
            # Create new entry
            order_book_entry = DailyOrderBook(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                supplier_id=supplier_id,
                quantity_needed=Decimal(str(quantity_needed_retail_units)),
                unit_name=supplier_unit_name,
                reason=reason,
                source_reference_type=None,  # Not used anymore
                source_reference_id=None,  # Not used anymore
                priority=7 if is_auto else 5,  # Higher priority for auto-generated
                status="PENDING",
                created_by=user_id
            )
            db.add(order_book_entry)
            db.commit()
            db.refresh(order_book_entry)
            
            logger.info(
                f"✅ Added to order book: {item.name} ({item_id}) - "
                f"{packs_needed} {supplier_unit_name} ({quantity_needed_retail_units} {item.retail_unit or 'units'}) "
                f"(stock: {current_stock_retail_units} {item.retail_unit or 'units'}, pack_size: {pack_size}, monthly_sales: {monthly_sales_float} {item.retail_unit or 'units'})"
            )
            return order_book_entry
    
    @staticmethod
    def _get_preferred_supplier(
        db: Session,
        item_id: UUID,
        company_id: UUID
    ) -> Optional[UUID]:
        """
        Get preferred supplier for an item.
        Returns supplier from most recent purchase, or None.
        """
        from app.models.purchase import SupplierInvoice, SupplierInvoiceItem
        
        # Get supplier from most recent purchase invoice
        last_purchase = (
            db.query(SupplierInvoice.supplier_id)
            .join(SupplierInvoiceItem, SupplierInvoiceItem.purchase_invoice_id == SupplierInvoice.id)
            .filter(
                and_(
                    SupplierInvoiceItem.item_id == item_id,
                    SupplierInvoice.company_id == company_id,
                    SupplierInvoice.status == "BATCHED"
                )
            )
            .order_by(SupplierInvoice.created_at.desc())
            .first()
        )
        
        if last_purchase:
            return last_purchase[0]
        
        return None
    
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
