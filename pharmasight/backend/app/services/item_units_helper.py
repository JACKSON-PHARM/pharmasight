"""
Item units helper – single source of truth: items table only.

Units, conversion rates, and break-bulk are item characteristics defined by
items.supplier_unit, items.wholesale_unit, items.retail_unit, items.pack_size,
items.wholesale_units_per_supplier, items.can_break_bulk. They can only be
updated via create item or update item endpoints. No item_units table.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from app.models.item import Item


def get_unit_multiplier_from_item(item: "Item", unit_name: str) -> Optional[Decimal]:
    """
    Return multiplier to base (wholesale) for the given unit name.
    Base = wholesale_unit; 1 base unit = 1 wholesale.
    - wholesale_unit -> 1
    - retail_unit -> 1/pack_size (one retail = 1/pack_size wholesale)
    - supplier_unit -> wholesale_units_per_supplier (one supplier = N wholesale)
    Returns None if unit_name is not one of the item's three tiers (case-insensitive).
    """
    if not item or not (unit_name and str(unit_name).strip()):
        return None
    u = str(unit_name).strip().lower()
    wholesale = (item.wholesale_unit or item.base_unit or "piece").strip().lower()
    retail = (item.retail_unit or "").strip().lower()
    supplier = (item.supplier_unit or "").strip().lower()
    pack = max(1, int(item.pack_size or 1))
    wups = max(Decimal("0.0001"), Decimal(str(item.wholesale_units_per_supplier or 1)))

    if u == wholesale:
        return Decimal("1")
    if retail and u == retail:
        return Decimal("1") / Decimal(str(pack))
    if supplier and u == supplier:
        return wups
    return None


def get_unit_multiplier_from_item_row(
    *,
    wholesale_unit: str,
    retail_unit: str,
    supplier_unit: str,
    pack_size: int,
    wholesale_units_per_supplier: float,
    unit_name: str,
) -> Optional[Decimal]:
    """
    Same as get_unit_multiplier_from_item but takes scalar values (e.g. from a row or dict).
    """
    if not unit_name or not str(unit_name).strip():
        return None
    u = str(unit_name).strip().lower()
    wholesale = (wholesale_unit or "piece").strip().lower()
    retail = (retail_unit or "").strip().lower()
    supplier = (supplier_unit or "").strip().lower()
    pack = max(1, int(pack_size or 1))
    wups = max(Decimal("0.0001"), Decimal(str(wholesale_units_per_supplier or 1)))

    if u == wholesale:
        return Decimal("1")
    if retail and u == retail:
        return Decimal("1") / Decimal(str(pack))
    if supplier and u == supplier:
        return wups
    return None


def validate_unit_for_item(item: "Item", unit_name: str) -> Tuple[bool, Optional[Decimal]]:
    """
    Check if unit_name is valid for this item (one of wholesale/retail/supplier).
    Returns (is_valid, multiplier_to_base). multiplier_to_base is None if invalid.
    """
    mult = get_unit_multiplier_from_item(item, unit_name)
    return (mult is not None, mult)
