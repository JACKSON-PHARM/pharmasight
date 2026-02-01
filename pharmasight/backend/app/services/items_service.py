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

from sqlalchemy.orm import Session

from app.models import Item, ItemUnit
from app.schemas.item import ItemCreate, ItemUpdate

logger = logging.getLogger(__name__)


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


def _ensure_units_from_3tier(db: Session, item: Item, data: ItemCreate) -> None:
    """Create item_units from 3-tier when `units` list is empty. Base = wholesale (multiplier 1)."""
    if data.units:
        return
    wups = max(Decimal("0.0001"), Decimal(str(getattr(data, "wholesale_units_per_supplier", 1) or 1)))
    pack = max(1, data.pack_size)
    existing = {}
    # Wholesale = base (1 per item)
    if data.wholesale_unit not in existing:
        u = ItemUnit(
            item_id=item.id,
            unit_name=data.wholesale_unit,
            multiplier_to_base=Decimal("1"),
            is_default=True,
        )
        db.add(u)
        existing[data.wholesale_unit] = u
    # Retail: 1 retail = 1/pack_size base (wholesale)
    if data.retail_unit not in existing and pack >= 1:
        mult = Decimal("1") / Decimal(str(pack))
        u = ItemUnit(
            item_id=item.id,
            unit_name=data.retail_unit,
            multiplier_to_base=mult,
            is_default=False,
        )
        db.add(u)
        existing[data.retail_unit] = u
    # Supplier: 1 supplier = wholesale_units_per_supplier base (wholesale)
    if data.supplier_unit not in existing and wups > 0:
        u = ItemUnit(
            item_id=item.id,
            unit_name=data.supplier_unit,
            multiplier_to_base=wups,
            is_default=False,
        )
        db.add(u)
        existing[data.supplier_unit] = u


def create_item(db: Session, data: ItemCreate) -> Item:
    """
    Create item with 3-tier units.

    - Validates pack_size >= 1 and breakable => pack_size > 1 (done in schema).
    - Sets base_unit = wholesale_unit (reference), default_cost = purchase_price_per_supplier_unit.
    - Builds item_units from 3-tier when `units` is empty.
    """
    if data.pack_size < 1:
        raise ValueError("Pack size must be at least 1")
    if data.can_break_bulk and data.pack_size < 2:
        raise ValueError("Breakable items must have pack_size > 1")

    dump = data.model_dump(exclude={"units", "company_id"}) if hasattr(data, "model_dump") else data.dict(exclude={"units", "company_id"})
    dump["company_id"] = data.company_id

    if not dump.get("sku") or (isinstance(dump.get("sku"), str) and not dump["sku"].strip()):
        sku = _generate_sku(data.company_id, db)
        while db.query(Item).filter(Item.company_id == data.company_id, Item.sku == sku).first():
            m = re.match(r"^([A-Z]{1,3})(\d+)$", sku.upper())
            n = int(m.group(2)) + 1 if m else 1
            sku = f"A{n:05d}"
        dump["sku"] = sku

    # Never persist a number as base_unit (e.g. price column mapped by mistake)
    dump["base_unit"] = _sanitize_base_unit(dump.get("base_unit"), data.wholesale_unit or "piece")
    dump["default_cost"] = dump.get("default_cost")
    if dump["default_cost"] is None:
        dump["default_cost"] = data.purchase_price_per_supplier_unit
    if data.vat_category:
        dump["vat_code"] = dump.get("vat_code") or data.vat_category

    db_item = Item(**dump)
    db.add(db_item)
    db.flush()

    if data.units:
        for u in data.units:
            d = u.model_dump() if hasattr(u, "model_dump") else u.dict()
            db_unit = ItemUnit(item_id=db_item.id, **d)
            db.add(db_unit)
        base_in_units = any(u.unit_name == db_item.base_unit for u in data.units)
        if not base_in_units:
            db.add(
                ItemUnit(
                    item_id=db_item.id,
                    unit_name=db_item.base_unit,
                    multiplier_to_base=Decimal("1"),
                    is_default=True,
                )
            )
    else:
        _ensure_units_from_3tier(db, db_item, data)

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

    # Never persist a number as unit names
    if "base_unit" in dump:
        dump["base_unit"] = _sanitize_base_unit(dump["base_unit"], item.wholesale_unit or "piece")
    if "wholesale_unit" in dump:
        dump["wholesale_unit"] = _sanitize_base_unit(dump["wholesale_unit"], "piece")
    if "retail_unit" in dump:
        dump["retail_unit"] = _sanitize_base_unit(dump["retail_unit"], "tablet")
    if "supplier_unit" in dump:
        dump["supplier_unit"] = _sanitize_base_unit(dump["supplier_unit"], "packet")

    for k, v in dump.items():
        setattr(item, k, v)

    if data.units is not None:
        existing = {str(u.id): u for u in db.query(ItemUnit).filter(ItemUnit.item_id == item_id).all()}
        seen = set()
        for u in data.units:
            ud = u.model_dump() if hasattr(u, "model_dump") else u.dict()
            uid = ud.pop("id", None)
            if uid and str(uid) in existing:
                existing[str(uid)].unit_name = ud["unit_name"]
                existing[str(uid)].multiplier_to_base = ud["multiplier_to_base"]
                existing[str(uid)].is_default = ud["is_default"]
                seen.add(str(uid))
            else:
                db.add(ItemUnit(item_id=item_id, **ud))
        for kid, u in list(existing.items()):
            if kid not in seen:
                db.delete(u)

    db.flush()
    return item
