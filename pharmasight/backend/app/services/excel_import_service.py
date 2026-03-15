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
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text

from app.models import (
    Item, ItemPricing, InventoryLedger,
    Supplier, Company, Branch
)
from app.services.snapshot_service import SnapshotService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.items_service import generate_sku_for_company, get_next_sku_number_for_bulk
from app.utils.vat import vat_rate_to_percent

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
    'opening_batch_number': 'Opening_Batch_Number',
    'opening_expiry_date': 'Opening_Expiry_Date',
    'wholesale_unit_price': 'Wholesale_Unit_Price',
    'supplier': 'Supplier',
    'vat_category': 'VAT_Category',
    'vat_rate': 'VAT_Rate',
    'base_unit': 'Base_Unit',
    'product_category': 'Product_Category',
    'pricing_tier': 'Pricing_Tier',
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
    # 3-tier unit names + conversion numbers
    {'id': 'supplier_unit', 'label': 'Supplier unit name (e.g. carton, crate, dozen)', 'required': False},
    {'id': 'wholesale_unit', 'label': 'Wholesale unit name (base = 1 per item; e.g. box, bottle)', 'required': False},
    {'id': 'retail_unit', 'label': 'Retail unit name (e.g. tablet, piece, ml)', 'required': False},
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
    {'id': 'current_stock_quantity', 'label': 'Current Stock Quantity (in wholesale/base units)', 'required': False},
    {'id': 'opening_batch_number', 'label': 'Opening Batch Number (required when Track Expiry=Yes and opening stock > 0)', 'required': False},
    {'id': 'opening_expiry_date', 'label': 'Opening Expiry Date YYYY-MM-DD (required when Track Expiry=Yes and opening stock > 0)', 'required': False},
    {'id': 'supplier', 'label': 'Supplier', 'required': False},
    {'id': 'vat_category', 'label': 'VAT Category', 'required': False},
    {'id': 'vat_rate', 'label': 'VAT Rate', 'required': False},
    {'id': 'product_category', 'label': 'Product Category (Pharmaceutical, Cosmetics, Equipment, Service)', 'required': False},
    {'id': 'pricing_tier', 'label': 'Pricing Tier (Chronic medication, Standard, Beauty/Cosmetics, etc.)', 'required': False},
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


def _get_item_name_from_row(row: Dict) -> Optional[str]:
    """Get item name from row using all known column variants. Returns None if blank/missing."""
    name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name', 'Description'])
    return _safe_strip(name) if name else None


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


def _normalize_units_for_excel_item(
    wholesale_unit: str,
    retail_unit: str,
    supplier_unit: str,
    pack_size: int,
    wholesale_units_per_supplier,
) -> Tuple[str, str, str]:
    """
    Enforce unit naming rules from Excel import:
    - pack_size == 1: single name everywhere (wholesale = retail; supplier = same unless wups > 1).
    - wholesale_units_per_supplier > 1: supplier unit name must differ from wholesale (e.g. case vs tube).
    Returns (wholesale_unit, retail_unit, supplier_unit).
    """
    pack_size = max(1, int(pack_size or 1))
    try:
        wups = float(wholesale_units_per_supplier or 1)
    except (TypeError, ValueError):
        wups = 1
    w = (wholesale_unit or "piece").strip().lower()
    r = (retail_unit or "piece").strip().lower()
    s = (supplier_unit or "piece").strip().lower()
    if pack_size == 1:
        single = r or w or "piece"
        w = r = single
        if wups <= 1:
            s = single
        elif s == single:
            s = "case"  # enforce different name when conversion > 1
    else:
        if wups > 1 and s == w:
            s = "case"  # enforce different supplier name when conversion > 1
    return (w, r, s)


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
        'Wsale price',
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
        'Cost price',
        'Last Cost',
        'Last_Cost'
    ]) or '0'
    wups = _parse_wholesale_units_per_supplier_from_row(row)
    purchase_per_supplier = ExcelImportService._parse_decimal(purchase_raw)
    return _cost_per_supplier_to_cost_per_base(purchase_per_supplier, wups)


