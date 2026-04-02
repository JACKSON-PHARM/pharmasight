"""
eTIMS sales line snapshot at batch time + immutability rules.

No KRA HTTP. Populates line-level codes from map_vat_to_etims_category and optional
item master KRA columns; sets invoice.submission_status = pending.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session as OrmSession

from app.services.etims.codes_service import map_vat_to_etims_category

logger = logging.getLogger(__name__)

ETIMS_LINE_SNAPSHOT_COLS = (
    "vat_cat_cd",
    "tax_ty_cd",
    "item_cls_cd",
    "pkg_unit_cd",
    "qty_unit_cd",
)

_GUARDS_REGISTERED = False


class EtimsSnapshotImmutableError(Exception):
    """Raised when a caller tries to mutate invoice lines after eTIMS snapshot is locked."""


def _norm_optional_str(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def apply_etims_snapshots_on_batch(invoice) -> None:
    """
    Set line-level eTIMS snapshot fields from VAT mapping + item KRA columns,
    then mark invoice for async KRA submission.
    """
    for line in invoice.items:
        item = line.item
        mapping = map_vat_to_etims_category(
            vat_category=getattr(item, "vat_category", None) if item else None,
            vat_rate_percent=float(line.vat_rate or 0),
        )
        line.vat_cat_cd = mapping.vat_cat_cd
        item_tax = _norm_optional_str(getattr(item, "kra_tax_ty_cd", None) if item else None)
        line.tax_ty_cd = item_tax or mapping.tax_ty_cd
        line.item_cls_cd = _norm_optional_str(getattr(item, "kra_item_cls_cd", None) if item else None)
        line.pkg_unit_cd = _norm_optional_str(getattr(item, "kra_pkg_unit_cd", None) if item else None)
        line.qty_unit_cd = _norm_optional_str(getattr(item, "kra_qty_unit_cd", None) if item else None)

    invoice.submission_status = "pending"


def ensure_invoice_etims_lines_mutable(invoice) -> None:
    """
    API-layer guard: refuse line mutations when submission_status is already set.
    """
    st = getattr(invoice, "submission_status", None)
    if st is not None and str(st).strip() != "":
        raise EtimsSnapshotImmutableError(
            "Cannot modify this invoice's lines: eTIMS submission state is already recorded (submission_status is set)."
        )


def _invoice_submission_loaded_value(invoice) -> Optional[object]:
    """submission_status as of last load from DB (not in-memory-only updates in same flush)."""
    try:
        ins = sa_inspect(invoice)
        return ins.attrs.submission_status.loaded_value
    except Exception:
        return None


def _guard_sales_invoice_submitted_immutable(obj) -> None:
    """After successful KRA submit, invoice header is frozen in the ORM."""
    from sqlalchemy.exc import InvalidRequestError

    from app.models.sale import SalesInvoice

    if not isinstance(obj, SalesInvoice):
        return
    insp = sa_inspect(obj)
    loaded_sub = insp.attrs.submission_status.loaded_value
    if str(loaded_sub or "") != "submitted":
        return
    allow = frozenset({"updated_at"})
    for col in obj.__table__.columns.keys():
        if col in allow:
            continue
        try:
            hist = insp.attrs[col].history
        except Exception:
            continue
        if hist.has_changes():
            raise InvalidRequestError(
                f"Submitted eTIMS sales invoice is immutable (blocked change to {col!r})."
            ) from None


def _before_flush_guard(session: OrmSession, flush_context, instances) -> None:
    from app.models.sale import SalesInvoiceItem, SalesInvoice

    for obj in list(session.dirty):
        if isinstance(obj, SalesInvoice):
            _guard_sales_invoice_submitted_immutable(obj)
            continue
        if not isinstance(obj, SalesInvoiceItem):
            continue

        inv = obj.sales_invoice
        if inv is None and obj.sales_invoice_id is not None:
            inv = session.get(SalesInvoice, obj.sales_invoice_id)
        if inv is None:
            continue

        loaded_sub = _invoice_submission_loaded_value(inv)
        if loaded_sub is None:
            continue

        insp = sa_inspect(obj)
        for col in ETIMS_LINE_SNAPSHOT_COLS:
            try:
                hist = insp.attrs[col].history
            except Exception:
                continue
            if hist.has_changes():
                from sqlalchemy.exc import InvalidRequestError

                raise InvalidRequestError(
                    f"Cannot modify eTIMS line snapshot field {col!r} after invoice submission_status is set."
                ) from None


def register_etims_invoice_orm_guards() -> None:
    """Idempotent: register SQLAlchemy before_flush immutability for SalesInvoiceItem."""
    global _GUARDS_REGISTERED
    if _GUARDS_REGISTERED:
        return
    event.listen(OrmSession, "before_flush", _before_flush_guard, propagate=True)
    _GUARDS_REGISTERED = True
    logger.debug("eTIMS SalesInvoiceItem ORM snapshot guard registered")
