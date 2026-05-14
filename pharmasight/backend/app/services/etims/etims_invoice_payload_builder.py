"""
Build KRA OSCU sales payloads from batched SalesInvoice + lines.

Primary submission uses ``POST /saveTrnsSalesOsdc`` (OSDC): ``itemList`` plus header buckets
``taxblAmtA``–``taxblAmtE``, matching ``gavaetims.py`` / ``kra_certify.py``.

Legacy ``sendSalesTransaction`` / ``salesTrnsItems`` remains available via
``build_send_sales_trns_payload`` if needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.item_units_helper import get_stock_display_unit, get_unit_multiplier_from_item

from app.services.etims.codes_service import (
    OSCU_TAX_TY_ZERO,
    map_item_master_vat_to_etims_category,
    map_vat_to_etims_category,
)

logger = logging.getLogger(__name__)


def _f(x: Optional[Decimal]) -> float:
    if x is None:
        return 0.0
    return float(x)


def _norm_tax_ty_cd(val: object | None) -> str:
    """Match gavaetims: OSCU taxTyCd is typically a short letter/digit code."""
    if val is None:
        return ""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        s = str(int(val))
        return s.strip().upper() if s else ""
    return str(val).strip().upper()


def _item_cd(item) -> str:
    """KRA ``itemCd``: strictly ``items.kra_item_code`` only."""
    if item is None:
        raise ValueError("KRA itemCd missing: invoice line has no linked item.")
    kra_code = str(getattr(item, "kra_item_code", None) or "").strip().upper()
    if kra_code:
        logger.info(
            "kra_item_code_usage op=sales_payload_line item_id=%s stored_code=%s used_code=%s",
            getattr(item, "id", None),
            kra_code,
            kra_code[:50],
        )
        return kra_code[:50]
    raise ValueError(
        f"KRA itemCd missing on item_id={getattr(item, 'id', None)}. "
        "Run explicit 'Sync to KRA now' or 'Refresh codes from KRA catalog' first."
    )


def _invoice_no_as_int(invoice_no: str) -> int:
    s = str(invoice_no or "").strip()
    digits = "".join(re.findall(r"\d+", s))
    if digits:
        return int(digits)
    return 0


def _norm_qty_unit_sale(v: object | None) -> str:
    """Match item_sync_service: default / ``U`` → ``TU`` for KRA qty unit."""
    s = str(v or "").strip().upper()
    if not s or s == "U":
        return "TU"
    return s


def _norm_pkg_unit_sale(v: object | None) -> str:
    s = str(v or "").strip().upper()
    return s if s else "NT"


def _line_is_effectively_zero_rated(line: Any) -> bool:
    """POS line has no VAT component (excl. rounding quirks)."""
    return float(_f(getattr(line, "vat_rate", None))) == 0.0 and float(_f(getattr(line, "vat_amount", None))) == 0.0


def _mapping_for_etims_sale_line(item: Any, line: Any) -> Any:
    """Item master VAT when linked to a product; else fall back to line-only (orphan lines)."""
    if item is not None:
        return map_item_master_vat_to_etims_category(item)
    return map_vat_to_etims_category(vat_category=None, vat_rate_percent=float(getattr(line, "vat_rate", None) or 0))


def _resolve_sales_tax_ty_cd(*, item: Any, line: Any) -> str:
    """
    ``taxTyCd`` on the sale payload follows **PharmaSight VAT** (same as batch snapshot), not ad-hoc swaps
    against KRA at submit time. KRA item master must be aligned first via ``saveItem``/sync (see submitter
    guard); that keeps returns consistent and avoids silent B/C flips on the wire.

    Stale line snapshots may still say ``B`` for historic zero-rated rows; coerce those to mapping.
    """
    line_tty = _norm_tax_ty_cd(getattr(line, "tax_ty_cd", None))
    mapping = (
        _mapping_for_etims_sale_line(item, line)
        if item is not None
        else map_vat_to_etims_category(vat_category=None, vat_rate_percent=float(line.vat_rate or 0))
    )
    tax_ty = mapping.tax_ty_cd if item is not None else (line_tty or mapping.tax_ty_cd)
    if not tax_ty:
        tax_ty = line_tty
    if tax_ty == "B" and _line_is_effectively_zero_rated(line):
        tax_ty = mapping.tax_ty_cd
    return tax_ty


def _stock_io_line_amounts_for_tax_ty(*, unit_prc: float, qty: float, tax_ty_cd: str) -> tuple[float, float, float, float]:
    """
    Mirror ``stock_io_line_amounts_for_tax_ty`` in ``gavaetims.py`` (used by ``saveInvoice`` / OSDC).

    ``taxTyCd`` **B** = VAT-inclusive gross supply; amounts split /1.16. Any other letter uses exclusive-style
    amounts with **taxAmt = 0** on the line (VAT buckets may still aggregate at header level per OSDC rules).
    Returns ``(splyAmt, taxblAmt, taxAmt, totAmt)``.
    """
    tty = str(tax_ty_cd or "").strip().upper()
    sply = round(float(unit_prc * qty), 2)
    if tty == "B":
        taxbl = round(sply / 1.16, 2)
        tax_amt = round(sply - taxbl, 2)
        return sply, taxbl, tax_amt, sply
    return sply, sply, 0.0, sply


def _use_osdc_inclusive_supply_split(*, tax_ty: str, _line: Any) -> bool:
    """
    gavaetims ``stock_io_line_amounts_for_tax_ty``: taxTyCd ``B`` = VAT-*inclusive* gross supply (/1.16).

    PharmaSight VAT mapping no longer emits ``taxTyCd`` ``B`` for zero-rated rows (that uses ``C``).
    If ``selectItemList`` / trusted master says ``B``, always use inclusive gross math — otherwise amounts
    disagree with KRA item validation even when POS ``vat_amount`` is 0 (inclusive-priced SKU).
    """
    return str(tax_ty or "").strip().upper() == "B"


def _org_invc_no_int(org_invc_no: object | None) -> int:
    """KRA expects a numeric original invoice reference; use 0 for normal sales (see gava / kra_certify)."""
    if org_invc_no is None:
        return 0
    s = str(org_invc_no).strip()
    if s.isdigit():
        return int(s)
    return 0


def _sales_calendar_dt_yyyymmdd(invoice: Any) -> str:
    d = getattr(invoice, "invoice_date", None)
    if d is None:
        return datetime.now(timezone.utc).strftime("%Y%m%d")
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    return str(d).replace("-", "")[:8]


def _utc_cfm_dt_14() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _bucket_key_for_tax_ty(tax_ty_cd: str) -> str:
    t = str(tax_ty_cd or "").strip().upper()
    if t in ("A", "B", "C", "D", "E"):
        return t
    return "A"


def _aggregate_osdc_buckets(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, float], Dict[str, float]]:
    taxbl = {k: 0.0 for k in ("A", "B", "C", "D", "E")}
    taxam = {k: 0.0 for k in ("A", "B", "C", "D", "E")}
    for row in rows:
        b = _bucket_key_for_tax_ty(str(row.get("taxTyCd") or ""))
        taxbl[b] += float(row.get("taxblAmt") or 0.0)
        taxam[b] += float(row.get("taxAmt") or 0.0)
    for k in taxbl:
        taxbl[k] = round(taxbl[k], 2)
        taxam[k] = round(taxam[k], 2)
    return taxbl, taxam


# After ``saveInvoice`` bucket totals, ``gavaetims`` applies ``apply_link_tax_rt_to_purchase_payload`` with this
# map (or a supplier sale-row snapshot). KRA rule ``taxRtB`` expects **16.0** here even when every line is
# ``taxTyCd`` ``C`` and ``taxblAmtB`` is 0 — deriving ``taxRtB`` from an empty B bucket yields 0.0 and OSDC
# returns: ``Validation failed | Rule taxRtB failed: Tax rate mismatch. Expected: 16.00, Found: 0.0``.
_KE_OSDC_SAVE_INVOICE_HEADER_TAX_RT: Dict[str, float] = {
    "taxRtA": 0.0,
    "taxRtB": 16.0,
    "taxRtC": 0.0,
    "taxRtD": 0.0,
    "taxRtE": 0.0,
}


def build_sales_trns_line_rows(invoice_items: List[Any], *, db: Any | None = None) -> List[Dict[str, Any]]:
    """
    One OSDC / sales-transaction row per invoice line (``itemList`` / ``salesTrnsItems``).

    Amounts, ``taxTyCd``, and ``vatCatCd`` follow PharmaSight item-master VAT (``_mapping_for_etims_sale_line`` /
    ``codes_service``), aligned with ``saveItem`` / stock IO conventions.

    When ``db`` is set, ``qty`` (and ``prc``) are converted to **inventory base (retail) units** — the same basis
    as ``insertStockIO`` / ``saveStockMaster`` — so monetary totals match. Without ``db``, legacy behaviour uses
    POS line quantity as ``qty`` (sale units only).

    **OSDC / ``saveTrnsSalesOsdc``:** KRA validates ``itemList[].pkg`` against the item master (see gavaetims
    ``saveInvoice`` step: ``pkg`` is **1.0** per line; the sold count lives in ``qty``). Sending ``pkg`` equal
    to the sale quantity triggers ``Invalid pkg … Expected: 1, Found: N``.
    """
    from app.services.inventory_service import InventoryService

    rows: List[Dict[str, Any]] = []
    for item_seq, line in enumerate(invoice_items, start=1):
        it = getattr(line, "item", None)
        item_cd = _item_cd(it)
        item_nm = (getattr(line, "item_name", None) or (it.name if it else None) or item_cd)[:200]
        qty_sale = _f(getattr(line, "quantity", None))
        prc_sale = _f(getattr(line, "unit_price_exclusive", None))
        qty = qty_sale
        prc = prc_sale
        if db is not None and it is not None and getattr(line, "item_id", None):
            unit_nm = (getattr(line, "unit_name", None) or "").strip()
            if not unit_nm:
                unit_nm = str(
                    getattr(it, "retail_unit", None)
                    or getattr(it, "wholesale_unit", None)
                    or getattr(it, "supplier_unit", None)
                    or "piece"
                ).strip() or "piece"
            # POS may store a label that is not one of the three tier names; mirror get_unit_display_short fallback.
            eff_unit = unit_nm
            if get_unit_multiplier_from_item(it, eff_unit) is None:
                eff_unit = get_stock_display_unit(it)
                if get_unit_multiplier_from_item(it, eff_unit) is None:
                    eff_unit = str(
                        getattr(it, "retail_unit", None)
                        or getattr(it, "wholesale_unit", None)
                        or "piece"
                    ).strip() or "piece"
            try:
                qty_base = float(
                    InventoryService.convert_to_base_units(db, line.item_id, float(qty_sale), eff_unit)
                )
                mult = (qty_base / float(qty_sale)) if abs(float(qty_sale)) > 1e-9 else 1.0
                if qty_base > 0 and mult > 0:
                    qty = round(qty_base, 4)
                    prc = round(prc_sale / mult, 6)
            except Exception as ex:
                logger.warning(
                    "sales_osdc_line_qty_staying_sale_unit item_id=%s unit=%s eff_unit=%s qty_sale=%s: %s",
                    getattr(line, "item_id", None),
                    unit_nm,
                    eff_unit,
                    qty_sale,
                    ex,
                )
        sply = _f(getattr(line, "line_total_exclusive", None))
        dc_rt = _f(getattr(line, "discount_percent", None))
        dc_amt = _f(getattr(line, "discount_amount", None))
        tax_ty = _resolve_sales_tax_ty_cd(item=it, line=line)
        if not tax_ty:
            raise ValueError("Line missing tax_ty_cd (eTIMS snapshot required before submit)")
        mapping = _mapping_for_etims_sale_line(it, line)
        tot_li = getattr(line, "line_total_inclusive", None)
        if _use_osdc_inclusive_supply_split(tax_ty=tax_ty, _line=line):
            sply_amt = round(_f(tot_li) if tot_li is not None else (prc * qty), 2)
            taxbl = round(sply_amt / 1.16, 2)
            tax_amt = round(sply_amt - taxbl, 2)
            tot = sply_amt
        elif mapping.tax_ty_cd == OSCU_TAX_TY_ZERO:
            sply_amt, taxbl, tax_amt, tot = _stock_io_line_amounts_for_tax_ty(
                unit_prc=prc, qty=qty, tax_ty_cd=tax_ty
            )
        else:
            tax_amt = round(_f(getattr(line, "vat_amount", None)), 2)
            taxbl = round(sply, 2)
            sply_amt = taxbl
            tot = round(_f(tot_li) if tot_li is not None else (taxbl + tax_amt), 2)
        vcd = str(getattr(mapping, "vat_cat_cd", None) or "").strip().upper()
        row: Dict[str, Any] = {
            "itemSeq": item_seq,
            "itemCd": item_cd,
            "itemNm": item_nm,
            # KRA saveTrnsSalesOsdc: pkg is the package count per line (1 for normal retail); qty is TU count.
            "pkg": 1.0,
            "qty": float(qty),
            "prc": round(prc, 2),
            "splyAmt": sply_amt,
            "dcRt": dc_rt,
            "dcAmt": dc_amt,
            "taxTyCd": tax_ty,
            "vatCatCd": vcd,
            "taxblAmt": taxbl,
            "taxAmt": tax_amt,
            "totAmt": tot,
        }
        icls_item = (getattr(it, "kra_item_cls_cd", None) or "").strip() if it else ""
        icls_line = (getattr(line, "item_cls_cd", None) or "").strip()
        icls = icls_item or icls_line
        if icls:
            row["itemClsCd"] = icls
        pkg_unit = ""
        if it:
            pkg_unit = (getattr(it, "kra_pkg_unit_cd", None) or "").strip()
        if not pkg_unit:
            pkg_unit = (getattr(line, "pkg_unit_cd", None) or "").strip()
        row["pkgUnitCd"] = _norm_pkg_unit_sale(pkg_unit)
        q_raw = (getattr(it, "kra_qty_unit_cd", None) or "").strip() if it else ""
        if not q_raw:
            q_raw = (getattr(line, "qty_unit_cd", None) or "").strip()
        row["qtyUnitCd"] = _norm_qty_unit_sale(q_raw)
        rows.append(row)
    return rows


def build_save_trns_sales_osdc_payload(
    *,
    tin: str,
    bhf_id: str,
    invoice: Any,
    invoice_items: List[Any],
    sales_ty_cd: str = "N",
    rcpt_ty_cd: str = "S",
    pmt_ty_cd: str = "01",
    reg_ty_cd: str = "M",
    trd_invc_no: Optional[str] = None,
    org_invc_no: object | None = 0,
    sales_stts_cd: str = "02",
    regr_id: str = "system",
    regr_nm: str = "system",
    modr_id: str = "system",
    modr_nm: str = "system",
    db: Any | None = None,
    osdc_invc_no: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Full ``saveTrnsSalesOsdc`` JSON body (``kra_certify.step_saveInvoice`` / ``gavaetims`` contract).

    ``osdc_invc_no``: KRA monotonic ``invcNo`` / ``requestedInvcNo`` (per branch, from
    ``branch_etims_credentials.kra_osdc_next_invc_no``). Do **not** use POS ``invoice_no`` digits here — KRA
    rejects gaps (e.g. ``INV-HQ-000014`` → 14 when KRA expects 1).

    Customer PIN rule (gava): if no ``custTin``, omit ``custTin``/``custNm`` at root and inside ``receipt``.
    """
    tin_s = (tin or "").strip()
    bhf_s = (bhf_id or "").strip()
    if osdc_invc_no is not None:
        n = int(osdc_invc_no)
        if n < 1:
            n = 1
        invc_body = str(n)
    else:
        inv_no_int = _invoice_no_as_int(getattr(invoice, "invoice_no", None) or "")
        invc_body = str(inv_no_int) if inv_no_int else "1"
    trd = str(trd_invc_no if trd_invc_no is not None else getattr(invoice, "invoice_no", None) or "").strip()
    if not trd:
        trd = invc_body
    trd = trd[:50]

    rows = build_sales_trns_line_rows(invoice_items, db=db)
    if not rows:
        raise ValueError("Invoice has no lines for saveTrnsSalesOsdc")

    taxbl_bk, taxam_bk = _aggregate_osdc_buckets(rows)
    tot_taxbl = round(sum(taxbl_bk.values()), 2)
    tot_tax = round(sum(taxam_bk.values()), 2)
    tot_amt_lines = round(sum(float(r.get("totAmt") or 0.0) for r in rows), 2)

    cfm_dt = _utc_cfm_dt_14()
    sales_dt = _sales_calendar_dt_yyyymmdd(invoice)

    payload: Dict[str, Any] = {
        "tin": tin_s,
        "bhfId": bhf_s,
        "regTyCd": (reg_ty_cd or "M").strip(),
        "salesTyCd": (sales_ty_cd or "N").strip(),
        "rcptTyCd": (rcpt_ty_cd or "S").strip(),
        "pmtTyCd": (pmt_ty_cd or "01").strip(),
        "trdInvcNo": trd,
        "invcNo": invc_body,
        "requestedInvcNo": invc_body,
        "orgInvcNo": str(_org_invc_no_int(org_invc_no)),
        "salesSttsCd": (sales_stts_cd or "02").strip(),
        "cfmDt": cfm_dt,
        "salesDt": sales_dt,
        "stockRlsDt": cfm_dt,
        "totItemCnt": len(rows),
        "taxblAmtA": taxbl_bk["A"],
        "taxblAmtB": taxbl_bk["B"],
        "taxblAmtC": taxbl_bk["C"],
        "taxblAmtD": taxbl_bk["D"],
        "taxblAmtE": taxbl_bk["E"],
        **_KE_OSDC_SAVE_INVOICE_HEADER_TAX_RT,
        "taxAmtA": taxam_bk["A"],
        "taxAmtB": taxam_bk["B"],
        "taxAmtC": taxam_bk["C"],
        "taxAmtD": taxam_bk["D"],
        "taxAmtE": taxam_bk["E"],
        "totTaxblAmt": tot_taxbl,
        "totTaxAmt": tot_tax,
        "totAmt": tot_amt_lines,
        "prchrAcptcYn": "N",
        "regrId": regr_id,
        "regrNm": regr_nm,
        "modrId": modr_id,
        "modrNm": modr_nm,
        "itemList": rows,
    }

    receipt: Dict[str, Any] = {"rcptPbctDt": cfm_dt, "prchrAcptcYn": "N"}
    cust_pin = str(getattr(invoice, "customer_pin", None) or "").strip()
    cust_nm = str(getattr(invoice, "customer_name", None) or "").strip()
    if cust_pin:
        payload["custTin"] = cust_pin
        payload["custNm"] = (cust_nm or "Customer")[:200]
        receipt["custTin"] = cust_pin
        if cust_nm:
            receipt["custNm"] = cust_nm[:200]
    payload["receipt"] = receipt

    return payload


