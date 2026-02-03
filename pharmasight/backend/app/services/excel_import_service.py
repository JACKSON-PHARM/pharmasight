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
from sqlalchemy import func, and_, or_, text

from app.models import (
    Item, ItemPricing, InventoryLedger,
    Supplier, Company, Branch
)

logger = logging.getLogger(__name__)

# System field keys for column mapping (Vyper-style: user maps Excel headers to these)
# Maps system_key -> canonical header name used by _normalize_column_name lookups
SYSTEM_TO_CANONICAL_HEADER: Dict[str, str] = {
    'item_name': 'Item_Name',
    'description': 'Description',
    'generic_name': 'Generic_Name',  # legacy map → description
    'item_code': 'Item_Code',
    'barcode': 'Barcode',
    'category': 'Category',
    'supplier_unit': 'Supplier_Unit',
    'wholesale_unit': 'Wholesale_Unit',
    'retail_unit': 'Retail_Unit',
    'pack_size': 'Pack_Size',
    'can_break_bulk': 'Can_Break_Bulk',
    'track_expiry': 'Track_Expiry',
    'is_controlled': 'Is_Controlled',
    'is_cold_chain': 'Is_Cold_Chain',
    'purchase_price_per_supplier_unit': 'Purchase_Price_per_Supplier_Unit',
    'wholesale_price_per_wholesale_unit': 'Wholesale_Price_per_Wholesale_Unit',
    'retail_price_per_retail_unit': 'Retail_Price_per_Retail_Unit',
    'current_stock_quantity': 'Current_Stock_Quantity',
    'wholesale_unit_price': 'Wholesale_Unit_Price',
    'supplier': 'Supplier',
    'vat_category': 'VAT_Category',
    'vat_rate': 'VAT_Rate',
    'base_unit': 'Base_Unit',
    'secondary_unit': 'Secondary_Unit',
    'conversion_rate': 'Conversion_Rate',
    'wholesale_units_per_supplier': 'Wholesale_Units_per_Supplier',
}

# Expected fields for UI: id (system_key), label, required
# Single 3-tier unit model only: wholesale = base (1 per item), retail = wholesale × pack_size, supplier = wholesale ÷ wholesale_units_per_supplier.
# No separate "base unit / secondary unit / conversion rate" — those are duplicates of wholesale/retail/pack_size.
EXPECTED_EXCEL_FIELDS: List[Dict] = [
    {'id': 'item_name', 'label': 'Item Name', 'required': True},
    {'id': 'description', 'label': 'Description', 'required': False},
    {'id': 'generic_name', 'label': 'Generic Name / Description (maps to description)', 'required': False},
    {'id': 'item_code', 'label': 'Item Code (SKU)', 'required': False},
    {'id': 'barcode', 'label': 'Barcode', 'required': False},
    {'id': 'category', 'label': 'Category', 'required': False},
    # 3-tier units only: wholesale (base), retail, supplier + conversion numbers
    {'id': 'wholesale_unit', 'label': 'Wholesale Unit (base = 1 per item; e.g. box, bottle)', 'required': False},
    {'id': 'retail_unit', 'label': 'Retail Unit (e.g. tablet, piece, ml)', 'required': False},
    {'id': 'supplier_unit', 'label': 'Supplier Unit (e.g. carton, crate, dozen)', 'required': False},
    {'id': 'pack_size', 'label': 'Pack Size (retail per wholesale: 1 wholesale = N retail)', 'required': False},
    {'id': 'wholesale_units_per_supplier', 'label': 'Wholesale per Supplier (e.g. 12 = 1 carton has 12 wholesale)', 'required': False},
    {'id': 'can_break_bulk', 'label': 'Can Break Bulk', 'required': False},
    {'id': 'track_expiry', 'label': 'Track Expiry', 'required': False},
    {'id': 'is_controlled', 'label': 'Is Controlled', 'required': False},
    {'id': 'is_cold_chain', 'label': 'Is Cold Chain', 'required': False},
    {'id': 'wholesale_unit_price', 'label': 'Wholesale Unit Price (purchase cost per wholesale unit)', 'required': False},
    {'id': 'purchase_price_per_supplier_unit', 'label': 'Purchase Price per Supplier Unit (fallback)', 'required': False},
    {'id': 'wholesale_price_per_wholesale_unit', 'label': 'Wholesale Price', 'required': False},
    {'id': 'retail_price_per_retail_unit', 'label': 'Retail Price / Sale Price', 'required': False},
    {'id': 'current_stock_quantity', 'label': 'Current Stock Quantity', 'required': False},
    {'id': 'supplier', 'label': 'Supplier', 'required': False},
    {'id': 'vat_category', 'label': 'VAT Category', 'required': False},
    {'id': 'vat_rate', 'label': 'VAT Rate', 'required': False},
]


def _apply_column_mapping(row: Dict, column_mapping: Dict[str, str]) -> Dict:
    """
    Remap row keys using user's column mapping (Excel header -> system field id).
    Returns a new row with canonical header names expected by the rest of the service.
    """
    out: Dict = {}
    for excel_header, system_key in column_mapping.items():
        if system_key not in SYSTEM_TO_CANONICAL_HEADER:
            continue
        canonical = SYSTEM_TO_CANONICAL_HEADER[system_key]
        val = row.get(excel_header)
        out[canonical] = val  # Pass through (validation will catch missing/empty item name)
    return out


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


def _safe_str(value) -> str:
    """
    Safely convert Excel value to string.
    Handles None, NaN, float, int, and string types.
    """
    if value is None:
        return ''
    if isinstance(value, (float, int)):
        # Check for NaN
        if isinstance(value, float) and (value != value):  # NaN check
            return ''
        return str(value)
    return str(value).strip() if isinstance(value, str) else str(value)


def _parse_bool_from_row(row: Dict, possible_names: List[str], default: bool) -> bool:
    """Parse a boolean from row using any of the possible column names."""
    val = _normalize_column_name(row, possible_names)
    if val is None or (isinstance(val, str) and not val.strip()):
        return default
    s = str(val).strip().lower()
    return s in ('true', '1', 'yes', 'y', 'x')


def _safe_strip(value) -> Optional[str]:
    """
    Safely strip a value, handling None, NaN, float, int types.
    Returns None if value is empty/None/NaN, otherwise returns stripped string.
    """
    if value is None:
        return None
    if isinstance(value, (float, int)):
        # Check for NaN
        if isinstance(value, float) and (value != value):  # NaN check
            return None
        str_value = str(value).strip()
        return str_value if str_value else None
    if isinstance(value, str):
        str_value = value.strip()
        return str_value if str_value else None
    return str(value).strip() if value else None


