"""
eTIMS sales line snapshot at batch time + immutability rules.

No KRA HTTP. Snapshots use ``Item`` master VAT for ``vat_cat_cd`` / ``tax_ty_cd`` (see ``apply_etims_snapshots_on_batch``).
Class and unit codes come from the item's KRA columns.
Submit-time alignment with KRA catalogue is enforced in ``etims_invoice_submitter.assert_invoice_eligible_for_etims_submit``.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.services.etims.codes_service import map_item_master_vat_to_etims_category, map_vat_to_etims_category

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

    ``vat_cat_cd`` / ``tax_ty_cd`` follow **item master** ``vat_category`` + ``vat_rate`` (not
    ``sales_invoice_items.vat_rate``) so eTIMS codes stay aligned with KRA ``saveItem`` when POS lines are stale.
    Class and unit codes still come from the item's KRA columns.
    """
    for line in invoice.items:
        item = line.item
        mapping = (
            map_item_master_vat_to_etims_category(item)
            if item is not None
            else map_vat_to_etims_category(vat_category=None, vat_rate_percent=float(line.vat_rate or 0))
        )
        line.vat_cat_cd = mapping.vat_cat_cd
        line.tax_ty_cd = mapping.tax_ty_cd

        line.item_cls_cd = _norm_optional_str(getattr(item, "kra_item_cls_cd", None) if item else None)
        line.pkg_unit_cd = _norm_optional_str(getattr(item, "kra_pkg_unit_cd", None) if item else None)
        line.qty_unit_cd = _norm_optional_str(getattr(item, "kra_qty_unit_cd", None) if item else None)

    invoice.submission_status = "pending"


def refresh_etims_snapshots_for_kra_resubmit(db: Session, invoice) -> None:
    """
    Recompute eTIMS line snapshots from current ``Item`` master + KRA columns and clear failed submit headers
    so a batched invoice can be sent to OSDC again (e.g. after fixing ``vatCatCd`` / ``taxTyCd`` mapping).

    Clears ``submission_status`` briefly so the ORM ``before_flush`` guard allows updating snapshot columns
    on ``SalesInvoiceItem``, then sets ``submission_status`` back to ``pending`` via ``apply_etims_snapshots_on_batch``.
    """
    inv_status = (getattr(invoice, "status", None) or "").strip().upper()
    if inv_status not in ("BATCHED", "PAID"):
        raise ValueError("invoice status must be BATCHED or PAID")
    sub = (getattr(invoice, "submission_status", None) or "").strip().lower()
    if sub == "submitted":
        raise ValueError("invoice is already submitted to KRA; cannot refresh snapshots")

    invoice.submission_status = None
    invoice.kra_last_error = None
    invoice.kra_receipt_number = None
    invoice.kra_signature = None
    invoice.kra_qr_code = None
    invoice.kra_submitted_at = None
    db.flush()
    apply_etims_snapshots_on_batch(invoice)
    db.flush()


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


def _before_flush_guard(session: Session, flush_context, instances) -> None:
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
    event.listen(Session, "before_flush", _before_flush_guard, propagate=True)
    _GUARDS_REGISTERED = True
    logger.debug("eTIMS SalesInvoiceItem ORM snapshot guard registered")