def build_send_sales_trns_payload(
    *,
    tin: str,
    bhf_id: str,
    invoice_no: str,
    invoice_items: List[Any],
    sales_ty_cd: str = "N",
    rcpt_ty_cd: str = "S",
    pmt_ty_cd: str = "01",
    reg_ty_cd: str = "M",
    trd_invc_no: Optional[str] = None,
    org_invc_no: object | None = 0,
) -> Dict[str, Any]:
    """
    `invoice_items` must be SalesInvoiceItem rows with `.item` loaded where possible.

    KRA `SalesTransactionInformation` requires receipt/payment codes and invoice linkage fields
    (`orgInvcNo`, `trdInvcNo`, etc.); defaults match working flows in `gavaetims.py` / `kra_certify.py`.
    """
    tin_s = (tin or "").strip()
    bhf_s = (bhf_id or "").strip()
    invc = _invoice_no_as_int(invoice_no)
    trd = str(trd_invc_no if trd_invc_no is not None else invoice_no or "").strip()
    if not trd:
        trd = str(invc)
    trd = trd[:50]
    rows = build_sales_trns_line_rows(invoice_items)

    return {
        "tin": tin_s,
        "bhfId": bhf_s,
        "regTyCd": (reg_ty_cd or "M").strip(),
        "salesTyCd": (sales_ty_cd or "N").strip(),
        "rcptTyCd": (rcpt_ty_cd or "S").strip(),
        "pmtTyCd": (pmt_ty_cd or "01").strip(),
        "trdInvcNo": trd,
        "invcNo": invc,
        "orgInvcNo": _org_invc_no_int(org_invc_no),
        "salesTrnsItems": rows,
    }