def _is_numeric_unit_value(value) -> bool:
    """
    Return True if value looks like a number (price/conversion rate mistaken for unit name).
    Used to reject wrong column mapping (e.g. price in Base Unit column).
    """
    if value is None:
        return False
    s = (_safe_strip(value) or '').strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _sanitize_unit_label(value, default: str) -> str:
    """
    Ensure unit name is a label (bottle, piece, etc.), not a number.
    If value is missing or parses as a number, return default.
    """
    if value is None:
        return default.lower()
    s = _safe_strip(value)
    if not s or _is_numeric_unit_value(s):
        return default.lower()
    return s.lower()


def _cost_per_supplier_to_cost_per_base(
    purchase_price_per_supplier_unit: Decimal,
    wholesale_units_per_supplier: Decimal
) -> Decimal:
    """
    Convert cost per supplier unit to cost per base (wholesale) unit.
    ­1 supplier unit = wholesale_units_per_supplier base units.
    So cost_per_base = purchase_price_per_supplier_unit / wholesale_units_per_supplier.
    """
    if not wholesale_units_per_supplier or wholesale_units_per_supplier <= 0:
        return purchase_price_per_supplier_unit or Decimal('0')
    return (purchase_price_per_supplier_unit or Decimal('0')) / wholesale_units_per_supplier


def _parse_wholesale_units_per_supplier_from_row(row: Dict) -> Decimal:
    """
    Get wholesale_units_per_supplier from row.
    New template uses Supplier_Pack_Size (direct) or Conversion_To_Supplier (inverse: 1 value = wholesale per supplier).
    """
    direct_raw = _normalize_column_name(row, [
        'Wholesale_Units_per_Supplier',
        'Wholesale Units per Supplier',
        'Conversion to Supplier',
        'wholesale_units_per_supplier',
        'Supplier_Pack_Size',
    ])
    if direct_raw is not None and str(direct_raw).strip() != '':
        parsed = ExcelImportService._parse_decimal(direct_raw)
        if parsed and parsed > 0:
            return max(Decimal('0.0001'), parsed)
    # New template: Conversion_To_Supplier = supplier units per wholesale → wholesale_units_per_supplier = 1/value
    conv_raw = _normalize_column_name(row, ['Conversion_To_Supplier'])
    if conv_raw is not None and str(conv_raw).strip() != '':
        conv = ExcelImportService._parse_decimal(conv_raw)
        if conv and conv > 0:
            return max(Decimal('0.0001'), Decimal('1') / conv)
    return Decimal('1')


def _default_cost_per_base_from_row(row: Dict) -> Decimal:
    """Compute default cost per base (wholesale) unit from Excel row."""
    wholesale_price_raw = _normalize_column_name(row, [
        'Wholesale_Price_per_Wholesale_Unit',
        'Wholesale_Unit_Price',
        'Wholesale Unit Price',
        'Wholesale unit price',
        'Purchase Price (Wholesale)',
        'Cost per Wholesale Unit'
    ])
    if wholesale_price_raw is not None and str(wholesale_price_raw).strip() != '':
        return ExcelImportService._parse_decimal(wholesale_price_raw) or Decimal('0')
    purchase_raw = _normalize_column_name(row, [
        'Purchase_Price_per_Supplier_Unit',
        'Purchase Price per Supplier Unit',
        'Price_List_Last_Cost',
        'Purchase price',
        'Last Cost',
        'Last_Cost'
    ]) or '0'
    wups = _parse_wholesale_units_per_supplier_from_row(row)
    purchase_per_supplier = ExcelImportService._parse_decimal(purchase_raw)
    return _cost_per_supplier_to_cost_per_base(purchase_per_supplier, wups)


def convert_quantity_supplier_to_wholesale(
    quantity_supplier: Decimal,
    wholesale_units_per_supplier: Decimal
) -> Decimal:
    """Convert quantity in supplier units to wholesale (base) units."""
    if not wholesale_units_per_supplier or wholesale_units_per_supplier <= 0:
        return quantity_supplier
    return quantity_supplier * wholesale_units_per_supplier