def _normalize_product_category_from_row(row: Dict) -> Optional[str]:
    """Extract product_category from row; return only if valid (PHARMACEUTICAL, COSMETICS, EQUIPMENT, SERVICE).
    Accepts client columns: Category (PHARMACY→PHARMACY, COSMETICS→COSMETICS), Sub Category (cosmetic-like→COSMETICS).
    """
    from app.models.item import PRODUCT_CATEGORIES
    raw = _safe_strip(_normalize_column_name(row, [
        'Product_Category', 'Product Category', 'product_category',
        'Category', 'category', 'Sub Category', 'Sub_Category', 'sub category'
    ]) or '')
    if not raw:
        return None
    val = raw.upper().replace(' ', '_').replace('-', '_')
    if val in PRODUCT_CATEGORIES:
        return val
    if val == 'PHARMACY':
        return 'PHARMACEUTICAL'
    if val in ('COSMETIC', 'BEAUTY'):
        return 'COSMETICS'
    # Sub Category cosmetic-like → COSMETICS
    cosmetic_like = (
        'MOISTURIZER', 'LOTION', 'BODY_SPLASH', 'SUNSCREEN', 'SKIN_CARE', 'ORAL_TREATMENT',
        'PERFUMES', 'OPTHALMIC_SOL', 'CONDOMS', 'SOAP', 'SERUM', 'SHOWER_GEL', 'LIPBALM',
        'BODY_SCRUB', 'GEL', 'FACE_MASK', 'SKINCARE', 'TONER', 'EYE_PENCIL', 'ROLL_ON',
        'SHAMPOO', 'CLEANSER', 'LIPSTICK', 'MISCELLANEOUS'
    )
    if val in cosmetic_like or 'COSMETIC' in val or 'BEAUTY' in val or 'SKIN' in val:
        return 'COSMETICS'
    # Default pharmacy-style subcategories to PHARMACEUTICAL
    if val in ('SUPPLEMENTS', 'NON_PHARM', 'CONTROLLED', 'PHARMACY'):
        return 'PHARMACEUTICAL'
    return None


# Map client "Sub Category" and similar values to PharmaSight pricing_tier (keys: normalized with spaces and underscores)
def _sub_category_to_tier(sub: str) -> Optional[str]:
    from app.models.item import PRICING_TIERS
    if not sub or not sub.strip():
        return None
    raw = sub.strip().upper()
    raw_underscore = raw.replace(' ', '_').replace('-', '_')
    mapping = {
        'SUPPLEMENTS': 'NUTRITION_SUPPLEMENTS',
        'NON PHARM': 'STANDARD', 'NON_PHARM': 'STANDARD',
        'MOISTURIZER': 'BEAUTY_COSMETICS', 'LOTION': 'BEAUTY_COSMETICS',
        'BODY SPLASH': 'BEAUTY_COSMETICS', 'BODY_SPLASH': 'BEAUTY_COSMETICS',
        'SUNSCREEN': 'BEAUTY_COSMETICS', 'SKIN CARE': 'BEAUTY_COSMETICS', 'SKINCARE': 'BEAUTY_COSMETICS',
        'PERFUMES': 'BEAUTY_COSMETICS', 'SOAP': 'BEAUTY_COSMETICS', 'SHOWER GEL': 'BEAUTY_COSMETICS',
        'SHAMPOO': 'BEAUTY_COSMETICS', 'CLEANSER': 'BEAUTY_COSMETICS', 'LIPSTICK': 'BEAUTY_COSMETICS',
        'INSULIN INJ': 'INJECTABLES', 'VACCINE INJ': 'INJECTABLES', 'INJECTABLES': 'INJECTABLES',
        'CONTROLLED': 'STANDARD', 'ANTIHYPERTENSIVE': 'CHRONIC_MEDICATION', 'ANTIDIABETICS': 'CHRONIC_MEDICATION',
        'STATINS': 'CHRONIC_MEDICATION', 'ANTICOAGULANT': 'CHRONIC_MEDICATION', 'INHALERS': 'STANDARD',
        'INHALER': 'STANDARD', 'IMMUNOSUPPRESANT': 'CHRONIC_MEDICATION', 'ANTICONVULSANTS': 'CHRONIC_MEDICATION',
    }
    tier = mapping.get(raw) or mapping.get(raw_underscore)
    return tier if tier and tier in PRICING_TIERS else None


def _normalize_pricing_tier_from_row(row: Dict) -> Optional[str]:
    """Extract pricing_tier from row; return only if valid tier name.
    Accepts client columns: Sub Category (mapped via _sub_category_to_tier), Pricing_Tier.
    """
    from app.models.item import PRICING_TIERS
    raw = _safe_strip(_normalize_column_name(row, [
        'Pricing_Tier', 'Pricing Tier', 'pricing_tier',
        'Sub Category', 'Sub_Category', 'sub category', 'SubCategory'
    ]) or '')
    if not raw:
        return None
    val = raw.upper().replace(' ', '_').replace('-', '_')
    if val in PRICING_TIERS:
        return val
    tier = _sub_category_to_tier(raw)
    return tier


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


