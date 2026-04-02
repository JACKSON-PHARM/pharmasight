"""
Build KRA OSCU `sendSalesTransaction` JSON body from batched SalesInvoice + lines.

Shape aligns with community eTIMS SDK Joi schema (tin, bhfId, invcNo, salesTrnsItems[]).
Optional `vatCatCd` is included when present on the line snapshot (some API versions accept it).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional


def _f(x: Optional[Decimal]) -> float:
    if x is None:
        return 0.0
    return float(x)


def _item_cd(item) -> str:
    if item is None:
        return "ITEM"
    sku = getattr(item, "sku", None) or ""
    sku = str(sku).strip()
    if sku:
        return sku[:50]
    return str(getattr(item, "id", "") or "").replace("-", "")[:32] or "ITEM"


def build_send_sales_trns_payload(
    *,
    tin: str,
    bhf_id: str,
    invoice_no: str,
    invoice_items: List[Any],
) -> Dict[str, Any]:
    """
    `invoice_items` must be SalesInvoiceItem rows with `.item` loaded where possible.
    """
    tin_s = (tin or "").strip()
    bhf_s = (bhf_id or "").strip()
    invc = (invoice_no or "").strip()[:100]
    rows: List[Dict[str, Any]] = []
    for line in invoice_items:
        it = getattr(line, "item", None)
        item_cd = _item_cd(it)
        item_nm = (getattr(line, "item_name", None) or (it.name if it else None) or item_cd)[:200]
        qty = _f(getattr(line, "quantity", None))
        prc = _f(getattr(line, "unit_price_exclusive", None))
        sply = _f(getattr(line, "line_total_exclusive", None))
        dc_rt = _f(getattr(line, "discount_percent", None))
        dc_amt = _f(getattr(line, "discount_amount", None))
        tax_ty = (getattr(line, "tax_ty_cd", None) or "").strip()
        if not tax_ty:
            raise ValueError("Line missing tax_ty_cd (eTIMS snapshot required before submit)")
        tax_amt = _f(getattr(line, "vat_amount", None))
        row: Dict[str, Any] = {
            "itemCd": item_cd,
            "itemNm": item_nm,
            "qty": qty,
            "prc": prc,
            "splyAmt": sply,
            "dcRt": dc_rt,
            "dcAmt": dc_amt,
            "taxTyCd": tax_ty,
            "taxAmt": tax_amt,
        }
        vcat = (getattr(line, "vat_cat_cd", None) or "").strip()
        if vcat:
            row["vatCatCd"] = vcat
        icls = (getattr(line, "item_cls_cd", None) or "").strip()
        if icls:
            row["itemClsCd"] = icls
        pkg = (getattr(line, "pkg_unit_cd", None) or "").strip()
        if pkg:
            row["pkgUnitCd"] = pkg
        qunit = (getattr(line, "qty_unit_cd", None) or "").strip()
        if qunit:
            row["qtyUnitCd"] = qunit
        rows.append(row)

    return {
        "tin": tin_s,
        "bhfId": bhf_s,
        "invcNo": invc,
        "salesTrnsItems": rows,
    }