def convert_quantity_wholesale_to_retail(
    quantity_wholesale: Decimal,
    pack_size: int
) -> Decimal:
    """Convert quantity in wholesale (base) units to retail units. 1 wholesale = pack_size retail."""
    pack = max(1, int(pack_size))
    return quantity_wholesale * Decimal(str(pack))


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
        # Accept multiple column name formats for item name
        item_name_fields = ['Item_Name', 'Item name*', 'Item name', 'Item Name']
        # Stock quantity is optional (defaults to 0 if missing) - no validation needed
        
        if not excel_data:
            errors.append("Excel file is empty")
            return False, errors
        
        for idx, row in enumerate(excel_data, start=2):  # Start at row 2 (header is row 1)
            # Check if at least one item name field exists and has a value
            item_name = None
            for field in item_name_fields:
                if field in row and row[field] is not None:
                    value = _safe_strip(row[field])
                    if value:
                        item_name = value
                        break
            
            if not item_name:
                # Try case-insensitive and normalized matching
                for key in row.keys():
                    normalized_key = key.replace(' ', '_').replace('-', '_').replace('*', '').lower()
                    if normalized_key in ['item_name', 'itemname']:
                        value = _safe_strip(row[key])
                        if value:
                            item_name = value
                            break
                
                if not item_name:
                    errors.append(f"Row {idx}: Missing required field 'Item name' (tried: {', '.join(item_name_fields)})")
            
            # Stock quantity is optional - no validation needed, will default to 0
        
        return len(errors) == 0, errors
    
    @staticmethod
    def import_excel_data(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        excel_data: List[Dict],
        force_mode: Optional[str] = None,
        job_id: Optional[UUID] = None,
        column_mapping: Optional[Dict[str, str]] = None
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
            column_mapping: Optional dict mapping Excel header names to system field ids
                           (e.g. {"Product Name": "item_name", "Cost": "purchase_price_per_supplier_unit"}).
                           When provided, each row is remapped before processing (Vyper-style).
        
        Returns:
            Dict with import results and statistics
        """
        # Apply column mapping if provided (user matched their Excel headers to system fields)
        if column_mapping:
            excel_data = [_apply_column_mapping(row, column_mapping) for row in excel_data]
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
                db, company_id, branch_id, user_id, excel_data, job_id=job_id
            )
        else:
            return ExcelImportService._import_non_destructive(
                db, company_id, branch_id, user_id, excel_data, job_id=job_id
            )

    @staticmethod
    def _get_items_with_real_transactions(
        db: Session,
        company_id: UUID,
        item_ids: List[UUID]
    ) -> set:
        """
        Return item_ids that have REAL transactions.

        We intentionally ignore pure OPENING_BALANCE ledger entries so that
        re-importing to correct master data is still allowed before any sales/purchases.

        Real transactions are considered:
        - Any sales invoice items
        - Any purchase invoice items
        - Any inventory_ledger entries EXCEPT transaction_type == 'OPENING_BALANCE'
        """
        if not item_ids:
            return set()

        # Import inside function to avoid circular imports at module import time
        from app.models.sale import SalesInvoice, SalesInvoiceItem
        from app.models.purchase import SupplierInvoice, SupplierInvoiceItem

        tx_item_ids: set = set()

        # Sales transactions
        sales_rows = (
            db.query(SalesInvoiceItem.item_id)
            .join(SalesInvoice, SalesInvoiceItem.sales_invoice_id == SalesInvoice.id)
            .filter(
                SalesInvoice.company_id == company_id,
                SalesInvoiceItem.item_id.in_(item_ids)
            )
            .distinct()
            .all()
        )
        tx_item_ids.update({row[0] for row in sales_rows})

        # Purchase transactions
        purchase_rows = (
            db.query(SupplierInvoiceItem.item_id)
            .join(SupplierInvoice, SupplierInvoiceItem.purchase_invoice_id == SupplierInvoice.id)
            .filter(
                SupplierInvoice.company_id == company_id,
                SupplierInvoiceItem.item_id.in_(item_ids)
            )
            .distinct()
            .all()
        )
        tx_item_ids.update({row[0] for row in purchase_rows})

        # Inventory movements (exclude opening balances)
        ledger_rows = (
            db.query(InventoryLedger.item_id)
            .filter(
                InventoryLedger.company_id == company_id,
                InventoryLedger.item_id.in_(item_ids),
                InventoryLedger.transaction_type != 'OPENING_BALANCE'
            )
            .distinct()
            .all()
        )
        tx_item_ids.update({row[0] for row in ledger_rows})

        return tx_item_ids

    @staticmethod
    def _overwrite_item_from_excel(item: Item, row: Dict):
        """
        Overwrite an existing item with Excel data (safe ONLY when item has no real transactions).

        This updates BOTH structural fields (units/pack_size) and non-structural fields.
        """
        # Reuse the same parsing logic as create for consistency
        description = _normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Generic name']) or ''
        barcode = _normalize_column_name(row, ['Barcode', 'barcode', 'BARCODE']) or ''
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY']) or ''

        supplier_unit_raw = _normalize_column_name(row, ['Supplier_Unit', 'Supplier Unit', 'supplier_unit']) or ''
        wholesale_unit_raw = _normalize_column_name(row, ['Wholesale_Unit', 'Wholesale Unit', 'wholesale_unit']) or ''
        retail_unit_raw = _normalize_column_name(row, ['Retail_Unit', 'Retail Unit', 'retail_unit']) or ''
        supplier_unit = _sanitize_unit_label(supplier_unit_raw, 'packet')
        wholesale_unit = _sanitize_unit_label(wholesale_unit_raw, 'packet')
        retail_unit = _sanitize_unit_label(retail_unit_raw, 'tablet')
        pack_size_raw = _normalize_column_name(row, ['Pack_Size', 'Pack Size', 'pack_size', 'Conversion Rate (n) (x = ny)', 'Conversion_To_Retail']) or '1'
        pack_size = int(ExcelImportService._parse_decimal(pack_size_raw)) if pack_size_raw else 1
        pack_size = max(1, int(pack_size))

        can_break_bulk_raw = _normalize_column_name(row, ['Can_Break_Bulk', 'Can Break Bulk', 'can_break_bulk'])
        can_break_bulk = str(can_break_bulk_raw).lower() in ['true', '1', 'yes', 'y'] if can_break_bulk_raw else True

        vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category', 'vat_category']) or 'ZERO_RATED'
        vat_category = (_safe_strip(vat_category_raw) or 'ZERO_RATED').upper()
        vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'vat_rate', 'Tax Rate']) or '0'
        vat_rate = ExcelImportService._parse_decimal(vat_rate_raw)
        if vat_category == 'STANDARD_RATED' and vat_rate == 0:
            vat_rate = Decimal('16.00')
        elif vat_category == 'ZERO_RATED':
            vat_rate = Decimal('0.00')

        # Apply updates (master data only; prices/cost come from inventory_ledger)
        item.description = _safe_strip(description)
        item.barcode = _safe_strip(barcode)
        item.category = _safe_strip(category)

        item.supplier_unit = supplier_unit
        item.wholesale_unit = wholesale_unit
        item.retail_unit = retail_unit
        item.pack_size = pack_size
        item.can_break_bulk = can_break_bulk
        item.wholesale_units_per_supplier = _parse_wholesale_units_per_supplier_from_row(row)

        # Base = wholesale (reference unit); never use a numeric value
        item.base_unit = item.wholesale_unit or 'piece'

        # VAT (vat_category + vat_rate only)
        item.vat_category = vat_category
        item.vat_rate = vat_rate
        
        # Tracking flags
        track_expiry_raw = _normalize_column_name(row, ['Track_Expiry', 'Track Expiry', 'track_expiry'])
        if track_expiry_raw is not None:
            item.track_expiry = _parse_bool_from_row(row, ['Track_Expiry', 'Track Expiry', 'track_expiry'], False)
        is_controlled_raw = _normalize_column_name(row, ['Is_Controlled', 'Is Controlled', 'is_controlled'])
        if is_controlled_raw is not None:
            item.is_controlled = _parse_bool_from_row(row, ['Is_Controlled', 'Is Controlled', 'is_controlled'], False)
        is_cold_chain_raw = _normalize_column_name(row, ['Is_Cold_Chain', 'Is Cold Chain', 'is_cold_chain'])
        if is_cold_chain_raw is not None:
            item.is_cold_chain = _parse_bool_from_row(row, ['Is_Cold_Chain', 'Is Cold Chain', 'is_cold_chain'], False)
    
    @staticmethod
    def _import_authoritative(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        excel_data: List[Dict],
        job_id: Optional[UUID] = None
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
            import time
            start_time = time.time()
            
            # Delete existing opening balances for this branch (only Excel-imported ones)
            # In authoritative mode, we can delete opening balances created from Excel
            logger.info("Deleting existing opening balances...")
            deleted_count = db.query(InventoryLedger).filter(
                and_(
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.transaction_type == 'OPENING_BALANCE',
                    InventoryLedger.reference_type == 'OPENING_BALANCE'
                )
            ).delete(synchronize_session=False)
            logger.info(f"Deleted {deleted_count} existing opening balances")
            
            # Process in batches using OPTIMIZED bulk operations
            # Increased batch size for better performance (500 items per batch)
            batch_size = 500  # Increased from 100 for better performance
            total_rows = len(excel_data)
            total_batches = (total_rows + batch_size - 1) // batch_size
            
            logger.info(f"Starting OPTIMIZED import of {total_rows} items in {total_batches} batches (batch size: {batch_size})")
            
            for batch_start in range(0, total_rows, batch_size):
                batch_num = batch_start//batch_size + 1
                batch_end = min(batch_start + batch_size, total_rows)
                batch = excel_data[batch_start:batch_end]
                batch_start_time = time.time()
                
                # Calculate progress percentage
                progress_pct = (batch_start / total_rows) * 100
                elapsed_time = batch_start_time - start_time
                items_per_sec = batch_start / elapsed_time if elapsed_time > 0 else 0
                estimated_remaining = (total_rows - batch_start) / items_per_sec if items_per_sec > 0 else 0
                
                logger.info(
                    f"Processing batch {batch_num}/{total_batches} "
                    f"(rows {batch_start+1}-{batch_end}, {progress_pct:.1f}% complete, "
                    f"{items_per_sec:.1f} items/sec, ~{estimated_remaining/60:.1f} min remaining)"
                )
                
                # OPTIMIZED: Process batch using bulk operations
                try:
                    batch_result = ExcelImportService._process_batch_bulk(
                        db, company_id, branch_id, user_id, batch, batch_start
                    )
                    stats['items_created'] += batch_result.get('items_created', 0)
                    stats['items_updated'] += batch_result.get('items_updated', 0)
                    stats['opening_balances_created'] += batch_result.get('opening_balances_created', 0)
                    stats['suppliers_created'] += batch_result.get('suppliers_created', 0)
                    stats['errors'].extend(batch_result.get('errors', []))
                except Exception as e:
                    logger.error(f"Batch {batch_num} bulk processing failed: {str(e)}", exc_info=True)
                    # Rollback and try row-by-row as fallback
                    try:
                        db.rollback()
                    except:
                        pass
                    logger.info(f"Falling back to row-by-row processing for batch {batch_num}")
                    for batch_idx, row in enumerate(batch):
                        row_number = batch_start + batch_idx + 2
                        try:
                            result = ExcelImportService._process_excel_row_authoritative(
                                db, company_id, branch_id, user_id, row
                            )
                            stats['items_created'] += result.get('item_created', 0)
                            stats['items_updated'] += result.get('item_updated', 0)
                            stats['opening_balances_created'] += result.get('opening_balance_created', 0)
                            stats['suppliers_created'] += result.get('supplier_created', 0)
                        except Exception as row_error:
                            try:
                                db.rollback()
                            except:
                                pass
                            item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name']) or 'Unknown'
                            error_msg = f"Error processing row {row_number} for '{item_name}': {str(row_error)}"
                            logger.error(error_msg)
                            stats['errors'].append(error_msg)
                
                # Commit batch to avoid long transaction and show progress
                try:
                    db.commit()
                    batch_time = time.time() - batch_start_time
                    total_time = time.time() - start_time
                    progress_pct = (batch_end / total_rows) * 100
                    logger.info(
                        f"Batch {batch_num}/{total_batches} committed successfully "
                        f"({batch_time:.1f}s, {progress_pct:.1f}% complete, "
                        f"{total_time/60:.1f} min total elapsed)"
                    )
                    
                    # Update job progress if job_id provided (use raw SQL so it persists after rollbacks)
                    if job_id:
                        try:
                            db.execute(
                                text("""
                                    UPDATE import_jobs
                                    SET processed_rows = :processed_rows,
                                        last_batch = :last_batch,
                                        updated_at = now()
                                    WHERE id = :id
                                """),
                                {
                                    "processed_rows": batch_end,
                                    "last_batch": batch_num,
                                    "id": job_id,
                                },
                            )
                            db.commit()
                            logger.info(f"Job {job_id} progress updated: {batch_end}/{total_rows} (batch {batch_num})")
                        except Exception as progress_error:
                            logger.warning(f"Could not update job progress: {progress_error}")
                            try:
                                db.rollback()
                            except Exception:
                                pass
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error committing batch {batch_num}: {str(e)}")
                    raise
            
            total_time = time.time() - start_time
            logger.info(
                f"AUTHORITATIVE import completed in {total_time/60:.1f} minutes: "
                f"{stats['items_created']} created, {stats['items_updated']} updated, "
                f"{stats['opening_balances_created']} opening balances, "
                f"{len(stats['errors'])} errors"
            )
            return {
                'mode': 'AUTHORITATIVE',
                'success': True,
                'stats': stats
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"AUTHORITATIVE import failed: {str(e)}")
            # Return partial results if we processed some items
            return {
                'mode': 'AUTHORITATIVE',
                'success': False,
                'stats': stats,
                'error': str(e)
            }
    
    @staticmethod
    def _import_non_destructive(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        excel_data: List[Dict],
        job_id: Optional[UUID] = None
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
            # Process in batches to avoid timeout and transaction issues
            batch_size = 100
            total_rows = len(excel_data)
            
            for batch_start in range(0, total_rows, batch_size):
                batch_end = min(batch_start + batch_size, total_rows)
                batch = excel_data[batch_start:batch_end]
                
                logger.info(f"Processing batch {batch_start//batch_size + 1}/{(total_rows + batch_size - 1)//batch_size} (rows {batch_start+1}-{batch_end})")
                
                # Process each row in batch
                for batch_idx, row in enumerate(batch):
                    row_number = batch_start + batch_idx + 2  # +2 because Excel rows start at 1, and row 1 is header
                    try:
                        result = ExcelImportService._process_excel_row_non_destructive(
                            db, company_id, branch_id, user_id, row
                        )
                        stats['items_created'] += result.get('item_created', 0)
                        stats['items_skipped'] += result.get('item_skipped', 0)
                        stats['prices_updated'] += result.get('price_updated', 0)
                        stats['suppliers_created'] += result.get('supplier_created', 0)
                    except Exception as e:
                        # Rollback this row's transaction, but continue with next row
                        db.rollback()
                        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name']) or 'Unknown'
                        error_msg = f"Error processing row {row_number} for '{item_name}': {str(e)}"
                        logger.error(error_msg, exc_info=True)
                        stats['errors'].append(error_msg)
                        # Continue processing next row
                        continue
                
                # Commit batch to avoid long transaction
                try:
                    db.commit()
                    logger.info(f"Batch {batch_start//batch_size + 1} committed successfully")
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error committing batch {batch_start//batch_size + 1}: {str(e)}")
                    raise
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
        
        # Use normalize_column_name to handle various column name formats
        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name']) or ''
        item_name = _safe_strip(item_name) or ''
        if not item_name:
            return result
        
        try:
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
                # Flush to get item.id before creating units
                db.flush()
                result['item_created'] = 1
            else:
                # Replace/Update existing item depending on transaction history
                has_real_tx = item.id in ExcelImportService._get_items_with_real_transactions(
                    db, company_id, [item.id]
                )
                if not has_real_tx:
                    # Safe to fully overwrite (master data only; no item_units)
                    ExcelImportService._overwrite_item_from_excel(item, row)
                    db.query(ItemPricing).filter(ItemPricing.item_id == item.id).delete(synchronize_session=False)
                else:
                    # Only update non-structural fields (VAT/category)
                    ExcelImportService._update_item_from_excel(db, item, row)
                result['item_updated'] = 1
            
            # Create/update pricing (ItemPricing row only; no prices on item)
            try:
                ExcelImportService._process_item_pricing(db, item, company_id, row)
            except Exception as pricing_error:
                # If pricing fails, log but continue
                logger.warning(f"Could not process pricing for item '{item_name}': {pricing_error}")
                # Don't rollback here - item and units are already saved
            
            # Create supplier if needed and set default_supplier_id
            supplier_id = None
            try:
                supplier_id = ExcelImportService._ensure_supplier(db, company_id, row)
                if supplier_id:
                    result['supplier_created'] = 1
            except Exception as supplier_error:
                logger.warning(f"Could not create supplier for item '{item_name}': {supplier_error}")
            
            # Compute default cost per base (same logic as opening balance) and set item defaults
            wholesale_price_raw = _normalize_column_name(row, [
                'Wholesale_Price_per_Wholesale_Unit',
                'Wholesale_Unit_Price',
                'Wholesale Unit Price',
                'Wholesale unit price',
                'Purchase Price (Wholesale)',
                'Cost per Wholesale Unit'
            ])
            if wholesale_price_raw is not None and str(wholesale_price_raw).strip() != '':
                default_cost_per_base = ExcelImportService._parse_decimal(wholesale_price_raw) or Decimal('0')
            else:
                purchase_raw = _normalize_column_name(row, [
                    'Purchase_Price_per_Supplier_Unit',
                    'Purchase Price per Supplier Unit',
                    'Price_List_Last_Cost',
                    'Purchase price',
                    'Last Cost',
                    'Last_Cost'
                ]) or '0'
                purchase_per_supplier = ExcelImportService._parse_decimal(purchase_raw)
                default_cost_per_base = _cost_per_supplier_to_cost_per_base(
                    purchase_per_supplier,
                    getattr(item, 'wholesale_units_per_supplier', None) or Decimal('1')
                )
            item.default_cost_per_base = default_cost_per_base
            item.default_supplier_id = supplier_id

            # Create opening balance: unit_cost from Excel (purchase price) converted to cost per base
            try:
                has_real_tx_stock = item.id in ExcelImportService._get_items_with_real_transactions(
                    db, company_id, [item.id]
                )
                if has_real_tx_stock:
                    return result
                stock_qty_raw = _normalize_column_name(row, [
                    'Current_Stock_Quantity',
                    'Current stock quantity',
                    'Current Stock Quantity',
                    'Current stock',
                    'Stock Quantity',
                    'stock quantity'
                ]) or '0'
                stock_qty = ExcelImportService._parse_quantity(stock_qty_raw)
                ExcelImportService._create_opening_balance(
                    db, company_id, branch_id, item.id, stock_qty, user_id,
                    unit_cost_per_base=default_cost_per_base
                )
                if stock_qty > 0:
                    result['opening_balance_created'] = 1
            except Exception as stock_error:
                logger.warning(f"Could not create opening balance for item '{item_name}': {stock_error}")
                # Don't fail the entire row if stock creation fails
        
        except Exception as e:
            # If item creation/update fails, rollback and re-raise
            db.rollback()
            raise
        
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
        item_name = _safe_strip(item_name) or ''
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
            item = ExcelImportService._create_item_from_excel(db, company_id, row)
            db.flush()
            result['item_created'] = 1
            ExcelImportService._process_item_pricing(db, item, company_id, row)
        else:
            has_real_tx = item.id in ExcelImportService._get_items_with_real_transactions(
                db, company_id, [item.id]
            )
            if not has_real_tx:
                ExcelImportService._overwrite_item_from_excel(item, row)
                db.query(ItemPricing).filter(ItemPricing.item_id == item.id).delete(synchronize_session=False)
                ExcelImportService._process_item_pricing(db, item, company_id, row)
                result['price_updated'] = 1
            else:
                result['item_skipped'] = 1
                if ExcelImportService._update_missing_prices_only(db, item, company_id, row):
                    result['price_updated'] = 1
        
        # Create supplier if missing (non-destructive) and set item defaults
        supplier_id = ExcelImportService._ensure_supplier(db, company_id, row)
        if supplier_id:
            result['supplier_created'] = 1
        item.default_supplier_id = supplier_id
        item.default_cost_per_base = _default_cost_per_base_from_row(row)
        
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
        """Create a new item from Excel row with 3-tier UNIT system"""
        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name']) or ''
        description = _normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Generic name']) or ''
        item_code = _normalize_column_name(row, ['Item_Code', 'Item Code', 'Item code', 'SKU', 'sku']) or ''
        barcode = _normalize_column_name(row, ['Barcode', 'barcode', 'BARCODE']) or ''
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY']) or ''
        
        # 3-TIER UNIT SYSTEM (from Excel template); sanitize so we never store a number as unit name
        supplier_unit_raw = _normalize_column_name(row, ['Supplier_Unit', 'Supplier Unit', 'supplier_unit']) or ''
        wholesale_unit_raw = _normalize_column_name(row, ['Wholesale_Unit', 'Wholesale Unit', 'wholesale_unit']) or ''
        retail_unit_raw = _normalize_column_name(row, ['Retail_Unit', 'Retail Unit', 'retail_unit']) or ''
        supplier_unit = _sanitize_unit_label(supplier_unit_raw, 'packet')
        wholesale_unit = _sanitize_unit_label(wholesale_unit_raw, 'packet')
        retail_unit = _sanitize_unit_label(retail_unit_raw, 'tablet')
        pack_size_raw = _normalize_column_name(row, ['Pack_Size', 'Pack Size', 'pack_size', 'Conversion Rate (n) (x = ny)', 'Conversion_To_Retail']) or '1'
        pack_size = max(1, int(ExcelImportService._parse_decimal(pack_size_raw)) if pack_size_raw else 1)
        wholesale_units_per_supplier = _parse_wholesale_units_per_supplier_from_row(row)
        can_break_bulk_raw = _normalize_column_name(row, ['Can_Break_Bulk', 'Can Break Bulk', 'can_break_bulk'])
        can_break_bulk = str(can_break_bulk_raw).lower() in ['true', '1', 'yes', 'y'] if can_break_bulk_raw else True
        
        # VAT CLASSIFICATION
        vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category', 'vat_category']) or 'ZERO_RATED'
        vat_category = _safe_strip(vat_category_raw) or 'ZERO_RATED'
        vat_category = vat_category.upper() if vat_category else 'ZERO_RATED'
        vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'vat_rate', 'Tax Rate']) or '0'
        vat_rate = ExcelImportService._parse_decimal(vat_rate_raw)
        if vat_category == 'STANDARD_RATED' and vat_rate == 0:
            vat_rate = Decimal('16.00')
        elif vat_category == 'ZERO_RATED':
            vat_rate = Decimal('0.00')
        
        # Base = wholesale (reference unit). Prices/cost come from inventory_ledger only.
        base_unit = wholesale_unit
        
        item = Item(
            company_id=company_id,
            name=_safe_strip(item_name) or '',
            description=_safe_strip(description),
            sku=_safe_strip(item_code),
            barcode=_safe_strip(barcode),
            category=_safe_strip(category),
            base_unit=_safe_strip(base_unit) or 'piece',
            supplier_unit=_safe_strip(supplier_unit) or 'packet',
            wholesale_unit=_safe_strip(wholesale_unit) or 'packet',
            retail_unit=_safe_strip(retail_unit) or 'tablet',
            pack_size=pack_size,
            wholesale_units_per_supplier=wholesale_units_per_supplier,
            can_break_bulk=can_break_bulk,
            vat_category=vat_category,
            vat_rate=vat_rate,
            track_expiry=_parse_bool_from_row(row, ['Track_Expiry', 'Track Expiry', 'track_expiry'], False),
            is_controlled=_parse_bool_from_row(row, ['Is_Controlled', 'Is Controlled', 'is_controlled'], False),
            is_cold_chain=_parse_bool_from_row(row, ['Is_Cold_Chain', 'Is Cold Chain', 'is_cold_chain'], False),
            is_active=True
        )
        db.add(item)
        db.flush()  # Get ID
        return item
    
    @staticmethod
    def _update_item_from_excel(db: Session, item: Item, row: Dict):
        """Update existing item from Excel (AUTHORITATIVE mode only). Master data only; prices from ledger."""
        # Only update non-structural fields; no price fields (cost/price from inventory_ledger)
        description = _normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Generic name'])
        if description:
            item.description = _safe_strip(description)
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY'])
        if category:
            item.category = _safe_strip(category)
        
        # Update VAT (vat_category + vat_rate only)
        vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category'])
        if vat_category_raw:
            vat_cat = _safe_strip(vat_category_raw) or 'ZERO_RATED'
            item.vat_category = vat_cat.upper() if vat_cat else 'ZERO_RATED'
        
        vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'Tax Rate'])
        if vat_rate_raw:
            item.vat_rate = ExcelImportService._parse_decimal(vat_rate_raw)
    
    @staticmethod
    def _process_item_pricing(
        db: Session,
        item: Item,
        company_id: UUID,
        row: Dict
    ):
        """Ensure ItemPricing row exists for item. Cost/price come from inventory_ledger only; do not write to item."""
        try:
            from sqlalchemy import text
            existing = db.execute(
                text("SELECT id FROM item_pricing WHERE item_id = :item_id"),
                {"item_id": item.id}
            ).first()
            if not existing:
                # Default: recommended markup 30%, minimum margin 15%
                pricing = ItemPricing(
                    item_id=item.id,
                    markup_percent=Decimal("30.00"),
                    min_margin_percent=Decimal("15.00"),
                    rounding_rule=None
                )
                db.add(pricing)
                db.flush()
        except Exception as e:
            logger.warning(f"Could not ensure ItemPricing for item {item.id}: {str(e)}")
    
    @staticmethod
    def _update_missing_prices_only(
        db: Session,
        item: Item,
        company_id: UUID,
        row: Dict
    ) -> bool:
        """NON_DESTRUCTIVE mode: no longer updates item price fields (cost/price from ledger only)."""
        return False
    
    @staticmethod
    def _ensure_supplier(
        db: Session,
        company_id: UUID,
        row: Dict
    ) -> Optional[UUID]:
        """Ensure supplier exists, return supplier ID"""
        supplier_name_raw = _normalize_column_name(row, ['Supplier', 'supplier', 'SUPPLIER', 'Supplier Name', 'supplier name']) or ''
        supplier_name = _safe_strip(supplier_name_raw) or ''
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
        user_id: UUID,
        unit_cost_per_base: Optional[Decimal] = None
    ):
        """Create opening balance entry in inventory_ledger. unit_cost_per_base = cost per base (wholesale) unit; from Excel (row) only."""
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
            return
        
        unit_cost = (unit_cost_per_base if unit_cost_per_base is not None else Decimal('0'))
        if existing:
            existing.quantity_delta = quantity
            existing.unit_cost = unit_cost
            existing.total_cost = quantity * unit_cost
        else:
            ledger_entry = InventoryLedger(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                transaction_type='OPENING_BALANCE',
                reference_type='OPENING_BALANCE',
                quantity_delta=quantity,
                unit_cost=unit_cost,
                total_cost=quantity * unit_cost,
                created_by=user_id
            )
            db.add(ledger_entry)
    
    @staticmethod
    def _process_batch_bulk(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        batch: List[Dict],
        batch_start: int
    ) -> Dict:
        """
        Process a batch of Excel rows using BULK operations (50-100x faster)
        
        Strategy:
        1. Extract all item names and supplier names from batch
        2. Bulk fetch existing items and suppliers (2 queries instead of N queries)
        3. Prepare all items/units/pricing/stock in memory
        4. Bulk insert everything at once
        """
        from uuid import uuid4
        
        result = {
            'items_created': 0,
            'items_updated': 0,
            'opening_balances_created': 0,
            'suppliers_created': 0,
            'errors': []
        }
        
        # Step 1: Extract item names and supplier names from batch
        item_names = []
        supplier_names = set()
        valid_rows = []
        
        for row in batch:
            item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name']) or ''
            item_name = _safe_strip(item_name)
            if item_name:
                item_names.append(item_name)
                valid_rows.append((item_name, row))
            
            supplier_name = _normalize_column_name(row, ['Supplier', 'Supplier Name', 'supplier']) or ''
            supplier_name = _safe_strip(supplier_name)
            if supplier_name:
                supplier_names.add(supplier_name)
        
        if not item_names:
            return result
        
        # Step 2: Bulk fetch existing items (ONE query instead of N queries)
        existing_items = {
            item.name.lower(): item
            for item in db.query(Item).filter(
                and_(
                    Item.company_id == company_id,
                    Item.name.in_(item_names)
                )
            ).all()
        }
        
        # Step 3: Bulk fetch existing suppliers (ONE query)
        existing_suppliers = {
            supplier.name.lower(): supplier
            for supplier in db.query(Supplier).filter(
                and_(
                    Supplier.company_id == company_id,
                    Supplier.name.in_(list(supplier_names))
                )
            ).all()
        }
        
        # Step 4: Prepare items for bulk insert/update
        items_to_insert = []
        update_mappings_replaceable = []  # full overwrite (no real transactions)
        update_mappings_locked = []       # safe updates only (has transactions)
        replaceable_item_ids = set()
        pricing_to_insert = []
        pricing_to_update = []
        opening_balances = []
        suppliers_to_create = []
        item_name_to_row = {}  # For later reference
        
        for item_name, row in valid_rows:
            item_name_lower = item_name.lower()
            item_name_to_row[item_name_lower] = (item_name, row)
            
            if item_name_lower in existing_items:
                # Existing item: decide replace vs safe update based on real transactions
                item = existing_items[item_name_lower]
                has_real_tx = item.id in ExcelImportService._get_items_with_real_transactions(
                    db, company_id, [item.id]
                )
                if not has_real_tx:
                    replaceable_item_ids.add(item.id)
                    # Full overwrite mapping (includes structural fields)
                    item_dict = ExcelImportService._create_item_dict_for_bulk(company_id, row, item_name)
                    item_dict['id'] = item.id
                    update_mappings_replaceable.append(item_dict)
                else:
                    # Safe update mapping only (do NOT touch unit structure)
                    safe = {'id': item.id}
                    description = _normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Generic name'])
                    if description:
                        safe['description'] = _safe_strip(description)
                    category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY'])
                    if category:
                        safe['category'] = _safe_strip(category)
                    barcode = _normalize_column_name(row, ['Barcode', 'barcode', 'BARCODE'])
                    if barcode:
                        safe['barcode'] = _safe_strip(barcode)
                    vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category', 'vat_category'])
                    if vat_category_raw:
                        vat_cat = (_safe_strip(vat_category_raw) or 'ZERO_RATED').upper()
                        safe['vat_category'] = vat_cat
                    vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'vat_rate', 'Tax Rate'])
                    if vat_rate_raw:
                        safe['vat_rate'] = ExcelImportService._parse_decimal(vat_rate_raw)
                    track_expiry_raw = _normalize_column_name(row, ['Track_Expiry', 'Track Expiry', 'track_expiry'])
                    if track_expiry_raw is not None:
                        safe['track_expiry'] = _parse_bool_from_row(row, ['Track_Expiry', 'Track Expiry', 'track_expiry'], False)
                    is_controlled_raw = _normalize_column_name(row, ['Is_Controlled', 'Is Controlled', 'is_controlled'])
                    if is_controlled_raw is not None:
                        safe['is_controlled'] = _parse_bool_from_row(row, ['Is_Controlled', 'Is Controlled', 'is_controlled'], False)
                    is_cold_chain_raw = _normalize_column_name(row, ['Is_Cold_Chain', 'Is Cold Chain', 'is_cold_chain'])
                    if is_cold_chain_raw is not None:
                        safe['is_cold_chain'] = _parse_bool_from_row(row, ['Is_Cold_Chain', 'Is Cold Chain', 'is_cold_chain'], False)
                    update_mappings_locked.append(safe)
            else:
                # Prepare new item
                item_dict = ExcelImportService._create_item_dict_for_bulk(company_id, row, item_name)
                items_to_insert.append(item_dict)
        
        # Step 4b: Build supplier name -> id (existing + to-create) and add default_supplier_id to item dicts
        supplier_name_to_id = {n.lower(): s.id for n, s in existing_suppliers.items()}
        supplier_name_to_id.update({s['name'].lower(): s['id'] for s in suppliers_to_create})
        for item_dict in items_to_insert + update_mappings_replaceable:
            name_lower = (item_dict.get('name') or '').lower()
            (_, row) = item_name_to_row.get(name_lower, (None, {}))
            supplier_name = _safe_strip(_normalize_column_name(row, ['Supplier', 'supplier', 'SUPPLIER', 'Supplier Name', 'supplier name']) or '')
            item_dict['default_supplier_id'] = supplier_name_to_id.get(supplier_name.lower()) if supplier_name else None
        
        # Step 5: Bulk insert new items
        if items_to_insert:
            db.bulk_insert_mappings(Item, items_to_insert)
            db.flush()
            result['items_created'] = len(items_to_insert)
        
        # Step 6: Bulk update existing items
        updated_count = 0
        if update_mappings_replaceable:
            db.bulk_update_mappings(Item, update_mappings_replaceable)
            updated_count += len(update_mappings_replaceable)
        if update_mappings_locked:
            db.bulk_update_mappings(Item, update_mappings_locked)
            updated_count += len(update_mappings_locked)
        if updated_count:
            db.flush()
            result['items_updated'] = updated_count
        
        # Step 7: Fetch all items (new + updated) to get IDs for units/pricing
        all_item_names = [item['name'] for item in items_to_insert] + [name for name, _ in valid_rows if name.lower() in existing_items]
        all_items_map = {
            item.name.lower(): item
            for item in db.query(Item).filter(
                and_(
                    Item.company_id == company_id,
                    Item.name.in_(all_item_names)
                )
            ).all()
        }

        # If replaceable existing items, clear their ItemPricing only (no item_units)
        if replaceable_item_ids:
            db.query(ItemPricing).filter(ItemPricing.item_id.in_(list(replaceable_item_ids))).delete(synchronize_session=False)
            db.flush()
        
        # Step 8: Prepare pricing and opening balances (no item_units)
        for item_name_lower, (item_name, row) in item_name_to_row.items():
            if item_name_lower not in all_items_map:
                continue
            
            item = all_items_map[item_name_lower]
            locked_ids = ExcelImportService._get_items_with_real_transactions(db, company_id, [item.id])
            is_locked = item.id in locked_ids
            
            # Prepare pricing
            try:
                pricing_dict = ExcelImportService._prepare_pricing_for_bulk(item, row)
                existing_pricing = db.query(ItemPricing).filter(ItemPricing.item_id == item.id).first()
                if existing_pricing:
                    # Update using raw SQL to avoid SQLAlchemy issues
                    db.execute(
                        text("UPDATE item_pricing SET markup_percent = :markup WHERE item_id = :item_id"),
                        {"markup": pricing_dict.get('markup_percent'), "item_id": item.id}
                    )
                else:
                    pricing_dict['item_id'] = item.id
                    pricing_to_insert.append(pricing_dict)
            except Exception as e:
                logger.warning(f"Could not prepare pricing for {item_name}: {e}")
            
            # Prepare opening balance: unit_cost from row (purchase price → cost per base)
            try:
                if is_locked:
                    continue
                stock_qty = ExcelImportService._parse_quantity(
                    _normalize_column_name(row, [
                        'Current_Stock_Quantity',
                        'Current stock quantity',
                        'Current Stock Quantity',
                        'Current stock',
                        'Stock Quantity',
                        'stock quantity'
                    ]) or '0'
                )
                if stock_qty > 0:
                    wholesale_price_raw = _normalize_column_name(row, [
                        'Wholesale_Price_per_Wholesale_Unit',
                        'Wholesale_Unit_Price',
                        'Wholesale Unit Price',
                        'Wholesale unit price',
                        'Purchase Price (Wholesale)',
                        'Cost per Wholesale Unit'
                    ])
                    if wholesale_price_raw is not None and str(wholesale_price_raw).strip() != '':
                        unit_cost_per_base = ExcelImportService._parse_decimal(wholesale_price_raw) or Decimal('0')
                    else:
                        purchase_raw = _normalize_column_name(row, [
                            'Purchase_Price_per_Supplier_Unit',
                            'Purchase Price per Supplier Unit',
                            'Price_List_Last_Cost',
                            'Last Cost',
                            'Purchase price'
                        ]) or '0'
                        purchase_per_supplier = ExcelImportService._parse_decimal(purchase_raw)
                        wups = getattr(item, 'wholesale_units_per_supplier', None) or Decimal('1')
                        unit_cost_per_base = _cost_per_supplier_to_cost_per_base(purchase_per_supplier, wups)
                    opening_balances.append({
                        'id': uuid4(),
                        'company_id': company_id,
                        'branch_id': branch_id,
                        'item_id': item.id,
                        'transaction_type': 'OPENING_BALANCE',
                        'reference_type': 'OPENING_BALANCE',
                        'quantity_delta': stock_qty,
                        'unit_cost': unit_cost_per_base,
                        'total_cost': stock_qty * unit_cost_per_base,
                        'created_by': user_id
                    })
            except Exception as e:
                logger.warning(f"Could not prepare opening balance for {item_name}: {e}")
            
            # Prepare suppliers
            supplier_name = _normalize_column_name(row, ['Supplier', 'Supplier Name', 'supplier']) or ''
            supplier_name = _safe_strip(supplier_name)
            if supplier_name and supplier_name.lower() not in existing_suppliers:
                # Check if already in suppliers_to_create
                if not any(s['name'].lower() == supplier_name.lower() for s in suppliers_to_create):
                    suppliers_to_create.append({
                        'id': uuid4(),
                        'company_id': company_id,
                        'name': supplier_name,
                        'is_active': True
                    })
        
        # Step 9: Bulk insert/update pricing
        if pricing_to_insert:
            try:
                db.bulk_insert_mappings(ItemPricing, pricing_to_insert)
                logger.info(f"Bulk inserted {len(pricing_to_insert)} pricing records")
            except Exception as e:
                logger.warning(f"Some pricing failed bulk insert: {e}")
        
        # Step 10: Bulk insert suppliers
        if suppliers_to_create:
            try:
                db.bulk_insert_mappings(Supplier, suppliers_to_create)
                db.flush()
                result['suppliers_created'] = len(suppliers_to_create)
                logger.info(f"Bulk inserted {len(suppliers_to_create)} suppliers")
            except Exception as e:
                logger.warning(f"Some suppliers failed bulk insert: {e}")
        
        # Step 11: Bulk insert opening balances
        if opening_balances:
            try:
                db.bulk_insert_mappings(InventoryLedger, opening_balances)
                result['opening_balances_created'] = len(opening_balances)
                logger.info(f"Bulk inserted {len(opening_balances)} opening balances")
            except Exception as e:
                logger.warning(f"Some opening balances failed bulk insert: {e}")
        
        return result
    
    @staticmethod
    def _create_item_dict_for_bulk(company_id: UUID, row: Dict, item_name: str) -> Dict:
        """Create item dictionary for bulk insert. Master data only; no price fields (from ledger)."""
        from uuid import uuid4
        return {
            'id': uuid4(),
            'company_id': company_id,
            'name': item_name,
            'description': _safe_strip(_normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Description']) or ''),
            'sku': _safe_strip(_normalize_column_name(row, ['Item_Code', 'SKU', 'Item Code', 'sku']) or ''),
            'barcode': _safe_strip(_normalize_column_name(row, ['Barcode', 'barcode']) or ''),
            'category': _safe_strip(_normalize_column_name(row, ['Category', 'category']) or ''),
            'base_unit': _sanitize_unit_label(_normalize_column_name(row, ['Wholesale_Unit', 'Wholesale Unit', 'Base_Unit', 'Base Unit', 'Base Unit (x)']), 'piece'),
            'vat_rate': ExcelImportService._parse_decimal(_normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'Tax Rate']) or '0'),
            'vat_category': _safe_strip(_normalize_column_name(row, ['VAT_Category', 'VAT Category']) or 'ZERO_RATED'),
            'is_active': True,
            'supplier_unit': _sanitize_unit_label(_normalize_column_name(row, ['Supplier_Unit', 'Supplier Unit']), 'piece'),
            'wholesale_unit': _sanitize_unit_label(_normalize_column_name(row, ['Wholesale_Unit', 'Wholesale Unit']), 'piece'),
            'retail_unit': _sanitize_unit_label(_normalize_column_name(row, ['Retail_Unit', 'Retail Unit']), 'tablet'),
            'pack_size': max(1, int(ExcelImportService._parse_decimal(_normalize_column_name(row, ['Pack_Size', 'Pack Size', 'Conversion_To_Retail']) or '1'))),
            'wholesale_units_per_supplier': _parse_wholesale_units_per_supplier_from_row(row),
            'can_break_bulk': True,
            'track_expiry': _parse_bool_from_row(row, ['Track_Expiry', 'Track Expiry', 'track_expiry'], False),
            'is_controlled': _parse_bool_from_row(row, ['Is_Controlled', 'Is Controlled', 'is_controlled'], False),
            'is_cold_chain': _parse_bool_from_row(row, ['Is_Cold_Chain', 'Is Cold Chain', 'is_cold_chain'], False),
            'default_cost_per_base': _default_cost_per_base_from_row(row),
        }
    
    @staticmethod
    def _prepare_pricing_for_bulk(item: Item, row: Dict) -> Dict:
        """Prepare pricing dictionary for bulk insert"""
        from uuid import uuid4
        # Only markup_percent goes to ItemPricing
        # 3-tier prices are already on Item
        return {
            'id': uuid4(),
            'markup_percent': None,
            'min_margin_percent': None,
            'rounding_rule': None
        }
    
    @staticmethod
    def _parse_quantity(value) -> int:
        """Parse quantity from Excel (handles strings, floats, NaN, etc.)"""
        if value is None:
            return 0
        if isinstance(value, (float, int)):
            # Check for NaN
            if isinstance(value, float) and (value != value):  # NaN check
                return 0
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() in ['nan', 'none', 'null', '']:
                return 0
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return 0
        return 0
    
    @staticmethod
    def _parse_decimal(value) -> Decimal:
        """Parse value to Decimal, handling None, NaN, float, int, and string types"""
        if value is None:
            return Decimal('0')
        if isinstance(value, (float, int)):
            # Check for NaN
            if isinstance(value, float) and (value != value):  # NaN check
                return Decimal('0')
            return Decimal(str(value))
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() in ['nan', 'none', 'null', '']:
                return Decimal('0')
            try:
                return Decimal(value)
            except (ValueError, TypeError):
                return Decimal('0')
        return Decimal('0')
