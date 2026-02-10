"""
Document line-item helpers: ensure no duplicate (item_id + unit) when saving documents.
Duplicates are merged by summing quantity and keeping the first price/discount.
"""
from decimal import Decimal
from typing import Dict, List, Tuple

from app.schemas.sale import QuotationItemCreate, SalesInvoiceItemCreate


def deduplicate_quotation_items(items: List[QuotationItemCreate]) -> List[QuotationItemCreate]:
    """
    Remove duplicates by (item_id, unit_name). Same item+unit is merged:
    quantities summed, first unit_price_exclusive and discount_percent kept.
    Order of first occurrence is preserved.
    """
    if not items:
        return items
    seen: Dict[Tuple, QuotationItemCreate] = {}
    for it in items:
        key = (it.item_id, it.unit_name)
        if key not in seen:
            seen[key] = it
        else:
            first = seen[key]
            q = Decimal(str(first.quantity)) + Decimal(str(it.quantity))
            seen[key] = QuotationItemCreate(
                item_id=first.item_id,
                unit_name=first.unit_name,
                quantity=q,
                unit_price_exclusive=first.unit_price_exclusive,
                discount_percent=first.discount_percent,
            )
    return list(seen.values())


def deduplicate_sales_invoice_items(items: List[SalesInvoiceItemCreate]) -> List[SalesInvoiceItemCreate]:
    """
    Remove duplicates by (item_id, unit_name). Same item+unit is merged:
    quantities summed, first unit_price_exclusive, discount_percent and discount_amount kept.
    Order of first occurrence is preserved.
    """
    if not items:
        return items
    seen: Dict[Tuple, SalesInvoiceItemCreate] = {}
    for it in items:
        key = (it.item_id, it.unit_name)
        if key not in seen:
            seen[key] = it
        else:
            first = seen[key]
            q = Decimal(str(first.quantity)) + Decimal(str(it.quantity))
            seen[key] = SalesInvoiceItemCreate(
                item_id=first.item_id,
                unit_name=first.unit_name,
                quantity=q,
                unit_price_exclusive=first.unit_price_exclusive,
                discount_percent=first.discount_percent,
                discount_amount=first.discount_amount,
            )
    return list(seen.values())
