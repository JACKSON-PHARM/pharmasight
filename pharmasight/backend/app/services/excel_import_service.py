"""
Excel Import Service - Inventory Integrity Enforced

This service implements two import modes:
- MODE A: Authoritative Reset (when no live transactions exist)
- MODE B: Non-Destructive (when live transactions exist)
"""
import logging
from typing import Dict, List, Optional, Tuple
from uuid import UUID
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models import (
    Item, ItemUnit, ItemPricing, InventoryLedger,
    Supplier, Company, Branch
)

logger = logging.getLogger(__name__)


def _normalize_column_name(row: Dict, possible_names: List[str]) -> Optional[str]:
    """
    Get value from row using any of the possible column names.
    Tries exact match first, then case-insensitive, then with spaces/underscores normalized.
    """
    for name in possible_names:
        if name in row:
            return row[name]
        # Try case-insensitive
        for key in row.keys():
            if key.lower() == name.lower():
                return row[key]
        # Try with spaces/underscores normalized
        for key in row.keys():
            normalized_key = key.replace(' ', '_').replace('-', '_').lower()
            normalized_name = name.replace(' ', '_').replace('-', '_').lower()
            if normalized_key == normalized_name:
                return row[key]
    return None


class ExcelImportService:
    """Service for importing Excel data with inventory integrity enforcement"""
    
    @staticmethod
    def has_live_transactions(db: Session, company_id: UUID) -> bool:
        """
        Detect if any live transactions exist in the system.
        
        Live transactions are any inventory_ledger entries where
        reference_type != 'OPENING_BALANCE'
        
        Returns:
            bool: True if live transactions exist, False otherwise
        """
        count = db.query(InventoryLedger).filter(
            and_(
                InventoryLedger.company_id == company_id,
                or_(
                    InventoryLedger.reference_type != 'OPENING_BALANCE',
                    InventoryLedger.reference_type.is_(None)
                )
            )
        ).count()
        
        return count > 0
    
    @staticmethod
    def detect_import_mode(db: Session, company_id: UUID) -> str:
        """
        Detect which import mode should be used.
        
        Returns:
            str: 'AUTHORITATIVE' or 'NON_DESTRUCTIVE'
        """
        if ExcelImportService.has_live_transactions(db, company_id):
            return 'NON_DESTRUCTIVE'
        return 'AUTHORITATIVE'
    
    @staticmethod
    def validate_excel_data(excel_data: List[Dict]) -> Tuple[bool, List[str]]:
        """
        Validate Excel data structure.
        
        Returns:
            Tuple[bool, List[str]]: (is_valid, error_messages)
        """
        errors = []
        # Accept multiple column name formats
        required_fields = ['Item_Name', 'Item name*', 'Item name', 'Current_Stock_Quantity', 'Current Stock Quantity']
        
        if not excel_data:
            errors.append("Excel file is empty")
            return False, errors
        
        for idx, row in enumerate(excel_data, start=2):  # Start at row 2 (header is row 1)
            for field in required_fields:
                if field not in row or row[field] is None:
                    errors.append(f"Row {idx}: Missing required field '{field}'")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def import_excel_data(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        excel_data: List[Dict],
        force_mode: Optional[str] = None
    ) -> Dict:
        """
        Import Excel data with mode detection and integrity enforcement.
        
        Args:
            db: Database session
            company_id: Company ID
            branch_id: Branch ID
            user_id: User ID performing import
            excel_data: List of dictionaries from Excel file
            force_mode: Optional mode override ('AUTHORITATIVE' or 'NON_DESTRUCTIVE')
        
        Returns:
            Dict with import results and statistics
        """
        # Validate data
        is_valid, errors = ExcelImportService.validate_excel_data(excel_data)
        if not is_valid:
            raise ValueError(f"Excel data validation failed: {', '.join(errors)}")
        
        # Detect mode
        if force_mode:
            mode = force_mode.upper()
            if mode not in ['AUTHORITATIVE', 'NON_DESTRUCTIVE']:
                raise ValueError(f"Invalid force_mode: {force_mode}")
        else:
            mode = ExcelImportService.detect_import_mode(db, company_id)
        
        logger.info(f"Excel import mode: {mode} for company {company_id}")
        
        if mode == 'AUTHORITATIVE':
            return ExcelImportService._import_authoritative(
                db, company_id, branch_id, user_id, excel_data
            )
        else:
            return ExcelImportService._import_non_destructive(
                db, company_id, branch_id, user_id, excel_data
            )
    
    @staticmethod
    def _import_authoritative(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        excel_data: List[Dict]
    ) -> Dict:
        """
        MODE A: Authoritative Reset Import
        
        - Delete existing Excel-derived records
        - Create items, units, pricing
        - Create opening balances in inventory_ledger
        """
        logger.info("Starting AUTHORITATIVE import mode")
        
        stats = {
            'items_created': 0,
            'items_updated': 0,
            'opening_balances_created': 0,
            'suppliers_created': 0,
            'errors': []
        }
        
        try:
            # Delete existing opening balances for this branch (only Excel-imported ones)
            # In authoritative mode, we can delete opening balances created from Excel
            db.query(InventoryLedger).filter(
                and_(
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.transaction_type == 'OPENING_BALANCE',
                    InventoryLedger.reference_type == 'OPENING_BALANCE'
                )
            ).delete(synchronize_session=False)
            
            # Process each Excel row
            for row in excel_data:
                try:
                    result = ExcelImportService._process_excel_row_authoritative(
                        db, company_id, branch_id, user_id, row
                    )
                    stats['items_created'] += result.get('item_created', 0)
                    stats['items_updated'] += result.get('item_updated', 0)
                    stats['opening_balances_created'] += result.get('opening_balance_created', 0)
                    stats['suppliers_created'] += result.get('supplier_created', 0)
                except Exception as e:
                    error_msg = f"Error processing row for '{row.get('Item_Name', 'Unknown')}': {str(e)}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
            
            db.commit()
            logger.info(f"AUTHORITATIVE import completed: {stats}")
            return {
                'mode': 'AUTHORITATIVE',
                'success': True,
                'stats': stats
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"AUTHORITATIVE import failed: {str(e)}")
            raise
    
    @staticmethod
    def _import_non_destructive(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        excel_data: List[Dict]
    ) -> Dict:
        """
        MODE B: Non-Destructive Import
        
        - Create missing items only
        - Fill missing prices
        - Attach supplier references
        - NO opening balances (ledger is immutable)
        - NO deletions or overwrites
        """
        logger.info("Starting NON_DESTRUCTIVE import mode")
        
        stats = {
            'items_created': 0,
            'items_skipped': 0,
            'prices_updated': 0,
            'suppliers_created': 0,
            'errors': []
        }
        
        try:
            for row in excel_data:
                try:
                    result = ExcelImportService._process_excel_row_non_destructive(
                        db, company_id, branch_id, user_id, row
                    )
                    stats['items_created'] += result.get('item_created', 0)
                    stats['items_skipped'] += result.get('item_skipped', 0)
                    stats['prices_updated'] += result.get('price_updated', 0)
                    stats['suppliers_created'] += result.get('supplier_created', 0)
                except Exception as e:
                    error_msg = f"Error processing row for '{row.get('Item_Name', 'Unknown')}': {str(e)}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
            
            db.commit()
            logger.info(f"NON_DESTRUCTIVE import completed: {stats}")
            return {
                'mode': 'NON_DESTRUCTIVE',
                'success': True,
                'stats': stats
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"NON_DESTRUCTIVE import failed: {str(e)}")
            raise
    
    @staticmethod
    def _process_excel_row_authoritative(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        row: Dict
    ) -> Dict:
        """Process a single Excel row in AUTHORITATIVE mode"""
        result = {
            'item_created': 0,
            'item_updated': 0,
            'opening_balance_created': 0,
            'supplier_created': 0
        }
        
        item_name = row.get('Item_Name', '').strip()
        if not item_name:
            return result
        
        # Find or create item by name
        item = db.query(Item).filter(
            and_(
                Item.company_id == company_id,
                Item.name == item_name
            )
        ).first()
        
        if not item:
            # Create new item
            item = ExcelImportService._create_item_from_excel(
                db, company_id, row
            )
            result['item_created'] = 1
        else:
            # Update existing item (only in authoritative mode)
            ExcelImportService._update_item_from_excel(db, item, row)
            result['item_updated'] = 1
        
        # Create/update units
        ExcelImportService._process_item_units(db, item, row)
        
        # Create/update pricing
        ExcelImportService._process_item_pricing(db, item, company_id, row)
        
        # Create supplier if needed
        supplier_id = ExcelImportService._ensure_supplier(db, company_id, row)
        if supplier_id:
            result['supplier_created'] = 1
        
        # Create opening balance
        stock_qty = ExcelImportService._parse_quantity(row.get('Current_Stock_Quantity', 0))
        if stock_qty != 0:
            ExcelImportService._create_opening_balance(
                db, company_id, branch_id, item.id, stock_qty, user_id
            )
            result['opening_balance_created'] = 1
        
        return result
    
    @staticmethod
    def _process_excel_row_non_destructive(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        row: Dict
    ) -> Dict:
        """Process a single Excel row in NON_DESTRUCTIVE mode"""
        result = {
            'item_created': 0,
            'item_skipped': 0,
            'price_updated': 0,
            'supplier_created': 0
        }
        
        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name']) or ''
        item_name = item_name.strip() if item_name else ''
        if not item_name:
            return result
        
        # Find item by name
        item = db.query(Item).filter(
            and_(
                Item.company_id == company_id,
                Item.name == item_name
            )
        ).first()
        
        if not item:
            # Create missing item only
            item = ExcelImportService._create_item_from_excel(
                db, company_id, row
            )
            result['item_created'] = 1
            
            # Create units and pricing for new item
            ExcelImportService._process_item_units(db, item, row)
            ExcelImportService._process_item_pricing(db, item, company_id, row)
        else:
            # Item exists - only update missing prices, don't overwrite
            result['item_skipped'] = 1
            price_updated = ExcelImportService._update_missing_prices_only(
                db, item, company_id, row
            )
            if price_updated:
                result['price_updated'] = 1
        
        # Create supplier if missing (non-destructive)
        supplier_id = ExcelImportService._ensure_supplier(db, company_id, row)
        if supplier_id:
            result['supplier_created'] = 1
        
        # NO opening balances in non-destructive mode
        # Stock is immutable once live transactions exist
        # Opening balances can only be created in AUTHORITATIVE mode
        
        return result
    
    @staticmethod
    def _create_item_from_excel(
        db: Session,
        company_id: UUID,
        row: Dict
    ) -> Item:
        """Create a new item from Excel row"""
        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name']) or ''
        generic_name = _normalize_column_name(row, ['Generic_Name', 'Generic Name', 'Description', 'Generic name']) or ''
        item_code = _normalize_column_name(row, ['Item_Code', 'Item Code', 'Item code', 'SKU', 'sku']) or ''
        barcode = _normalize_column_name(row, ['Barcode', 'barcode', 'BARCODE']) or ''
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY']) or ''
        base_unit = _normalize_column_name(row, ['Base_Unit', 'Base Unit', 'Base unit', 'Base Unit (x)']) or 'piece'
        last_cost = _normalize_column_name(row, ['Price_List_Last_Cost', 'Price_List_Last Cost', 'Purchase price', 'Last Cost', 'Last_Cost']) or '0'
        
        item = Item(
            company_id=company_id,
            name=item_name.strip(),
            generic_name=generic_name.strip() or None,
            sku=item_code.strip() or None,
            barcode=barcode.strip() or None,
            category=category.strip() or None,
            base_unit=base_unit.strip().lower(),
            default_cost=ExcelImportService._parse_decimal(last_cost),
            is_vatable=True,
            vat_rate=Decimal('0'),  # Most medicines are zero-rated
            vat_code='ZERO_RATED',
            price_includes_vat=False,
            is_active=True
        )
        db.add(item)
        db.flush()  # Get ID
        return item
    
    @staticmethod
    def _update_item_from_excel(db: Session, item: Item, row: Dict):
        """Update existing item from Excel (AUTHORITATIVE mode only)"""
        # Only update non-structural fields
        generic_name = _normalize_column_name(row, ['Generic_Name', 'Generic Name', 'Description', 'Generic name'])
        if generic_name:
            item.generic_name = generic_name.strip() or None
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY'])
        if category:
            item.category = category.strip() or None
        last_cost = _normalize_column_name(row, ['Price_List_Last_Cost', 'Price_List_Last Cost', 'Purchase price', 'Last Cost', 'Last_Cost'])
        if last_cost:
            item.default_cost = ExcelImportService._parse_decimal(last_cost)
    
    @staticmethod
    def _process_item_units(db: Session, item: Item, row: Dict):
        """Create/update item units from Excel"""
        base_unit_raw = _normalize_column_name(row, ['Base_Unit', 'Base Unit', 'Base unit', 'Base Unit (x)']) or 'piece'
        base_unit = base_unit_raw.strip().lower() if base_unit_raw else 'piece'
        
        # Ensure base unit exists
        base_unit_obj = db.query(ItemUnit).filter(
            and_(
                ItemUnit.item_id == item.id,
                ItemUnit.unit_name == base_unit
            )
        ).first()
        
        if not base_unit_obj:
            base_unit_obj = ItemUnit(
                item_id=item.id,
                unit_name=base_unit,
                multiplier_to_base=Decimal('1'),
                is_default=True
            )
            db.add(base_unit_obj)
        
        # Process additional units if provided
        # (Excel may have unit conversion data)
    
    @staticmethod
    def _process_item_pricing(
        db: Session,
        item: Item,
        company_id: UUID,
        row: Dict
    ):
        """Create/update item pricing rules from Excel"""
        # Calculate markup from retail price if provided
        retail_price_str = _normalize_column_name(row, ['Retail_Price', 'Retail Price', 'Retail price', 'Sale Price', 'Sale price']) or '0'
        retail_price = ExcelImportService._parse_decimal(retail_price_str)
        purchase_cost = item.default_cost or Decimal('0')
        
        if retail_price > 0 and purchase_cost > 0:
            # Calculate markup: (retail - cost) / cost * 100
            markup_percent = ((retail_price - purchase_cost) / purchase_cost * Decimal('100'))
            
            # Get or create ItemPricing
            pricing = db.query(ItemPricing).filter(
                ItemPricing.item_id == item.id
            ).first()
            
            if pricing:
                pricing.markup_percent = markup_percent
            else:
                pricing = ItemPricing(
                    item_id=item.id,
                    markup_percent=markup_percent
                )
                db.add(pricing)
    
    @staticmethod
    def _update_missing_prices_only(
        db: Session,
        item: Item,
        company_id: UUID,
        row: Dict
    ) -> bool:
        """Update only missing pricing rules (NON_DESTRUCTIVE mode)"""
        updated = False
        
        # Only update if pricing doesn't exist
        pricing = db.query(ItemPricing).filter(
            ItemPricing.item_id == item.id
        ).first()
        
        if not pricing:
            # Calculate markup from retail price if provided
            retail_price_str = _normalize_column_name(row, ['Retail_Price', 'Retail Price', 'Retail price', 'Sale Price', 'Sale price']) or '0'
            retail_price = ExcelImportService._parse_decimal(retail_price_str)
            purchase_cost = item.default_cost or Decimal('0')
            
            if retail_price > 0 and purchase_cost > 0:
                markup_percent = ((retail_price - purchase_cost) / purchase_cost * Decimal('100'))
                pricing = ItemPricing(
                    item_id=item.id,
                    markup_percent=markup_percent
                )
                db.add(pricing)
                updated = True
        
        return updated
    
    @staticmethod
    def _ensure_supplier(
        db: Session,
        company_id: UUID,
        row: Dict
    ) -> Optional[UUID]:
        """Ensure supplier exists, return supplier ID"""
        supplier_name_raw = _normalize_column_name(row, ['Supplier', 'supplier', 'SUPPLIER', 'Supplier Name', 'supplier name']) or ''
        supplier_name = supplier_name_raw.strip() if supplier_name_raw else ''
        if not supplier_name:
            return None
        
        supplier = db.query(Supplier).filter(
            and_(
                Supplier.company_id == company_id,
                Supplier.name == supplier_name
            )
        ).first()
        
        if not supplier:
            supplier = Supplier(
                company_id=company_id,
                name=supplier_name,
                is_active=True
            )
            db.add(supplier)
            db.flush()
            return supplier.id
        
        return supplier.id
    
    @staticmethod
    def _create_opening_balance(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        quantity: int,
        user_id: UUID
    ):
        """Create opening balance entry in inventory_ledger"""
        # Check if opening balance already exists for this item+branch
        existing = db.query(InventoryLedger).filter(
            and_(
                InventoryLedger.company_id == company_id,
                InventoryLedger.branch_id == branch_id,
                InventoryLedger.item_id == item_id,
                InventoryLedger.transaction_type == 'OPENING_BALANCE',
                InventoryLedger.reference_type == 'OPENING_BALANCE'
            )
        ).first()
        
        # IMPORTANT: quantity_delta MUST NOT be zero (database constraint)
        if quantity == 0:
            # Skip creating opening balance if quantity is zero
            return
        
        if existing:
            # In authoritative mode, we can update existing opening balance
            item = db.query(Item).filter(Item.id == item_id).first()
            unit_cost = item.default_cost or Decimal('0')
            existing.quantity_delta = quantity
            existing.unit_cost = unit_cost
            existing.total_cost = quantity * unit_cost
        else:
            # Create new opening balance
            item = db.query(Item).filter(Item.id == item_id).first()
            unit_cost = item.default_cost or Decimal('0')
            
            ledger_entry = InventoryLedger(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                transaction_type='OPENING_BALANCE',
                reference_type='OPENING_BALANCE',
                quantity_delta=quantity,  # Already validated != 0 above
                unit_cost=unit_cost,
                total_cost=quantity * unit_cost,
                created_by=user_id
            )
            db.add(ledger_entry)
    
    @staticmethod
    def _parse_quantity(value) -> int:
        """Parse quantity from Excel (handles strings, floats, etc.)"""
        if value is None:
            return 0
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return 0
    
    @staticmethod
    def _parse_decimal(value) -> Decimal:
        """Parse decimal from Excel"""
        if value is None:
            return Decimal('0')
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return Decimal('0')
