"""Batch/expiry display data for sales invoice print (PDF and API enrichment)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import InventoryLedger, SalesInvoice, SalesInvoiceItem


def _format_expiry_for_print(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        s = str(value).strip()
        if not s:
            return ""
        try:
            d = date.fromisoformat(s[:10])
        except ValueError:
            return s
    return d.strftime("%d %b %Y")


def attach_batch_expiry_to_invoice_item(
    db: Session,
    invoice: SalesInvoice,
    invoice_item: SalesInvoiceItem,
) -> None:
    """Mutate invoice_item with batch_number, expiry_date, batch_allocations for print."""
    sale_ledgers = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.reference_type == "sales_invoice",
            InventoryLedger.reference_id == invoice.id,
            InventoryLedger.item_id == invoice_item.item_id,
            InventoryLedger.transaction_type == "SALE",
            InventoryLedger.quantity_delta < 0,
        )
        .order_by(InventoryLedger.created_at.asc())
        .all()
    )
    if sale_ledgers:
        invoice_item.batch_allocations = [
            {
                "batch_number": getattr(led, "batch_number", None),
                "expiry_date": led.expiry_date.isoformat() if getattr(led, "expiry_date", None) else None,
                "quantity": abs(float(led.quantity_delta)),
            }
            for led in sale_ledgers
        ]
        first_ledger = sale_ledgers[0]
        invoice_item.batch_number = getattr(first_ledger, "batch_number", None)
        invoice_item.expiry_date = (
            first_ledger.expiry_date.isoformat() if getattr(first_ledger, "expiry_date", None) else None
        )
        return
    invoice_item.batch_allocations = None
    if getattr(invoice_item, "batch_id", None):
        ledger = db.query(InventoryLedger).filter(InventoryLedger.id == invoice_item.batch_id).first()
        if ledger:
            invoice_item.batch_number = ledger.batch_number
            invoice_item.expiry_date = (
                ledger.expiry_date.isoformat() if getattr(ledger, "expiry_date", None) else None
            )
            return
    invoice_item.batch_number = None
    invoice_item.expiry_date = None


def batch_expiry_subline_text(row: Dict[str, Any], *, require: bool = False) -> Optional[str]:
    """Plain-text subline(s) for batch/expiry under an item name."""
    lines: List[str] = []
    allocs = row.get("batch_allocations")
    if isinstance(allocs, list) and allocs:
        for a in allocs:
            if not isinstance(a, dict):
                continue
            parts: List[str] = []
            bn = a.get("batch_number")
            if bn is not None and str(bn).strip():
                parts.append(f"Batch: {bn}")
            exp = _format_expiry_for_print(a.get("expiry_date"))
            if exp:
                parts.append(f"Exp: {exp}")
            if not parts:
                continue
            line = " ".join(parts)
            q = a.get("quantity")
            if q is not None:
                try:
                    line += f" ({float(q):g})"
                except (TypeError, ValueError):
                    pass
            lines.append(line)
    else:
        parts = []
        bn = row.get("batch_number")
        if bn is not None and str(bn).strip():
            parts.append(f"Batch: {bn}")
        exp = _format_expiry_for_print(row.get("expiry_date"))
        if exp:
            parts.append(f"Exp: {exp}")
        if parts:
            lines.append(" ".join(parts))
    if lines:
        return "\n".join(lines)
    if require:
        return "Batch: —  Exp: —"
    return None


def build_sales_invoice_pdf_item_rows(
    db: Session,
    invoice: SalesInvoice,
    *,
    require_batch_expiry: bool = False,
) -> List[Dict[str, Any]]:
    """Line dicts for build_sales_invoice_pdf including batch/expiry fields."""
    rows: List[Dict[str, Any]] = []
    for oi in invoice.items or []:
        attach_batch_expiry_to_invoice_item(db, invoice, oi)
        item_name = oi.item.name if oi.item else (getattr(oi, "item_name", None) or "—")
        row: Dict[str, Any] = {
            "item_name": item_name,
            "quantity": float(oi.quantity),
            "unit_name": oi.unit_name or "",
            "unit_price_exclusive": float(oi.unit_price_exclusive or 0),
            "line_total_exclusive": float(oi.line_total_exclusive or 0),
            "line_total_inclusive": float(oi.line_total_inclusive or 0),
            "batch_number": getattr(oi, "batch_number", None),
            "expiry_date": getattr(oi, "expiry_date", None),
            "batch_allocations": getattr(oi, "batch_allocations", None),
        }
        if require_batch_expiry:
            row["batch_expiry_subline"] = batch_expiry_subline_text(row, require=True)
        rows.append(row)
    return rows
