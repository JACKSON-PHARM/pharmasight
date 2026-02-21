"""
Single PDF generator for all transaction documents.
Uses a common template flow: header → document title/number → metadata+client
→ (optional) payment details → items table → totals → (optional) approval block → notes.

Document-specific needs:
- Sales invoice: payment details (till number, paybill); no approval.
- Quotation: no payment, no approval.
- Purchase order: approval block (stamp/signature); no payment.
- Supplier invoice: document skeleton only (no payment, no approval).
- GRN: document skeleton (metadata + supplier + items + total).
"""
from decimal import Decimal
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.document_pdf_commons import (
    build_approval_block_flowables,
    build_document_header,
    build_document_metadata_client_table,
    build_payment_details_table,
    get_document_styles,
)

# Document types supported by the common generator
DOC_TYPE_SALES_INVOICE = "sales_invoice"
DOC_TYPE_QUOTATION = "quotation"
DOC_TYPE_PURCHASE_ORDER = "purchase_order"
DOC_TYPE_SUPPLIER_INVOICE = "supplier_invoice"
DOC_TYPE_GRN = "grn"


def _format_date(d) -> str:
    if d is None:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _format_datetime(dt) -> str:
    if dt is None:
        return "—"
    if hasattr(dt, "strftime"):
        if getattr(dt, "hour", 0) == 0 and getattr(dt, "minute", 0) == 0:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


def _items_table_flowable(items: List[Dict], doc_type: str) -> Table:
    """Single items table layout: Description | Qty | Unit Price | Total."""
    headers = ["Description", "Qty", "Unit Price", "Total"]
    col_widths = [80 * mm, 25 * mm, 35 * mm, 35 * mm]
    data = [headers]
    for row in items:
        name = (row.get("item_name") or row.get("description") or "").strip() or "—"
        qty = row.get("quantity")
        qty_str = f"{qty:,.2f}" if qty is not None else "—"
        unit = row.get("unit_name") or ""
        if unit:
            qty_str = f"{qty_str} {unit}"
        unit_price = (
            row.get("unit_price_exclusive")
            or row.get("unit_price")
            or row.get("unit_cost")
        )
        up_str = f"{unit_price:,.2f}" if unit_price is not None else "—"
        line_total = (
            row.get("line_total_inclusive")
            or row.get("total")
            or row.get("total_price")
            or row.get("total_cost")
            or row.get("line_total_exclusive")
        )
        tot_str = f"{line_total:,.2f}" if line_total is not None else "—"
        data.append([name, qty_str, up_str, tot_str])
    if len(data) == 1:
        data.append(["—", "—", "—", "—"])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    return t


