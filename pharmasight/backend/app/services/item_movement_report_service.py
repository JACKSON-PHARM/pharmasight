"""
Item Movement Report service — read-only, builds report from inventory_ledger only.
No changes to ledger or any write flows.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Branch,
    Company,
    Item,
    InventoryLedger,
    CompanySetting,
    SalesInvoice,
    GRN,
    SupplierInvoice,
    BranchTransfer,
    BranchReceipt,
    StockTakeSession,
)
from app.schemas.reports import (
    ItemMovementDisplayOptions,
    ItemMovementReportResponse,
    ItemMovementRow,
)
from app.schemas.reports import ItemBatchInfo


# Default timezone for date boundaries (UTC)
def _midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _get_report_display_options(db: Session, company_id: UUID) -> ItemMovementDisplayOptions:
    """Read company_settings.report_settings.item_movement; default both to False."""
    row = db.query(CompanySetting).filter(
        CompanySetting.company_id == company_id,
        CompanySetting.setting_key == "report_settings",
    ).first()
    if not row or not row.setting_value:
        return ItemMovementDisplayOptions(show_batch_number=False, show_expiry_date=False)
    try:
        import json
        data = json.loads(row.setting_value)
        item_movement = (data or {}).get("item_movement") or {}
        return ItemMovementDisplayOptions(
            show_batch_number=bool(item_movement.get("show_batch_number", False)),
            show_expiry_date=bool(item_movement.get("show_expiry_date", False)),
        )
    except Exception:
        return ItemMovementDisplayOptions(show_batch_number=False, show_expiry_date=False)


def _resolve_references_batch(
    db: Session,
    refs_by_type: Dict[str, List[UUID]],
) -> Dict[Tuple[str, UUID], Dict[str, Any]]:
    """
    Resolve (reference_type, reference_id) to document_type and reference string.
    Returns map (reference_type, reference_id) -> { "document_type": str, "reference": str }.
    """
    result: Dict[Tuple[str, UUID], Dict[str, Any]] = {}

    # sales_invoice -> Sale, invoice_no (+ customer_name, payment_mode)
    for rid in refs_by_type.get("sales_invoice") or []:
        inv = db.query(SalesInvoice).filter(SalesInvoice.id == rid).first()
        if inv:
            ref_parts = [inv.invoice_no or ""]
            if inv.customer_name:
                ref_parts.append(str(inv.customer_name))
            if getattr(inv, "payment_mode", None):
                ref_parts.append(str(inv.payment_mode))
            result[("sales_invoice", rid)] = {
                "document_type": "Sale",
                "reference": " ".join(ref_parts).strip() or inv.invoice_no or "",
            }
        else:
            result[("sales_invoice", rid)] = {"document_type": "Sale", "reference": ""}

    # grn -> GRN, grn_no
    for rid in refs_by_type.get("grn") or []:
        grn = db.query(GRN).filter(GRN.id == rid).first()
        result[("grn", rid)] = {
            "document_type": "GRN",
            "reference": grn.grn_no if grn else "",
        }

    # purchase_invoice -> Supplier Invoice, invoice_number
    for rid in refs_by_type.get("purchase_invoice") or []:
        inv = db.query(SupplierInvoice).filter(SupplierInvoice.id == rid).first()
        result[("purchase_invoice", rid)] = {
            "document_type": "Supplier Invoice",
            "reference": inv.invoice_number if inv else "",
        }

    # branch_transfer -> Branch Transfer Out, transfer_number
    for rid in refs_by_type.get("branch_transfer") or []:
        t = db.query(BranchTransfer).filter(BranchTransfer.id == rid).first()
        result[("branch_transfer", rid)] = {
            "document_type": "Branch Transfer Out",
            "reference": t.transfer_number if t else "",
        }

    # branch_receipt -> Branch Transfer In, receipt_number
    for rid in refs_by_type.get("branch_receipt") or []:
        r = db.query(BranchReceipt).filter(BranchReceipt.id == rid).first()
        result[("branch_receipt", rid)] = {
            "document_type": "Branch Transfer In",
            "reference": r.receipt_number if r else "",
        }

    # STOCK_TAKE -> Stock Take, session_code
    for rid in refs_by_type.get("STOCK_TAKE") or []:
        s = db.query(StockTakeSession).filter(StockTakeSession.id == rid).first()
        result[("STOCK_TAKE", rid)] = {
            "document_type": "Stock Take",
            "reference": s.session_code if s else str(rid),
        }

    return result


def build_item_movement_report(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    item_id: UUID,
    start_date: date,
    end_date: date,
) -> ItemMovementReportResponse:
    """
    Build branch-scoped item movement report from inventory_ledger only.
    Date filter: created_at >= start_ts AND created_at < end_ts
    where start_ts = start_date 00:00:00 UTC, end_ts = end_date + 1 day 00:00:00 UTC.
    """
    start_ts = _midnight_utc(start_date)
    end_ts = _midnight_utc(end_date)
    # end_ts = day after end_date at 00:00:00
    end_ts = end_ts + timedelta(days=1)

    company = db.query(Company).filter(Company.id == company_id).first()
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    item = db.query(Item).filter(Item.id == item_id, Item.company_id == company_id).first()
    if not item:
        raise ValueError("item_not_found")
    if not company or not branch or branch.company_id != company_id:
        raise ValueError("branch_or_company_not_found")

    display_options = _get_report_display_options(db, company_id)

    # Opening balance: SUM(quantity_delta) where created_at < start_ts
    opening_row = db.query(func.coalesce(func.sum(InventoryLedger.quantity_delta), 0)).filter(
        InventoryLedger.company_id == company_id,
        InventoryLedger.branch_id == branch_id,
        InventoryLedger.item_id == item_id,
        InventoryLedger.created_at < start_ts,
    ).scalar()
    opening_balance = Decimal(str(opening_row or 0))

    # Movement rows: created_at >= start_ts AND created_at < end_ts, ORDER BY created_at ASC, id ASC
    ledger_rows = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.created_at >= start_ts,
            InventoryLedger.created_at < end_ts,
        )
        .order_by(InventoryLedger.created_at.asc(), InventoryLedger.id.asc())
        .all()
    )

    # Collect reference_type + reference_id for batch resolution
    refs_by_type: Dict[str, List[UUID]] = {}
    for row in ledger_rows:
        rt = (row.reference_type or "").strip()
        if rt and row.reference_id and rt not in ("MANUAL_ADJUSTMENT", "OPENING_BALANCE"):
            refs_by_type.setdefault(rt, []).append(row.reference_id)
    # Deduplicate per type
    for k in refs_by_type:
        refs_by_type[k] = list(dict.fromkeys(refs_by_type[k]))

    ref_map = _resolve_references_batch(db, refs_by_type)

    # Build output rows: synthetic opening row first, then ledger rows with running balance
    rows_out: List[ItemMovementRow] = []
    running = opening_balance

    # First row: synthetic Opening Balance
    rows_out.append(ItemMovementRow(
        date=start_ts,
        document_type="Opening Balance",
        reference="",
        qty_in=Decimal("0"),
        qty_out=Decimal("0"),
        running_balance=opening_balance,
        batch_number=None,
        expiry_date=None,
    ))

    for row in ledger_rows:
        qty_delta = Decimal(str(row.quantity_delta or 0))
        if qty_delta > 0:
            qty_in, qty_out = qty_delta, Decimal("0")
        else:
            qty_in, qty_out = Decimal("0"), abs(qty_delta)
        running += qty_delta

        rt = (row.reference_type or "").strip()
        if rt == "MANUAL_ADJUSTMENT":
            doc_type, ref = "Adjustment", (row.notes or "Adjustment").strip() or "Adjustment"
        elif rt == "OPENING_BALANCE":
            doc_type, ref = "Opening Balance", ""
        else:
            info = ref_map.get((rt, row.reference_id)) if row.reference_id else None
            doc_type = (info or {}).get("document_type", rt or "—")
            ref = (info or {}).get("reference", "")

        expiry = row.expiry_date
        if expiry is not None and hasattr(expiry, "date") and callable(getattr(expiry, "date", None)):
            expiry = expiry.date()
        rows_out.append(ItemMovementRow(
            date=row.created_at,
            document_type=doc_type,
            reference=ref or "",
            qty_in=qty_in,
            qty_out=qty_out,
            running_balance=running,
            batch_number=row.batch_number if display_options.show_batch_number else None,
            expiry_date=expiry if display_options.show_expiry_date else None,
        ))

    closing_balance = running

    return ItemMovementReportResponse(
        company_name=company.name or "",
        branch_name=branch.name or "",
        item_name=item.name or "",
        item_sku=item.sku,
        start_date=start_date,
        end_date=end_date,
        display_options=display_options,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        rows=rows_out,
    )


def build_batch_movement_report(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    item_id: UUID,
    batch_no: str,
    start_date: date,
    end_date: date,
) -> ItemMovementReportResponse:
    """
    Build branch-scoped batch movement report from inventory_ledger only.
    Filters by company_id, branch_id, item_id, batch_number, and date range.
    Order by movement date DESC. Running balance is calculated for the batch.
    Read-only; no changes to ledger or stock logic.
    """
    start_ts = _midnight_utc(start_date)
    end_ts = _midnight_utc(end_date)
    end_ts = end_ts + timedelta(days=1)

    company = db.query(Company).filter(Company.id == company_id).first()
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    item = db.query(Item).filter(Item.id == item_id, Item.company_id == company_id).first()
    if not item:
        raise ValueError("item_not_found")
    if not company or not branch or branch.company_id != company_id:
        raise ValueError("branch_or_company_not_found")
    batch_no_clean = (batch_no or "").strip()
    if not batch_no_clean:
        raise ValueError("batch_no_required")

    display_options = _get_report_display_options(db, company_id)  # unused for batch; overridden below
    # Batch report always shows batch and expiry for context
    display_options = ItemMovementDisplayOptions(
        show_batch_number=True,
        show_expiry_date=True,
    )

    # Opening balance for this batch: SUM(quantity_delta) where created_at < start_ts
    opening_row = db.query(func.coalesce(func.sum(InventoryLedger.quantity_delta), 0)).filter(
        InventoryLedger.company_id == company_id,
        InventoryLedger.branch_id == branch_id,
        InventoryLedger.item_id == item_id,
        InventoryLedger.batch_number == batch_no_clean,
        InventoryLedger.created_at < start_ts,
    ).scalar()
    opening_balance = Decimal(str(opening_row or 0))

    # Movement rows: date range, ORDER BY created_at DESC, id DESC (newest first)
    ledger_rows = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.batch_number == batch_no_clean,
            InventoryLedger.created_at >= start_ts,
            InventoryLedger.created_at < end_ts,
        )
        .order_by(InventoryLedger.created_at.desc(), InventoryLedger.id.desc())
        .all()
    )
    # Reverse so we display chronological order (oldest first in list) for running balance
    ledger_rows = list(reversed(ledger_rows))

    refs_by_type: Dict[str, List[UUID]] = {}
    for row in ledger_rows:
        rt = (row.reference_type or "").strip()
        if rt and row.reference_id and rt not in ("MANUAL_ADJUSTMENT", "OPENING_BALANCE"):
            refs_by_type.setdefault(rt, []).append(row.reference_id)
    for k in refs_by_type:
        refs_by_type[k] = list(dict.fromkeys(refs_by_type[k]))
    ref_map = _resolve_references_batch(db, refs_by_type)

    rows_out: List[ItemMovementRow] = []
    running = opening_balance

    rows_out.append(ItemMovementRow(
        date=start_ts,
        document_type="Opening Balance",
        reference="",
        qty_in=Decimal("0"),
        qty_out=Decimal("0"),
        running_balance=opening_balance,
        batch_number=batch_no_clean,
        expiry_date=None,
    ))

    for row in ledger_rows:
        qty_delta = Decimal(str(row.quantity_delta or 0))
        if qty_delta > 0:
            qty_in, qty_out = qty_delta, Decimal("0")
        else:
            qty_in, qty_out = Decimal("0"), abs(qty_delta)
        running += qty_delta

        rt = (row.reference_type or "").strip()
        if rt == "MANUAL_ADJUSTMENT":
            doc_type, ref = "Adjustment", (row.notes or "Adjustment").strip() or "Adjustment"
        elif rt == "OPENING_BALANCE":
            doc_type, ref = "Opening Balance", ""
        else:
            info = ref_map.get((rt, row.reference_id)) if row.reference_id else None
            doc_type = (info or {}).get("document_type", rt or "—")
            ref = (info or {}).get("reference", "")

        expiry = row.expiry_date
        if expiry is not None and hasattr(expiry, "date") and callable(getattr(expiry, "date", None)):
            expiry = expiry.date()
        rows_out.append(ItemMovementRow(
            date=row.created_at,
            document_type=doc_type,
            reference=ref or "",
            qty_in=qty_in,
            qty_out=qty_out,
            running_balance=running,
            batch_number=row.batch_number if display_options.show_batch_number else None,
            expiry_date=expiry if display_options.show_expiry_date else None,
        ))

    closing_balance = running

    return ItemMovementReportResponse(
        company_name=company.name or "",
        branch_name=branch.name or "",
        item_name=item.name or "",
        item_sku=item.sku,
        start_date=start_date,
        end_date=end_date,
        display_options=display_options,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        rows=rows_out,
    )


def get_item_batches(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    item_id: UUID,
) -> List[ItemBatchInfo]:
    """
    Return distinct batches for an item at a branch (tenant- and branch-scoped).
    Each batch includes batch_no, expiry_date, and current_balance (sum of quantity_delta).
    Sorted by expiry_date DESC (newest first), then batch_no.
    Used to populate the batch dropdown in Batch Movement Report.
    """
    batch_rows = (
        db.query(
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
            func.sum(InventoryLedger.quantity_delta).label("balance"),
        )
        .filter(
            InventoryLedger.company_id == company_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.batch_number.isnot(None),
            InventoryLedger.batch_number != "",
        )
        .group_by(InventoryLedger.batch_number, InventoryLedger.expiry_date)
        .all()
    )
    out: List[ItemBatchInfo] = []
    for row in batch_rows:
        bn = (row.batch_number or "").strip()
        if not bn:
            continue
        expiry = row.expiry_date
        if expiry is not None and hasattr(expiry, "date") and callable(getattr(expiry, "date", None)):
            expiry = expiry.date()
        bal = Decimal(str(row.balance or 0))
        out.append(ItemBatchInfo(batch_no=bn, expiry_date=expiry, current_balance=bal))
    # Sort newest first: by expiry_date DESC nulls last, then batch_no
    out.sort(key=lambda x: ((x.expiry_date is None, -(x.expiry_date or date(1970, 1, 1)).toordinal()), x.batch_no))
    return out
