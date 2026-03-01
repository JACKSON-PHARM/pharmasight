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
    Return multiplier to base (retail) for the given unit name.
    Base = retail (smallest unit); 1 base unit = 1 retail (e.g. 1 tablet).
    - retail_unit -> 1
    - wholesale_unit -> pack_size (one pack = pack_size retail)
    - supplier_unit -> pack_size * wholesale_units_per_supplier (one carton = N retail)
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

    if retail and u == retail:
        return Decimal("1")
    if u == wholesale:
        return Decimal(str(pack))
    if supplier and u == supplier:
        return Decimal(str(pack)) * wups
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
    Multiplier is to base (retail): retail->1, wholesale->pack_size, supplier->pack_size*wups.
    """
    if not unit_name or not str(unit_name).strip():
        return None
    u = str(unit_name).strip().lower()
    wholesale = (wholesale_unit or "piece").strip().lower()
    retail = (retail_unit or "").strip().lower()
    supplier = (supplier_unit or "").strip().lower()
    pack = max(1, int(pack_size or 1))
    wups = max(Decimal("0.0001"), Decimal(str(wholesale_units_per_supplier or 1)))

    if retail and u == retail:
        return Decimal("1")
    if u == wholesale:
        return Decimal(str(pack))
    if supplier and u == supplier:
        return Decimal(str(pack)) * wups
    return None


def validate_unit_for_item(item: "Item", unit_name: str) -> Tuple[bool, Optional[Decimal]]:
    """
    Check if unit_name is valid for this item (one of wholesale/retail/supplier).
    Returns (is_valid, multiplier_to_base). multiplier_to_base is None if invalid.
    """
    mult = get_unit_multiplier_from_item(item, unit_name)
    return (mult is not None, mult)


def get_stock_display_unit(item: Optional["Item"], fallback: str = "piece") -> str:
    """
    Unit name to use when labeling numeric stock (base_quantity).
    When pack_size=1 and cannot break bulk, there is only one tier — use that single name everywhere
    (wholesale_unit) so we never show e.g. "13 case" for 13 tubes. Otherwise use retail_unit.
    """
    if not item:
        return (fallback or "piece").strip().lower()
    pack = max(1, int(getattr(item, "pack_size", None) or 1))
    can_break = getattr(item, "can_break_bulk", True)
    if pack == 1 and not can_break:
        # Single unit tier: use one name everywhere (wholesale = retail after enforcement)
        return (item.wholesale_unit or item.base_unit or fallback or "piece").strip().lower()
    return (item.retail_unit or fallback or "piece").strip().lower()


def get_unit_display_short(item: Optional["Item"], unit_name: str) -> str:
    """
    Universal short form for display/printing only. Does not change stored unit_name.
    - P = retail (pieces, tablets, capsules, etc.)
    - W = wholesale (base)
    - S = supplier
    When can_break_bulk is False, return "P" throughout.
    """
    if not item:
        return "P"
    if getattr(item, "can_break_bulk", True) is False:
        return "P"
    u = (unit_name or "").strip().lower()
    wholesale = (item.wholesale_unit or item.base_unit or "piece").strip().lower()
    retail = (item.retail_unit or "").strip().lower()
    supplier = (item.supplier_unit or "").strip().lower()
    # Match wholesale first so e.g. "pack" (1 pack = 100 caps) shows W not P when names differ
    if u == wholesale:
        return "W"
    if retail and u == retail:
        return "P"
    if supplier and u == supplier:
        return "S"
    return "P"