def build_document_pdf(doc_type: str, payload: Dict[str, Any]) -> bytes:
    """
    Generate PDF for any transaction document from a single payload.

    doc_type: one of DOC_TYPE_SALES_INVOICE, DOC_TYPE_QUOTATION, DOC_TYPE_PURCHASE_ORDER,
              DOC_TYPE_SUPPLIER_INVOICE, DOC_TYPE_GRN.

    payload: flat dict with keys used as needed per doc_type:
      - company_name, company_address, company_phone, company_pin, company_logo_bytes
      - branch_name, branch_address
      - document_title (e.g. "SALES INVOICE"), document_number (e.g. invoice_no)
      - metadata_rows: List[Tuple[str, str]] e.g. [("Date:", "2025-01-01")]
      - client_label ("Customer" / "Supplier"), client_name, extra_client_rows (optional)
      - till_number, paybill (sales invoice only)
      - items: List[Dict] with item_name, quantity, unit_name, unit_price*/unit_cost, total*
      - total_exclusive, vat_amount, total_inclusive (invoice/quotation)
      - total_amount (PO), total_cost (GRN)
      - notes (optional)
      - approver_name, approved_at_str, approver_designation, approver_ppb_number,
        stamp_bytes, signature_bytes (purchase order only)
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    st = get_document_styles()
    flow: List[Any] = []

    # ----- 1. Header (all documents) -----
    flow.append(
        build_document_header(
            company_name=payload.get("company_name") or "—",
            company_address=payload.get("company_address"),
            company_phone=payload.get("company_phone"),
            company_pin=payload.get("company_pin"),
            branch_name=payload.get("branch_name"),
            branch_address=payload.get("branch_address"),
            company_logo_bytes=payload.get("company_logo_bytes"),
            with_border=True,
        )
    )
    flow.append(Spacer(1, 7 * mm))

    # ----- 2. Document title + number -----
    title = payload.get("document_title") or ""
    number = payload.get("document_number") or ""
    flow.append(Paragraph(title, st["heading"]))
    flow.append(Paragraph(number, st["detail"]))
    flow.append(Spacer(1, 4 * mm))

    # ----- 3. Metadata + client block (all documents) -----
    metadata_rows = payload.get("metadata_rows") or []
    client_label = payload.get("client_label") or "—"
    client_name = payload.get("client_name") or "—"
    extra_client_rows = payload.get("extra_client_rows") or []
    flow.append(
        build_document_metadata_client_table(
            metadata_rows=metadata_rows,
            client_label=client_label,
            client_name=client_name,
            extra_client_rows=extra_client_rows if extra_client_rows else None,
            with_border=False,
        )
    )
    flow.append(Spacer(1, 7 * mm))

    # ----- 4. Payment details (sales invoice only) -----
    if doc_type == DOC_TYPE_SALES_INVOICE and (
        payload.get("till_number") or payload.get("paybill")
    ):
        flow.append(
            build_payment_details_table(
                till_number=payload.get("till_number"),
                paybill=payload.get("paybill"),
                with_border=True,
            )
        )
        flow.append(Spacer(1, 4 * mm))

    # ----- 5. Items table (all documents) -----
    items = payload.get("items") or []
    flow.append(_items_table_flowable(items, doc_type))
    flow.append(Spacer(1, 4 * mm))

    # ----- 6. Totals -----
    if doc_type in (DOC_TYPE_SALES_INVOICE, DOC_TYPE_QUOTATION, DOC_TYPE_SUPPLIER_INVOICE):
        total_exclusive = payload.get("total_exclusive") or Decimal("0")
        vat_amount = payload.get("vat_amount") or Decimal("0")
        total_inclusive = payload.get("total_inclusive") or Decimal("0")
        flow.append(Paragraph(f"<b>Net: {total_exclusive:,.2f}</b>", st["detail"]))
        flow.append(Paragraph(f"<b>VAT: {vat_amount:,.2f}</b>", st["detail"]))
        flow.append(Paragraph(f"<b>Total: {total_inclusive:,.2f}</b>", st["detail"]))
    elif doc_type == DOC_TYPE_PURCHASE_ORDER:
        total_amount = payload.get("total_amount") or Decimal("0")
        flow.append(Paragraph(f"<b>Total: {total_amount:,.2f}</b>", st["detail"]))
    elif doc_type == DOC_TYPE_GRN:
        total_cost = payload.get("total_cost") or Decimal("0")
        flow.append(Paragraph(f"<b>Total cost: {total_cost:,.2f}</b>", st["detail"]))

    flow.append(Spacer(1, 7 * mm))

    # ----- 7. Approval block (purchase order only) -----
    if doc_type == DOC_TYPE_PURCHASE_ORDER:
        flow.extend(
            build_approval_block_flowables(
                approver_name=payload.get("approver_name") or "",
                approved_at_str=payload.get("approved_at_str") or _format_datetime(datetime.now(timezone.utc)),
                approver_designation=payload.get("approver_designation"),
                approver_ppb_number=payload.get("approver_ppb_number"),
                stamp_bytes=payload.get("stamp_bytes"),
                signature_bytes=payload.get("signature_bytes"),
            )
        )

    # ----- 8. Notes (optional) -----
    notes = payload.get("notes")
    if notes:
        flow.append(Spacer(1, 4 * mm))
        flow.append(Paragraph(f"Notes: {notes}", st["detail"]))

    doc.build(flow)
    return buf.getvalue()


# ----- Document-specific wrappers (same signatures as before; API imports from here) -----


def _format_order_date(dt) -> str:
    now_utc = datetime.now(timezone.utc)
    if dt is None:
        return now_utc.strftime("%Y-%m-%d")
    if hasattr(dt, "strftime"):
        if not hasattr(dt, "hour"):
            return dt.strftime("%Y-%m-%d")
        if getattr(dt, "hour", 0) == 0 and getattr(dt, "minute", 0) == 0:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


def _format_approved_at(dt) -> str:
    now_utc = datetime.now(timezone.utc)
    if dt is None:
        return now_utc.strftime("%Y-%m-%d %H:%M")
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


def build_quotation_pdf(
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    company_logo_bytes: Optional[bytes] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    quotation_no: str = "",
    quotation_date: Optional[date] = None,
    valid_until: Optional[date] = None,
    customer_name: Optional[str] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    total_exclusive: Optional[Decimal] = None,
    vat_amount: Optional[Decimal] = None,
    total_inclusive: Optional[Decimal] = None,
) -> bytes:
    """Build A4 PDF for a sales quotation. No payment details, no approval block."""
    items = items or []
    total_exclusive = total_exclusive or Decimal("0")
    vat_amount = vat_amount or Decimal("0")
    total_inclusive = total_inclusive or Decimal("0")
    quotation_date = quotation_date or date.today()
    metadata: List[Tuple[str, str]] = [
        ("Date:", quotation_date.strftime("%Y-%m-%d") if hasattr(quotation_date, "strftime") else str(quotation_date)),
    ]
    extra_client: List[Tuple[str, str]] = []
    if valid_until:
        extra_client.append(
            ("Valid until:", valid_until.strftime("%Y-%m-%d") if hasattr(valid_until, "strftime") else str(valid_until))
        )
    if reference:
        extra_client.append(("Reference:", reference))
    payload = {
        "company_name": company_name,
        "company_address": company_address,
        "company_phone": company_phone,
        "company_pin": company_pin,
        "company_logo_bytes": company_logo_bytes,
        "branch_name": branch_name,
        "branch_address": branch_address,
        "document_title": "SALES QUOTATION",
        "document_number": quotation_no or "",
        "metadata_rows": metadata,
        "client_label": "Customer",
        "client_name": customer_name or "—",
        "extra_client_rows": extra_client if extra_client else None,
        "items": items,
        "total_exclusive": total_exclusive,
        "vat_amount": vat_amount,
        "total_inclusive": total_inclusive,
        "notes": notes,
    }
    return build_document_pdf(DOC_TYPE_QUOTATION, payload)


def build_po_pdf(
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    company_logo_path: Optional[str] = None,
    company_logo_bytes: Optional[bytes] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    order_number: str = "",
    order_date: Optional[datetime] = None,
    supplier_name: str = "—",
    reference: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    total_amount: Optional[Decimal] = None,
    document_branding: Optional[Dict[str, Any]] = None,
    stamp_path: Optional[str] = None,
    stamp_bytes: Optional[bytes] = None,
    approver_name: str = "",
    approver_designation: Optional[str] = None,
    approver_ppb_number: Optional[str] = None,
    signature_path: Optional[str] = None,
    signature_bytes: Optional[bytes] = None,
    approved_at: Optional[datetime] = None,
) -> bytes:
    """Build A4 PDF for an approved purchase order. Includes approval block; no payment details."""
    items = items or []
    total_amount = total_amount or Decimal("0")
    now_utc = datetime.now(timezone.utc)
    order_date = order_date or now_utc
    approved_at = approved_at or now_utc
    metadata_rows = [("Order date:", _format_order_date(order_date))]
    extra_client = [("Reference:", reference)] if reference else []
    payload = {
        "company_name": company_name,
        "company_address": company_address,
        "company_phone": company_phone,
        "company_pin": company_pin,
        "company_logo_bytes": company_logo_bytes,
        "branch_name": branch_name,
        "branch_address": branch_address,
        "document_title": "PURCHASE ORDER",
        "document_number": order_number or "",
        "metadata_rows": metadata_rows,
        "client_label": "Supplier",
        "client_name": supplier_name,
        "extra_client_rows": extra_client,
        "items": items,
        "total_amount": total_amount,
        "approver_name": approver_name,
        "approved_at_str": _format_approved_at(approved_at),
        "approver_designation": approver_designation,
        "approver_ppb_number": approver_ppb_number,
        "stamp_bytes": stamp_bytes,
        "signature_bytes": signature_bytes,
    }
    return build_document_pdf(DOC_TYPE_PURCHASE_ORDER, payload)


def build_sales_invoice_pdf(
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    company_logo_bytes: Optional[bytes] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    invoice_no: str = "",
    invoice_date: Optional[date] = None,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    payment_mode: Optional[str] = None,
    status: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    total_exclusive: Optional[Decimal] = None,
    vat_amount: Optional[Decimal] = None,
    total_inclusive: Optional[Decimal] = None,
    notes: Optional[str] = None,
    till_number: Optional[str] = None,
    paybill: Optional[str] = None,
) -> bytes:
    """Build A4 PDF for a sales invoice. Optional till/paybill; no approval block."""
    items = items or []
    total_exclusive = total_exclusive or Decimal("0")
    vat_amount = vat_amount or Decimal("0")
    total_inclusive = total_inclusive or Decimal("0")
    invoice_date = invoice_date or date.today()
    metadata: List[Tuple[str, str]] = [
        ("Date:", invoice_date.strftime("%Y-%m-%d") if hasattr(invoice_date, "strftime") else str(invoice_date)),
    ]
    extra_client: List[Tuple[str, str]] = []
    if customer_phone:
        extra_client.append(("Phone:", customer_phone))
    if payment_mode:
        extra_client.append(("Payment:", payment_mode))
    if status:
        extra_client.append(("Status:", status))
    payload = {
        "company_name": company_name,
        "company_address": company_address,
        "company_phone": company_phone,
        "company_pin": company_pin,
        "company_logo_bytes": company_logo_bytes,
        "branch_name": branch_name,
        "branch_address": branch_address,
        "document_title": "SALES INVOICE",
        "document_number": invoice_no or "",
        "metadata_rows": metadata,
        "client_label": "Customer",
        "client_name": customer_name or "—",
        "extra_client_rows": extra_client if extra_client else None,
        "till_number": till_number,
        "paybill": paybill,
        "items": items,
        "total_exclusive": total_exclusive,
        "vat_amount": vat_amount,
        "total_inclusive": total_inclusive,
        "notes": notes,
    }
    return build_document_pdf(DOC_TYPE_SALES_INVOICE, payload)


def build_grn_pdf(
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    company_logo_bytes: Optional[bytes] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    grn_no: str = "",
    date_received: Optional[date] = None,
    supplier_name: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    total_cost: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> bytes:
    """Build A4 PDF for a GRN. Document skeleton: header, metadata, supplier, items, total."""
    items = items or []
    total_cost = total_cost or Decimal("0")
    date_received = date_received or date.today()
    metadata: List[Tuple[str, str]] = [
        (
            "Date received:",
            date_received.strftime("%Y-%m-%d") if hasattr(date_received, "strftime") else str(date_received),
        ),
    ]
    payload = {
        "company_name": company_name,
        "company_address": company_address,
        "company_phone": company_phone,
        "company_pin": company_pin,
        "company_logo_bytes": company_logo_bytes,
        "branch_name": branch_name,
        "branch_address": branch_address,
        "document_title": "GOODS RECEIVED NOTE",
        "document_number": grn_no or "",
        "metadata_rows": metadata,
        "client_label": "Supplier",
        "client_name": supplier_name or "—",
        "items": items,
        "total_cost": total_cost,
        "notes": notes,
    }
    return build_document_pdf(DOC_TYPE_GRN, payload)


def build_supplier_invoice_pdf(
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    company_logo_bytes: Optional[bytes] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    invoice_number: str = "",
    invoice_date: Optional[date] = None,
    supplier_name: Optional[str] = None,
    reference: Optional[str] = None,
    status: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    total_exclusive: Optional[Decimal] = None,
    vat_amount: Optional[Decimal] = None,
    total_inclusive: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> bytes:
    """Build A4 PDF for a supplier (purchase) invoice. Document skeleton only; no payment, no approval."""
    items = items or []
    total_exclusive = total_exclusive or Decimal("0")
    vat_amount = vat_amount or Decimal("0")
    total_inclusive = total_inclusive or Decimal("0")
    invoice_date = invoice_date or date.today()
    metadata: List[Tuple[str, str]] = [
        ("Date:", invoice_date.strftime("%Y-%m-%d") if hasattr(invoice_date, "strftime") else str(invoice_date)),
    ]
    extra_client: List[Tuple[str, str]] = []
    if reference:
        extra_client.append(("Reference:", reference))
    if status:
        extra_client.append(("Status:", status))
    payload = {
        "company_name": company_name,
        "company_address": company_address,
        "company_phone": company_phone,
        "company_pin": company_pin,
        "company_logo_bytes": company_logo_bytes,
        "branch_name": branch_name,
        "branch_address": branch_address,
        "document_title": "SUPPLIER INVOICE",
        "document_number": invoice_number or "",
        "metadata_rows": metadata,
        "client_label": "Supplier",
        "client_name": supplier_name or "—",
        "extra_client_rows": extra_client if extra_client else None,
        "items": items,
        "total_exclusive": total_exclusive,
        "vat_amount": vat_amount,
        "total_inclusive": total_inclusive,
        "notes": notes,
    }
    return build_document_pdf(DOC_TYPE_SUPPLIER_INVOICE, payload)
