"""
Items service – 3-tier UNIT system (base = wholesale).

Base/reference = wholesale unit (1 per item). Stock in base = wholesale qty.
- Retail: 1 wholesale = pack_size retail. retail_qty = wholesale_qty * pack_size.
- Supplier: 1 supplier = wholesale_units_per_supplier wholesale. supplier_qty = wholesale_qty / N.
"""
from __future__ import annotations

import re
import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Item
from app.schemas.item import ItemCreate, ItemUpdate

logger = logging.getLogger(__name__)


class DuplicateItemNameError(ValueError):
    """Raised when creating an item whose name already exists for the company (case-insensitive)."""
    def __init__(self, name: str, company_id: UUID):
        self.name = name
        self.company_id = company_id
        super().__init__(f"An item with the name '{name}' already exists for this company.")


def _is_numeric_unit_value(value) -> bool:
    """Return True if value looks like a number (e.g. price mistaken for unit name)."""
    if value is None:
        return False
    s = (str(value).strip() if value else "").strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _sanitize_base_unit(value, fallback: str) -> str:
    """Ensure base_unit is a label (bottle, piece, etc.), not a number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return (fallback or "piece").lower()
    s = str(value).strip()
    if _is_numeric_unit_value(s):
        return (fallback or "piece").lower()
    return s.lower()


def _generate_sku(company_id: UUID, db: Session) -> str:
    """Generate unique SKU for company (A00001, A00002, ...)."""
    last = (
        db.query(Item.sku)
        .filter(Item.company_id == company_id, Item.sku.isnot(None), Item.sku != "")
        .order_by(Item.sku.desc())
        .limit(100)
        .all()
    )
    max_n = 0
    for row in last:
        if row[0]:
            m = re.match(r"^([A-Z]{1,3})(\d+)$", (row[0] or "").upper())
            if m:
                try:
                    max_n = max(max_n, int(m.group(2)))
                except ValueError:
                    pass
    return f"A{(max_n + 1):05d}"


def create_item(db: Session, data: ItemCreate) -> Item:
    """
    Create item with 3-tier units. Units are item characteristics (items table only; no item_units table).

    - Validates pack_size >= 1 and breakable => pack_size > 1 (done in schema).
    - Sets base_unit = wholesale_unit (reference). Cost/price from inventory_ledger only.
    - Rejects duplicate item names (same company, case-insensitive) to avoid duplicates from double-submit.
    """
    if data.pack_size < 1:
        raise ValueError("Pack size must be at least 1")
    if data.can_break_bulk and data.pack_size < 2:
        raise ValueError("Breakable items must have pack_size > 1")

    # Single unit name when pack_size=1: adopt retail_unit everywhere (wholesale = retail)
    if data.pack_size == 1:
        single_name = (data.retail_unit or data.wholesale_unit or "piece").strip() or "piece"
        single_name = _sanitize_base_unit(single_name, "piece")
        dump = data.model_dump(exclude={"units", "company_id"}) if hasattr(data, "model_dump") else data.dict(exclude={"units", "company_id"})
        dump["wholesale_unit"] = single_name
        dump["retail_unit"] = single_name
        if (data.wholesale_units_per_supplier or 1) <= 1:
            dump["supplier_unit"] = single_name
        elif (data.supplier_unit or "").strip().lower() == single_name.lower():
            raise ValueError("When wholesale_units_per_supplier > 1, supplier unit name must differ from wholesale/retail (e.g. 'case' vs 'tube')")
    else:
        dump = data.model_dump(exclude={"units", "company_id"}) if hasattr(data, "model_dump") else data.dict(exclude={"units", "company_id"})
        if data.can_break_bulk and (data.retail_unit or "").strip().lower() == (data.wholesale_unit or "").strip().lower():
            raise ValueError("When can break bulk and pack_size > 1, retail unit and wholesale unit must have different names (e.g. tablet vs packet)")

    dump["company_id"] = data.company_id
    name_normalized = (data.name or "").strip()
    if name_normalized:
        existing = (
            db.query(Item)
            .filter(
                Item.company_id == data.company_id,
                func.lower(Item.name) == name_normalized.lower(),
            )
            .first()
        )
        if existing:
            raise DuplicateItemNameError(name=name_normalized, company_id=data.company_id)

    if not dump.get("sku") or (isinstance(dump.get("sku"), str) and not dump["sku"].strip()):
        sku = _generate_sku(data.company_id, db)
        while db.query(Item).filter(Item.company_id == data.company_id, Item.sku == sku).first():
            m = re.match(r"^([A-Z]{1,3})(\d+)$", sku.upper())
            n = int(m.group(2)) + 1 if m else 1
            sku = f"A{n:05d}"
        dump["sku"] = sku

    # Never persist a number as base_unit (e.g. price column mapped by mistake)
    dump["base_unit"] = _sanitize_base_unit(dump.get("base_unit"), data.wholesale_unit or "piece")
    # Do not persist deprecated price fields — cost from inventory_ledger only
    for key in ("default_cost", "purchase_price_per_supplier_unit", "wholesale_price_per_wholesale_unit", "retail_price_per_retail_unit"):
        dump.pop(key, None)

    db_item = Item(**dump)
    db.add(db_item)
    db.flush()
    return db_item


def update_item(db: Session, item_id: UUID, data: ItemUpdate) -> Item | None:
    """Update item; apply 3-tier fields when provided."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return None

    dump = data.model_dump(exclude_unset=True, exclude={"units"}) if hasattr(data, "model_dump") else data.dict(exclude_unset=True, exclude={"units"})

    if "can_break_bulk" in dump and "pack_size" not in dump:
        pack = getattr(item, "pack_size", 1) or 1
        if dump["can_break_bulk"] and pack < 2:
            raise ValueError("Breakable items must have pack_size > 1")
    if "pack_size" in dump and "can_break_bulk" not in dump:
        cb = getattr(item, "can_break_bulk", False)
        if cb and dump["pack_size"] < 2:
            raise ValueError("Breakable items must have pack_size > 1")
    if "can_break_bulk" in dump and "pack_size" in dump:
        if dump["can_break_bulk"] and dump["pack_size"] < 2:
            raise ValueError("Breakable items must have pack_size > 1")

    # Resolve effective pack_size and wholesale_units_per_supplier for unit rules
    pack_size = dump.get("pack_size", getattr(item, "pack_size", 1)) or 1
    wups = dump.get("wholesale_units_per_supplier", getattr(item, "wholesale_units_per_supplier", 1)) or 1
    try:
        wups = float(wups)
    except (TypeError, ValueError):
        wups = 1

    # Single unit name when pack_size=1: adopt one name everywhere (wholesale = retail)
    if pack_size == 1:
        single_name = (dump.get("retail_unit") or dump.get("wholesale_unit") or item.retail_unit or item.wholesale_unit or "piece")
        single_name = _sanitize_base_unit(single_name, "piece")
        dump["wholesale_unit"] = single_name
        dump["retail_unit"] = single_name
        if wups <= 1:
            dump["supplier_unit"] = single_name
        elif (dump.get("supplier_unit") or getattr(item, "supplier_unit", "") or "").strip().lower() == single_name.lower():
            raise ValueError("When wholesale_units_per_supplier > 1, supplier unit name must differ from wholesale/retail (e.g. 'case' vs 'tube')")
    else:
        # Break bulk: enforce different retail vs wholesale names
        retail = (dump.get("retail_unit") or getattr(item, "retail_unit", "") or "").strip().lower()
        wholesale = (dump.get("wholesale_unit") or getattr(item, "wholesale_unit", "") or "").strip().lower()
        if dump.get("can_break_bulk", getattr(item, "can_break_bulk", False)) and retail == wholesale:
            raise ValueError("When can break bulk and pack_size > 1, retail unit and wholesale unit must have different names (e.g. tablet vs packet)")

    # Never persist a number as unit names
    if "base_unit" in dump:
        dump["base_unit"] = _sanitize_base_unit(dump["base_unit"], dump.get("wholesale_unit") or item.wholesale_unit or "piece")
    if "wholesale_unit" in dump:
        dump["wholesale_unit"] = _sanitize_base_unit(dump["wholesale_unit"], "piece")
    if "retail_unit" in dump:
        dump["retail_unit"] = _sanitize_base_unit(dump["retail_unit"], "tablet")
    if "supplier_unit" in dump:
        dump["supplier_unit"] = _sanitize_base_unit(dump["supplier_unit"], "packet")

    for k, v in dump.items():
        setattr(item, k, v)

    # Units are item characteristics (columns on items table only). No separate units list to persist.
    db.flush()
    return item
