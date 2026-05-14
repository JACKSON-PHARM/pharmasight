"""
KRA eTIMS code mapping: PharmaSight item / invoice line VAT → OSCU ``vatCatCd`` + ``taxTyCd``.

Codes are derived **only** from ``vat_category`` and ``vat_rate`` (PharmaSight source of truth), not from env vars.

Kenya OSCU conventions used here (aligned with ``gavaetims.py`` notes):
- ``vatCatCd`` / ``taxTyCd`` are separate dimensions; letter ``B`` as **taxTyCd** means VAT-*inclusive* gross
  in stock/sale helpers — it is **not** used as zero-rated ``taxTyCd``.
- Standard-rated VAT (16%) → ``taxTyCd`` ``A``, ``vatCatCd`` ``A``.
- Zero-rated pharmacy items → ``taxTyCd`` ``C``, ``vatCatCd`` ``D`` (``C`` + ``B`` triggers OSDC ``taxRtB`` / 16% validation failures).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Canonical OSCU defaults when mapping from PharmaSight VAT flags (not configurable via env).
OSCU_VAT_CAT_STANDARD = "A"
OSCU_VAT_CAT_ZERO = "D"
OSCU_TAX_TY_STANDARD = "A"
OSCU_TAX_TY_ZERO = "C"


@dataclass(frozen=True)
class EtimsVatMapping:
    """eTIMS VAT-related codes for one invoice line or item."""

    vat_cat_cd: str
    tax_ty_cd: str


def _normalize_vat_category(vat_category: Optional[str]) -> str:
    if not vat_category:
        return ""
    s = str(vat_category).strip().upper().replace("-", "_").replace(" ", "_")
    # VAT_INCLUSIVE: selling price may include VAT in UX elsewhere; line math in PharmaSight stays excl.
    if s == "VAT_INCLUSIVE":
        return "STANDARD_RATED"
    return s


def map_vat_to_etims_category(
    *,
    vat_category: Optional[str],
    vat_rate_percent: float,
) -> EtimsVatMapping:
    """
    Map PharmaSight classification to eTIMS vatCatCd + taxTyCd.

    Internal categories: ZERO_RATED | STANDARD_RATED | VAT_INCLUSIVE (alias → standard mapping).
    """
    cat = _normalize_vat_category(vat_category)
    rate = float(vat_rate_percent or 0)
    zero = cat == "ZERO_RATED" or rate == 0
    if zero:
        return EtimsVatMapping(vat_cat_cd=OSCU_VAT_CAT_ZERO, tax_ty_cd=OSCU_TAX_TY_ZERO)
    if cat == "STANDARD_RATED" or rate > 0:
        return EtimsVatMapping(vat_cat_cd=OSCU_VAT_CAT_STANDARD, tax_ty_cd=OSCU_TAX_TY_STANDARD)
    return EtimsVatMapping(vat_cat_cd=OSCU_VAT_CAT_ZERO, tax_ty_cd=OSCU_TAX_TY_ZERO)


def map_item_master_vat_to_etims_category(item: Optional[object]) -> EtimsVatMapping:
    """
    Map from ``Item`` master ``vat_category`` + ``vat_rate``.

    KRA ``saveItem`` / catalogue alignment is per product master, not per frozen POS line. Using
    ``sales_invoice_items.vat_rate`` for eTIMS can send the wrong ``taxTyCd`` after the item was corrected to
    zero-rated while old invoice lines still show 16% — KRA then returns misleading ``taxTyCd`` validation errors.
    """
    if item is None:
        return map_vat_to_etims_category(vat_category=None, vat_rate_percent=0.0)
    return map_vat_to_etims_category(
        vat_category=getattr(item, "vat_category", None),
        vat_rate_percent=float(getattr(item, "vat_rate", 0) or 0),
    )