def _vat_from_row(row: Dict) -> Dict:
    """
    Parse VAT category and rate from Excel row with inference:
    - If vat_rate > 0 is provided, set vat_category = STANDARD_RATED (so VAT is not zeroed).
    - Unit cost from Excel is assumed exclusive of VAT.
    """
    vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category', 'vat_category']) or 'ZERO_RATED'
    vat_category = (_safe_strip(vat_category_raw) or 'ZERO_RATED').upper()
    vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'vat_rate', 'Tax Rate', 'Tax', 'VAT']) or '0'
    vat_rate = ExcelImportService._parse_decimal(vat_rate_raw)
    if vat_rate and vat_rate > 0:
        vat_category = 'STANDARD_RATED'
    elif vat_category == 'STANDARD_RATED' and (not vat_rate or vat_rate == 0):
        vat_rate = Decimal('16.00')
    elif vat_category == 'ZERO_RATED':
        vat_rate = Decimal('0.00')
    # Store as percentage in DB (0.16 -> 16) for Kenyan system
    vat_rate = Decimal(str(vat_rate_to_percent(float(vat_rate))))
    return {'vat_rate': vat_rate, 'vat_category': vat_category}


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
        Validate Excel data structure. Call after filtering out blank rows and deduplicating.
        - Only checks that there is at least one row left to import.
        - Duplicate item names are handled by deduplication (keep first, skip rest) before this.
        """
        if not excel_data:
            return False, ["Excel file is empty or has no rows with item name."]
        return True, []
    
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
        # Skip rows with blank item name (silent)
        excel_data = [row for row in excel_data if _get_item_name_from_row(row)]
        if not excel_data:
            raise ValueError(
                "No valid rows: every row has blank or missing item name. "
                "Use a column that contains the product name (e.g. Item Name, Description) and ensure it is mapped."
            )
        # Deduplicate by item name (keep first occurrence, skip later duplicates) so import does not abort
        seen_name_lower = set()
        deduped = []
        duplicate_names = []
        for row in excel_data:
            name = _get_item_name_from_row(row)
            if not name:
                continue
            key = name.lower().strip()
            if key in seen_name_lower:
                if name not in duplicate_names:
                    duplicate_names.append(name)
                continue
            seen_name_lower.add(key)
            deduped.append(row)
        rows_skipped_duplicate = len(excel_data) - len(deduped)
        excel_data = deduped
        is_valid, errors = ExcelImportService.validate_excel_data(excel_data)
        if not is_valid:
            raise ValueError(f"Excel data validation failed: {'; '.join(errors)}")
        
        # Detect mode
        if force_mode:
            mode = force_mode.upper()
            if mode not in ['AUTHORITATIVE', 'NON_DESTRUCTIVE']:
                raise ValueError(f"Invalid force_mode: {force_mode}")
        else:
            mode = ExcelImportService.detect_import_mode(db, company_id)
        
        logger.info(f"Excel import mode: {mode} for company {company_id}")
        
        if mode == 'AUTHORITATIVE':
            result = ExcelImportService._import_authoritative(
                db, company_id, branch_id, user_id, excel_data, job_id=job_id
            )
        else:
            result = ExcelImportService._import_non_destructive(
                db, company_id, branch_id, user_id, excel_data, job_id=job_id
            )
        if rows_skipped_duplicate:
            stats = result.get("stats") or {}
            stats["rows_skipped_duplicate_name"] = rows_skipped_duplicate
            stats["duplicate_item_names"] = duplicate_names
            result["stats"] = stats
        return result

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
    def _overwrite_item_from_excel(db: Session, item: Item, row: Dict):
        """
        Overwrite an existing item with Excel data (safe ONLY when item has no real transactions).

        This updates BOTH structural fields (units/pack_size) and non-structural fields.
        Units are item characteristics (items table columns only).
        """
        # Reuse the same parsing logic as create for consistency
        description = _normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Generic name']) or ''
        barcode = _normalize_column_name(row, ['Barcode', 'barcode', 'BARCODE']) or ''
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY', 'Brand']) or ''

        supplier_unit_raw = _normalize_column_name(row, ['Supplier_Unit', 'Supplier Unit', 'supplier_unit']) or ''
        wholesale_unit_raw = _normalize_column_name(row, ['Wholesale_Unit', 'Wholesale Unit', 'wholesale_unit']) or ''
        retail_unit_raw = _normalize_column_name(row, ['Retail_Unit', 'Retail Unit', 'retail_unit']) or ''
        supplier_unit = _sanitize_unit_label(supplier_unit_raw, 'packet')
        wholesale_unit = _sanitize_unit_label(wholesale_unit_raw, 'packet')
        retail_unit = _sanitize_unit_label(retail_unit_raw, 'tablet')
        pack_size_raw = _normalize_column_name(row, ['Pack_Size', 'Pack Size', 'pack size', 'pack_size', 'Conversion Rate (n) (x = ny)', 'Conversion_To_Retail']) or '1'
        pack_size = int(ExcelImportService._parse_decimal(pack_size_raw)) if pack_size_raw else 1
        pack_size = max(1, int(pack_size))
        wholesale_units_per_supplier = _parse_wholesale_units_per_supplier_from_row(row)
        wholesale_unit, retail_unit, supplier_unit = _normalize_units_for_excel_item(
            wholesale_unit, retail_unit, supplier_unit, pack_size, wholesale_units_per_supplier
        )

        can_break_bulk_raw = _normalize_column_name(row, ['Can_Break_Bulk', 'Can Break Bulk', 'can_break_bulk'])
        can_break_bulk = str(can_break_bulk_raw).lower() in ['true', '1', 'yes', 'y'] if can_break_bulk_raw else True

        vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category', 'vat_category']) or 'ZERO_RATED'
        vat_category = (_safe_strip(vat_category_raw) or 'ZERO_RATED').upper()
        vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'vat_rate', 'Tax Rate', 'Tax', 'VAT']) or '0'
        vat_rate = ExcelImportService._parse_decimal(vat_rate_raw)
        # Infer category from rate when only rate is provided (e.g. Excel has "VAT Rate" = 16 but no category column)
        if vat_rate and vat_rate > 0:
            vat_category = 'STANDARD_RATED'
            if vat_rate != Decimal('16.00'):
                pass  # keep explicit rate (e.g. 16)
        elif vat_category == 'STANDARD_RATED' and (not vat_rate or vat_rate == 0):
            vat_rate = Decimal('16.00')
        elif vat_category == 'ZERO_RATED':
            vat_rate = Decimal('0.00')
        # Store as percentage in DB (0.16 -> 16) for Kenyan system
        vat_rate = Decimal(str(vat_rate_to_percent(float(vat_rate))))

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
        # Units are item characteristics (items table only); no item_units table.
    
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
            
            stock_validation_config = None
            try:
                from app.services.stock_validation_service import get_stock_validation_config
                stock_validation_config = get_stock_validation_config(db, company_id)
            except Exception as e:
                logger.warning("Could not load stock validation config: %s", e)
            
            # Process in batches; smaller size so first progress update shows within ~30–60s (was 1000 → 0% for minutes)
            batch_size = 200  # 1036 items = 6 batches; first commit after 200 rows so UI shows progress soon
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
                        db, company_id, branch_id, user_id, batch, batch_start,
                        stock_validation_config=stock_validation_config,
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
                                db, company_id, branch_id, user_id, row,
                                stock_validation_config=stock_validation_config,
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
                            item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name', 'Description']) or 'Unknown'
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
                        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name', 'Description']) or 'Unknown'
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
        row: Dict,
        stock_validation_config: Optional[object] = None,
    ) -> Dict:
        """Process a single Excel row in AUTHORITATIVE mode. stock_validation_config: from get_stock_validation_config (once per request)."""
        result = {
            'item_created': 0,
            'item_updated': 0,
            'opening_balance_created': 0,
            'supplier_created': 0
        }
        
        # Use normalize_column_name to handle various column name formats
        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name', 'Description']) or ''
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
                    # Safe to fully overwrite (master data only; units are item columns)
                    ExcelImportService._overwrite_item_from_excel(db, item, row)
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
                'Wsale price',
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
                    'Cost price',
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
                    'Quantity Available',
                    'stock quantity'
                ]) or '0'
                stock_qty = ExcelImportService._parse_quantity(stock_qty_raw)
                batch_number_open = None
                expiry_date_open = None
                if getattr(item, "track_expiry", False) and stock_qty > 0:
                    batch_number_open = _normalize_column_name(row, [
                        'Opening_Batch_Number', 'Opening Batch Number', 'opening_batch_number'
                    ])
                    batch_number_open = _safe_strip(batch_number_open) if batch_number_open else None
                    expiry_date_raw = _normalize_column_name(row, [
                        'Opening_Expiry_Date', 'Opening Expiry Date', 'opening_expiry_date'
                    ])
                    expiry_date_raw = _safe_strip(expiry_date_raw) if expiry_date_raw else None
                    if not batch_number_open or not expiry_date_raw:
                        raise ValueError(
                            f"Item '{item_name}' has Track Expiry and opening stock. "
                            "Provide Opening Batch Number and Opening Expiry Date (YYYY-MM-DD) columns."
                        )
                    try:
                        from datetime import datetime as dt
                        expiry_date_open = dt.fromisoformat(expiry_date_raw.replace("Z", "+00:00")).date()
                    except (ValueError, TypeError):
                        raise ValueError(
                            f"Item '{item_name}': Invalid Opening Expiry Date '{expiry_date_raw}'. Use YYYY-MM-DD."
                        )
                    if stock_validation_config is not None:
                        from app.services.stock_validation_service import (
                            validate_stock_entry_with_config,
                            StockValidationError,
                        )
                        try:
                            res = validate_stock_entry_with_config(
                                stock_validation_config,
                                batch_number=batch_number_open,
                                expiry_date=expiry_date_open,
                                track_expiry=True,
                                require_batch=bool(getattr(stock_validation_config, "require_batch_tracking", True)),
                                require_expiry=bool(getattr(stock_validation_config, "require_expiry_tracking", True)),
                                override=False,
                            )
                        except StockValidationError as e:
                            raise ValueError(e.result.message if e.result else str(e))
                        if not res.valid:
                            raise ValueError(res.message or "Batch/expiry validation failed.")
                ExcelImportService._create_opening_balance(
                    db, company_id, branch_id, item.id, stock_qty, user_id,
                    unit_cost_per_base=default_cost_per_base,
                    batch_number=batch_number_open,
                    expiry_date=expiry_date_open,
                )
                if stock_qty > 0:
                    result['opening_balance_created'] = 1
            except Exception as stock_error:
                logger.warning(f"Could not create opening balance for item '{item_name}': {stock_error}")
                raise
        
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
        
        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name', 'Description']) or ''
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
                ExcelImportService._overwrite_item_from_excel(db, item, row)
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
        item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name', 'Description']) or ''
        description = _normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Generic name']) or ''
        item_code_raw = _normalize_column_name(row, ['Item_Code', 'Item Code', 'Item code', 'SKU', 'sku']) or ''
        item_code = _safe_strip(item_code_raw) or generate_sku_for_company(company_id, db)
        barcode = _normalize_column_name(row, ['Barcode', 'barcode', 'BARCODE']) or ''
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY', 'Brand']) or ''
        
        # 3-TIER UNIT SYSTEM (from Excel template); sanitize so we never store a number as unit name
        supplier_unit_raw = _normalize_column_name(row, ['Supplier_Unit', 'Supplier Unit', 'supplier_unit']) or ''
        wholesale_unit_raw = _normalize_column_name(row, ['Wholesale_Unit', 'Wholesale Unit', 'wholesale_unit']) or ''
        retail_unit_raw = _normalize_column_name(row, ['Retail_Unit', 'Retail Unit', 'retail_unit']) or ''
        supplier_unit = _sanitize_unit_label(supplier_unit_raw, 'packet')
        wholesale_unit = _sanitize_unit_label(wholesale_unit_raw, 'packet')
        retail_unit = _sanitize_unit_label(retail_unit_raw, 'tablet')
        pack_size_raw = _normalize_column_name(row, ['Pack_Size', 'Pack Size', 'pack size', 'pack_size', 'Conversion Rate (n) (x = ny)', 'Conversion_To_Retail']) or '1'
        pack_size = max(1, int(ExcelImportService._parse_decimal(pack_size_raw)) if pack_size_raw else 1)
        wholesale_units_per_supplier = _parse_wholesale_units_per_supplier_from_row(row)
        wholesale_unit, retail_unit, supplier_unit = _normalize_units_for_excel_item(
            wholesale_unit, retail_unit, supplier_unit, pack_size, wholesale_units_per_supplier
        )
        can_break_bulk_raw = _normalize_column_name(row, ['Can_Break_Bulk', 'Can Break Bulk', 'can_break_bulk'])
        can_break_bulk = str(can_break_bulk_raw).lower() in ['true', '1', 'yes', 'y'] if can_break_bulk_raw else True
        
        # VAT CLASSIFICATION (unit cost from Excel is assumed exclusive of VAT)
        vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category', 'vat_category']) or 'ZERO_RATED'
        vat_category = _safe_strip(vat_category_raw) or 'ZERO_RATED'
        vat_category = vat_category.upper() if vat_category else 'ZERO_RATED'
        vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'vat_rate', 'Tax Rate', 'Tax', 'VAT']) or '0'
        vat_rate = ExcelImportService._parse_decimal(vat_rate_raw)
        # Infer STANDARD_RATED from positive rate when category not provided (e.g. only "VAT Rate" column with 16)
        if vat_rate and vat_rate > 0:
            vat_category = 'STANDARD_RATED'
        elif vat_category == 'STANDARD_RATED' and (not vat_rate or vat_rate == 0):
            vat_rate = Decimal('16.00')
        elif vat_category == 'ZERO_RATED':
            vat_rate = Decimal('0.00')
        # Store as percentage in DB (0.16 -> 16) for Kenyan system
        vat_rate = Decimal(str(vat_rate_to_percent(float(vat_rate))))
        
        # Base = wholesale (reference unit). Prices/cost come from inventory_ledger only.
        base_unit = wholesale_unit
        
        item = Item(
            company_id=company_id,
            name=_safe_strip(item_name) or '',
            description=_safe_strip(description),
            sku=item_code,
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
            is_active=True,
            setup_complete=False,
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
        category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY', 'Brand'])
        if category:
            item.category = _safe_strip(category)
        
        # Update VAT (vat_category + vat_rate only)
        vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category'])
        if vat_category_raw:
            vat_cat = _safe_strip(vat_category_raw) or 'ZERO_RATED'
            item.vat_category = vat_cat.upper() if vat_cat else 'ZERO_RATED'
        
        vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'Tax Rate'])
        if vat_rate_raw:
            parsed = ExcelImportService._parse_decimal(vat_rate_raw)
            item.vat_rate = Decimal(str(vat_rate_to_percent(float(parsed))))
    
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
        supplier_name_raw = _normalize_column_name(row, ['Supplier', 'supplier', 'SUPPLIER', 'Supplier Name', 'supplier name', 'Vendor', 'Vendor Name', 'vendor']) or ''
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
        unit_cost_per_base: Optional[Decimal] = None,
        batch_number: Optional[str] = None,
        expiry_date: Optional[date] = None,
    ):
        """Create opening balance entry in inventory_ledger. unit_cost_per_base = cost per base (wholesale) unit; from Excel (row) only.
        For track_expiry items, pass batch_number and expiry_date."""
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
            old_qty = existing.quantity_delta
            existing.quantity_delta = quantity
            existing.unit_cost = unit_cost
            existing.total_cost = quantity * unit_cost
            if batch_number is not None:
                existing.batch_number = batch_number.strip() if batch_number else None
            if expiry_date is not None:
                existing.expiry_date = expiry_date if isinstance(expiry_date, date) else expiry_date
            SnapshotService.upsert_inventory_balance_delta(
                db, company_id, branch_id, item_id, old_qty, quantity,
                document_number="OPENING",
            )
            SnapshotService.upsert_purchase_snapshot(db, company_id, branch_id, item_id, unit_cost, None, None)
            SnapshotRefreshService.refresh_item_sync(db, company_id, branch_id, item_id)
        else:
            ledger_entry = InventoryLedger(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                transaction_type='OPENING_BALANCE',
                reference_type='OPENING_BALANCE',
                document_number='OPENING',
                quantity_delta=quantity,
                unit_cost=unit_cost,
                total_cost=quantity * unit_cost,
                created_by=user_id,
                batch_number=batch_number.strip() if batch_number and str(batch_number).strip() else None,
                expiry_date=expiry_date if isinstance(expiry_date, date) else expiry_date,
            )
            db.add(ledger_entry)
            db.flush()
            SnapshotService.upsert_inventory_balance(
                db, company_id, branch_id, item_id, quantity,
                document_number="OPENING",
            )
            SnapshotService.upsert_purchase_snapshot(db, company_id, branch_id, item_id, unit_cost, None, None)
            SnapshotRefreshService.refresh_item_sync(db, company_id, branch_id, item_id)
    
    @staticmethod
    def _process_batch_bulk(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        user_id: UUID,
        batch: List[Dict],
        batch_start: int,
        stock_validation_config: Optional[object] = None,
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
            item_name = _normalize_column_name(row, ['Item_Name', 'Item name*', 'Item name', 'Item Name', 'Description']) or ''
            item_name = _safe_strip(item_name)
            if item_name:
                item_names.append(item_name)
                valid_rows.append((item_name, row))
            
            supplier_name = _normalize_column_name(row, ['Supplier', 'Supplier Name', 'supplier', 'Vendor', 'Vendor Name', 'vendor']) or ''
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
        
        # Step 3a: Create any missing suppliers NOW so we have their IDs when setting default_supplier_id on items
        suppliers_to_create = []
        for name in supplier_names:
            if name and _safe_strip(name) and _safe_strip(name).lower() not in existing_suppliers:
                suppliers_to_create.append({
                    'id': uuid4(),
                    'company_id': company_id,
                    'name': _safe_strip(name),
                    'is_active': True
                })
        if suppliers_to_create:
            db.bulk_insert_mappings(Supplier, suppliers_to_create)
            db.flush()
            result['suppliers_created'] = len(suppliers_to_create)
        
        # Step 3b: ONE call to get all item ids that have real transactions (avoids N+1: was 500+ calls per batch)
        existing_item_ids = [item.id for item in existing_items.values()]
        items_with_real_tx_set = ExcelImportService._get_items_with_real_transactions(db, company_id, existing_item_ids) if existing_item_ids else set()
        
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
        # One query for entire batch instead of one per item (was causing 1000+ queries for 1k items)
        next_sku_num = get_next_sku_number_for_bulk(company_id, db)

        for item_name, row in valid_rows:
            item_name_lower = item_name.lower()
            item_name_to_row[item_name_lower] = (item_name, row)
            
            if item_name_lower in existing_items:
                # Existing item: decide replace vs safe update based on real transactions
                item = existing_items[item_name_lower]
                has_real_tx = item.id in items_with_real_tx_set
                if not has_real_tx:
                    replaceable_item_ids.add(item.id)
                    # Full overwrite mapping (includes structural fields)
                    item_dict = ExcelImportService._create_item_dict_for_bulk(company_id, row, item_name)
                    if not (item_dict.get('sku') or '').strip():
                        item_dict['sku'] = f"A{next_sku_num:05d}"
                        next_sku_num += 1
                    item_dict['id'] = item.id
                    update_mappings_replaceable.append(item_dict)
                else:
                    # Safe update mapping only (do NOT touch unit structure)
                    safe = {'id': item.id}
                    description = _normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Generic name'])
                    if description:
                        safe['description'] = _safe_strip(description)
                    category = _normalize_column_name(row, ['Category', 'category', 'CATEGORY', 'Brand'])
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
                        parsed = ExcelImportService._parse_decimal(vat_rate_raw)
                        safe['vat_rate'] = Decimal(str(vat_rate_to_percent(float(parsed))))
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
                if not (item_dict.get('sku') or '').strip():
                    item_dict['sku'] = f"A{next_sku_num:05d}"
                    next_sku_num += 1
                items_to_insert.append(item_dict)
        
        # Step 4b: Build supplier name -> id (existing + just-created) and add default_supplier_id to item dicts
        supplier_name_to_id = {n.lower(): s.id for n, s in existing_suppliers.items()}
        supplier_name_to_id.update({s['name'].lower(): s['id'] for s in suppliers_to_create})
        for item_dict in items_to_insert + update_mappings_replaceable:
            name_lower = (item_dict.get('name') or '').lower()
            (_, row) = item_name_to_row.get(name_lower, (None, {}))
            supplier_name = _safe_strip(_normalize_column_name(row, ['Supplier', 'supplier', 'SUPPLIER', 'Supplier Name', 'supplier name', 'Vendor', 'Vendor Name', 'vendor']) or '')
            item_dict['default_supplier_id'] = supplier_name_to_id.get(supplier_name.lower()) if supplier_name else None
        suppliers_to_create = []  # Already inserted in Step 3a; avoid double-insert in Step 10
        
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

        # If replaceable existing items, clear their ItemPricing only
        if replaceable_item_ids:
            db.query(ItemPricing).filter(ItemPricing.item_id.in_(list(replaceable_item_ids))).delete(synchronize_session=False)
            db.flush()
        
        # Step 7b: Bulk fetch existing ItemPricing for all items in this batch (ONE query instead of N)
        all_item_ids_batch = [item.id for item in all_items_map.values()]
        existing_pricing_list = db.query(ItemPricing).filter(ItemPricing.item_id.in_(all_item_ids_batch)).all() if all_item_ids_batch else []
        existing_pricing_by_item = {p.item_id: p for p in existing_pricing_list}
        
        # Step 8: Prepare pricing and opening balances
        for item_name_lower, (item_name, row) in item_name_to_row.items():
            if item_name_lower not in all_items_map:
                continue
            
            item = all_items_map[item_name_lower]
            is_locked = item.id in items_with_real_tx_set
            
            # Prepare pricing
            try:
                pricing_dict = ExcelImportService._prepare_pricing_for_bulk(item, row)
                existing_pricing = existing_pricing_by_item.get(item.id)
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
                        'Quantity Available',
                        'stock quantity'
                    ]) or '0'
                )
                if stock_qty > 0:
                    batch_number_ob = None
                    expiry_date_ob = None
                    if getattr(item, 'track_expiry', False):
                        require_batch = bool(getattr(stock_validation_config, "require_batch_tracking", True)) if stock_validation_config is not None else True
                        require_expiry = bool(getattr(stock_validation_config, "require_expiry_tracking", True)) if stock_validation_config is not None else True
                        batch_number_ob = _safe_strip(_normalize_column_name(row, [
                            'Opening_Batch_Number', 'Opening Batch Number', 'opening_batch_number'
                        ]) or '')
                        expiry_date_raw = _safe_strip(_normalize_column_name(row, [
                            'Opening_Expiry_Date', 'Opening Expiry Date', 'opening_expiry_date'
                        ]) or '')
                        if (require_batch and not batch_number_ob) or (require_expiry and not expiry_date_raw):
                            result.setdefault('errors', []).append(
                                f"Item '{item_name}' has Track Expiry and opening stock. Provide Opening Batch Number and Opening Expiry Date (YYYY-MM-DD). Skipping opening balance for this row."
                            )
                            raise ValueError("Skip opening balance")
                        try:
                            expiry_date_ob = datetime.fromisoformat(expiry_date_raw.replace("Z", "+00:00")).date()
                        except (ValueError, TypeError):
                            result.setdefault('errors', []).append(
                                f"Item '{item_name}': Invalid Opening Expiry Date. Use YYYY-MM-DD. Skipping opening balance."
                            )
                            raise ValueError("Skip opening balance")
                        if stock_validation_config is not None:
                            from app.services.stock_validation_service import (
                                validate_stock_entry_with_config,
                                StockValidationError,
                            )
                            try:
                                res = validate_stock_entry_with_config(
                                    stock_validation_config,
                                    batch_number=batch_number_ob,
                                    expiry_date=expiry_date_ob,
                                    track_expiry=True,
                                    require_batch=require_batch,
                                    require_expiry=require_expiry,
                                    override=False,
                                )
                            except StockValidationError as e:
                                result.setdefault('errors', []).append(
                                    f"Item '{item_name}': {e.result.message if e.result else str(e)}. Skipping opening balance."
                                )
                                raise ValueError("Skip opening balance")
                            if not res.valid:
                                result.setdefault('errors', []).append(
                                    f"Item '{item_name}': {res.message or 'Batch/expiry validation failed.'}. Skipping opening balance."
                                )
                                raise ValueError("Skip opening balance")
                    wholesale_price_raw = _normalize_column_name(row, [
                        'Wholesale_Price_per_Wholesale_Unit',
                        'Wholesale_Unit_Price',
                        'Wholesale Unit Price',
                        'Wsale price',
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
                            'Cost price',
                            'Last Cost',
                            'Purchase price'
                        ]) or '0'
                        purchase_per_supplier = ExcelImportService._parse_decimal(purchase_raw)
                        wups = getattr(item, 'wholesale_units_per_supplier', None) or Decimal('1')
                        unit_cost_per_base = _cost_per_supplier_to_cost_per_base(purchase_per_supplier, wups)
                    ob_dict = {
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
                    }
                    if batch_number_ob:
                        ob_dict['batch_number'] = batch_number_ob
                    if expiry_date_ob is not None:
                        ob_dict['expiry_date'] = expiry_date_ob
                    opening_balances.append(ob_dict)
            except ValueError as e:
                if str(e) == "Skip opening balance":
                    pass
                else:
                    logger.warning(f"Could not prepare opening balance for {item_name}: {e}")
            except Exception as e:
                logger.warning(f"Could not prepare opening balance for {item_name}: {e}")
            
            # Suppliers already created in Step 3a; no need to append to suppliers_to_create here
        
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
                db.flush()
                # Bulk update inventory_balances and purchase snapshot (one query each) instead of N per-item sync refreshes
                balance_rows = [
                    (ob['company_id'], ob['branch_id'], ob['item_id'], ob['quantity_delta'])
                    for ob in opening_balances
                ]
                purchase_rows = [
                    (ob['company_id'], ob['branch_id'], ob['item_id'], ob.get('unit_cost'), ob.get('created_at'), None)
                    for ob in opening_balances
                ]
                SnapshotService.upsert_inventory_balance_bulk(db, balance_rows)
                SnapshotService.upsert_purchase_snapshot_bulk(db, purchase_rows)
                # Enqueue one branch refresh so item_branch_snapshot is updated in background (avoids N sync refreshes)
                first_ob = opening_balances[0]
                SnapshotRefreshService.enqueue_branch_refresh(
                    db, first_ob['company_id'], first_ob['branch_id'], reason="excel_import_bulk"
                )
                result['opening_balances_created'] = len(opening_balances)
                logger.info(f"Bulk inserted {len(opening_balances)} opening balances (snapshot refresh enqueued)")
            except Exception as e:
                logger.warning(f"Some opening balances failed bulk insert: {e}")

        return result
    
    @staticmethod
    def _create_item_dict_for_bulk(company_id: UUID, row: Dict, item_name: str) -> Dict:
        """Create item dictionary for bulk insert. Master data only; no price fields (from ledger)."""
        from uuid import uuid4
        wholesale_unit = _sanitize_unit_label(_normalize_column_name(row, ['Wholesale_Unit', 'Wholesale Unit']), 'piece')
        retail_unit = _sanitize_unit_label(_normalize_column_name(row, ['Retail_Unit', 'Retail Unit']), 'tablet')
        supplier_unit = _sanitize_unit_label(_normalize_column_name(row, ['Supplier_Unit', 'Supplier Unit']), 'piece')
        try:
            pack_size_raw = _normalize_column_name(row, ['Pack_Size', 'Pack Size', 'Conversion_To_Retail']) or '1'
            pack_size = max(1, int(ExcelImportService._parse_decimal(pack_size_raw)))
        except (ValueError, TypeError, Exception):
            pack_size = 1  # Missing or invalid (e.g. "n/a") → 1 so import does not fail
        wholesale_units_per_supplier = _parse_wholesale_units_per_supplier_from_row(row)
        wholesale_unit, retail_unit, supplier_unit = _normalize_units_for_excel_item(
            wholesale_unit, retail_unit, supplier_unit, pack_size, wholesale_units_per_supplier
        )
        return {
            'id': uuid4(),
            'company_id': company_id,
            'name': item_name,
            'description': _safe_strip(_normalize_column_name(row, ['Description', 'Generic_Name', 'Generic Name', 'Description']) or ''),
            'sku': _safe_strip(_normalize_column_name(row, ['Item_Code', 'SKU', 'Item Code', 'sku']) or ''),
            'barcode': _safe_strip(_normalize_column_name(row, ['Barcode', 'barcode']) or ''),
            'category': _safe_strip(_normalize_column_name(row, ['Category', 'category', 'Brand']) or ''),
            'base_unit': wholesale_unit,
            **_vat_from_row(row),
            'is_active': True,
            'supplier_unit': supplier_unit,
            'wholesale_unit': wholesale_unit,
            'retail_unit': retail_unit,
            'pack_size': pack_size,
            'wholesale_units_per_supplier': wholesale_units_per_supplier,
            'can_break_bulk': True,
            'track_expiry': _parse_bool_from_row(row, ['Track_Expiry', 'Track Expiry', 'track_expiry'], False),
            'is_controlled': _parse_bool_from_row(row, ['Is_Controlled', 'Is Controlled', 'is_controlled'], False),
            'is_cold_chain': _parse_bool_from_row(row, ['Is_Cold_Chain', 'Is Cold Chain', 'is_cold_chain'], False),
            'default_cost_per_base': _default_cost_per_base_from_row(row),
            'product_category': _normalize_product_category_from_row(row),
            'pricing_tier': _normalize_pricing_tier_from_row(row),
            'setup_complete': False,
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
