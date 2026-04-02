"""
KRA eTIMS code mapping: PharmaSight item/line VAT → vatCatCd + taxTyCd.

Defaults follow common OSCU examples (taxTyCd V = VAT, zero-rated B) and are
overridable via settings (ETIMS_VAT_CAT_*, ETIMS_TAX_TY_*) to match sandbox code lists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import settings


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
    zero = cat == "ZERO_RATED" or float(vat_rate_percent or 0) == 0
    if zero:
        return EtimsVatMapping(
            vat_cat_cd=settings.ETIMS_VAT_CAT_ZERO,
            tax_ty_cd=settings.ETIMS_TAX_TY_ZERO,
        )
    if cat == "STANDARD_RATED" or float(vat_rate_percent or 0) > 0:
        return EtimsVatMapping(
            vat_cat_cd=settings.ETIMS_VAT_CAT_STANDARD,
            tax_ty_cd=settings.ETIMS_TAX_TY_STANDARD,
        )
    return EtimsVatMapping(
        vat_cat_cd=settings.ETIMS_VAT_CAT_ZERO,
        tax_ty_cd=settings.ETIMS_TAX_TY_ZERO,
    )
