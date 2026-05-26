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
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
)

from app.services.document_pdf_commons import (
    build_approval_block_flowables,
    build_document_header,
    build_document_metadata_client_table,
    build_payment_details_table,
    build_sales_quotation_footer_table,
    get_document_styles,
)

# Document types supported by the common generator
DOC_TYPE_SALES_INVOICE = "sales_invoice"
DOC_TYPE_QUOTATION = "quotation"
DOC_TYPE_PURCHASE_ORDER = "purchase_order"
DOC_TYPE_SUPPLIER_INVOICE = "supplier_invoice"
DOC_TYPE_GRN = "grn"


def kra_qr_png_bytes(kra_qr_code: Optional[str]) -> Optional[bytes]:
    """Build PNG bytes for PDF: base64 PNG payload or QR from string."""
    if not kra_qr_code or not str(kra_qr_code).strip():
        return None
    s = str(kra_qr_code).strip()
    try:
        import base64

        raw = base64.b64decode(s, validate=False)
        if len(raw) > 24 and raw[:8] == b"\x89PNG\r\n\x1a\x0a":
            return raw
    except Exception:
        pass
    try:
        import qrcode

        img = qrcode.make(s, box_size=4, border=3)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


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


def _format_kra_verified_stamp(dt) -> str:
    """Display KRA verification time on fiscal block (local wall time, DD/MM/YYYY HH:MM:SS)."""
    if dt is None:
        return ""
    try:
        if hasattr(dt, "astimezone") and getattr(dt, "tzinfo", None) is not None:
            try:
                dt = dt.astimezone()
            except Exception:
                pass
        if hasattr(dt, "strftime"):
            return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        pass
    return str(dt)


_ITEM_DESC_STYLE = ParagraphStyle(
    "ItemDesc",
    fontName="Helvetica",
    fontSize=9,
    leading=11,
    spaceAfter=0,
)

_STMT_DESC_STYLE = ParagraphStyle(
    "StmtDesc",
    fontName="Helvetica",
    fontSize=7.5,
    leading=9,
    spaceAfter=0,
    wordWrap="CJK",
)
_STMT_DESC_DETAIL_STYLE = ParagraphStyle(
    "StmtDescDetail",
    fontName="Helvetica",
    fontSize=6.5,
    leading=8,
    spaceAfter=0,
    leftIndent=2,
    textColor=colors.HexColor("#444444"),
    wordWrap="CJK",
)
_STMT_REF_STYLE = ParagraphStyle(
    "StmtRef",
    fontName="Helvetica",
    fontSize=7,
    leading=8,
    spaceAfter=0,
    wordWrap="CJK",
)
def _description_cell_flowable(row: Dict[str, Any], *, show_batch_expiry: bool) -> Any:
    name = (row.get("item_name") or row.get("description") or "").strip() or "—"
    sub = row.get("batch_expiry_subline")
    if sub is None and show_batch_expiry:
        from app.services.sales_invoice_batch_display import batch_expiry_subline_text

        sub = batch_expiry_subline_text(row, require=show_batch_expiry)
    if sub:
        safe_name = xml_escape(name)
        safe_sub = xml_escape(str(sub)).replace("\n", "<br/>")
        return Paragraph(
            f"{safe_name}<br/><font size='7' color='#333333'>{safe_sub}</font>",
            _ITEM_DESC_STYLE,
        )
    return name


def _items_table_flowable(
    items: List[Dict[str, Any]],
    _doc_type: str,
    *,
    show_batch_expiry: bool = False,
) -> Table:
    headers = ["Description", "Qty", "Unit Price", "Total"]
    col_widths = [80 * mm, 25 * mm, 35 * mm, 35 * mm]
    data = [headers]
    for row in items:
        name = _description_cell_flowable(row, show_batch_expiry=show_batch_expiry)
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
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    # Underline only (no box): line below each row
    for r in range(len(data)):
        style.append(("LINEBELOW", (0, r), (-1, r), 0.5, colors.grey))
    t.setStyle(TableStyle(style))
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
      - prepared_by, printed_by, served_by (sales invoice and quotation footer)
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

    # ----- 1. Header (all documents incl. PO): same as sales/quotations — company left, logo right; underline only, no box -----
    flow.append(
        build_document_header(
            company_name=payload.get("company_name") or "—",
            company_address=payload.get("company_address"),
            company_phone=payload.get("company_phone"),
            company_pin=payload.get("company_pin"),
            branch_name=payload.get("branch_name"),
            branch_address=payload.get("branch_address"),
            company_logo_bytes=payload.get("company_logo_bytes"),
            with_border=False,
        )
    )
    flow.append(Spacer(1, 7 * mm))

    # ----- 2. Document title only (number goes in metadata block on the right) -----
    title = payload.get("document_title") or ""
    flow.append(Paragraph(title, st["heading"]))
    warning = (payload.get("non_fiscal_warning") or "").strip()
    if warning:
        warn_style = ParagraphStyle(
            name="non_fiscal_warning",
            parent=st["detail"],
            alignment=TA_CENTER,
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#8A4B00"),
        )
        flow.append(Paragraph(f"<b>{xml_escape(warning)}</b>", warn_style))
    flow.append(Spacer(1, 4 * mm))

    # ----- 3. Metadata + client block: client left (one line: Customer | Payment | Till for sales), Document right -----
    metadata_rows = payload.get("metadata_rows") or []
    document_number = payload.get("document_number") or ""
    client_label = payload.get("client_label") or "—"
    client_name = payload.get("client_name") or "—"
    extra_client_rows = payload.get("extra_client_rows") or []
    payment_mode = payload.get("payment_mode") if doc_type == DOC_TYPE_SALES_INVOICE else None
    till_number = payload.get("till_number") if doc_type == DOC_TYPE_SALES_INVOICE else None
    paybill = payload.get("paybill") if doc_type == DOC_TYPE_SALES_INVOICE else None
    flow.append(
        build_document_metadata_client_table(
            metadata_rows=metadata_rows,
            client_label=client_label,
            client_name=client_name,
            extra_client_rows=extra_client_rows if extra_client_rows else None,
            with_border=False,
            document_number=document_number,
            payment_mode=payment_mode,
            till_number=till_number,
            paybill=paybill if (paybill and str(paybill).strip()) else None,
        )
    )
    flow.append(Spacer(1, 7 * mm))

    # ----- 5. Items table (all documents) -----
    items = payload.get("items") or []
    show_batch_expiry = bool(payload.get("show_batch_expiry"))
    flow.append(_items_table_flowable(items, doc_type, show_batch_expiry=show_batch_expiry))
    flow.append(Spacer(1, 4 * mm))

    # ----- 6. Totals -----
    if doc_type in (DOC_TYPE_SALES_INVOICE, DOC_TYPE_QUOTATION, DOC_TYPE_SUPPLIER_INVOICE):
        total_exclusive = payload.get("total_exclusive") or Decimal("0")
        vat_amount = payload.get("vat_amount") or Decimal("0")
        total_inclusive = payload.get("total_inclusive") or Decimal("0")
        flow.append(Paragraph(f"<b>Net: {total_exclusive:,.2f}</b>", st["detail"]))
        flow.append(Paragraph(f"<b>VAT: {vat_amount:,.2f}</b>", st["detail"]))
        flow.append(Paragraph(f"<b>Total: {total_inclusive:,.2f}</b>", st["detail"]))
        kra_rn = payload.get("kra_receipt_number")
        kra_invoice_number = payload.get("kra_invoice_number")
        tis_name = payload.get("etims_trader_invoicing_system_name")
        kra_sig = payload.get("kra_signature")
        kra_qr_png = payload.get("kra_qr_png_bytes")
        kra_pin = (payload.get("company_pin") or "").strip() if doc_type == DOC_TYPE_SALES_INVOICE else ""
        kra_cu = (payload.get("kra_cu_device_serial") or "").strip() if doc_type == DOC_TYPE_SALES_INVOICE else ""
        kra_submitted = payload.get("kra_submitted_at") if doc_type == DOC_TYPE_SALES_INVOICE else None
        if kra_rn or kra_sig or kra_qr_png:
            kra_center = ParagraphStyle(
                name="kra_blk_center",
                parent=st["detail"],
                alignment=TA_CENTER,
                fontSize=9,
                leading=11,
                spaceAfter=2,
            )
            flow.append(Spacer(1, 5 * mm))
            flow.append(Paragraph("<b>KRA eTIMS</b>", kra_center))
            if doc_type == DOC_TYPE_SALES_INVOICE and kra_pin:
                flow.append(Paragraph(f"PIN: {xml_escape(kra_pin)}", kra_center))
            if doc_type == DOC_TYPE_SALES_INVOICE and kra_invoice_number:
                flow.append(Paragraph(f"KRA Invoice No: {xml_escape(str(kra_invoice_number))}", kra_center))
            if kra_rn:
                flow.append(Paragraph(f"KRA Receipt No: {xml_escape(str(kra_rn))}", kra_center))
            if doc_type == DOC_TYPE_SALES_INVOICE and kra_cu:
                flow.append(Paragraph(f"Control Unit Serial No: {xml_escape(kra_cu)}", kra_center))
            if doc_type == DOC_TYPE_SALES_INVOICE and tis_name:
                flow.append(Paragraph(f"TIS: {xml_escape(str(tis_name))}", kra_center))
            if kra_sig:
                flow.append(Spacer(1, 2 * mm))
                flow.append(Paragraph("<b>Internal Data:</b>", kra_center))
                sig_raw = str(kra_sig)
                sig_short = (sig_raw[:800] + "…") if len(sig_raw) > 800 else sig_raw
                sig_html = xml_escape(sig_short).replace("\n", "<br/>")
                flow.append(Paragraph(sig_html, kra_center))
            if kra_qr_png:
                flow.append(Spacer(1, 3 * mm))
                qr_w = 16 * mm
                qr_img = RLImage(BytesIO(kra_qr_png), width=qr_w, height=qr_w)
                qr_tbl = Table([[qr_img]], colWidths=[175 * mm])
                qr_tbl.setStyle(
                    TableStyle(
                        [
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ]
                    )
                )
                flow.append(qr_tbl)
            verified_str = _format_kra_verified_stamp(kra_submitted) if kra_submitted else ""
            if verified_str:
                flow.append(Spacer(1, 2 * mm))
                flow.append(Paragraph("<b>Date/Time Verified:</b>", kra_center))
                flow.append(Paragraph(xml_escape(verified_str), kra_center))
            flow.append(Spacer(1, 2 * mm))
            flow.append(Paragraph("<b>END OF FISCAL RECEIPT</b>", kra_center))
            flow.append(Paragraph("THANK YOU FOR SHOPPING WITH US", kra_center))
            tag_fiscal = ParagraphStyle(
                name="sales_pdf_tagline_fiscal",
                parent=st["detail"],
                alignment=TA_CENTER,
                fontSize=8,
                leading=10,
                textColor=colors.HexColor("#333333"),
                spaceBefore=4,
            )
            flow.append(Paragraph("<b>Powered by SightOps</b>", tag_fiscal))
    elif doc_type == DOC_TYPE_PURCHASE_ORDER:
        total_amount = payload.get("total_amount") or Decimal("0")
        flow.append(Paragraph(f"<b>Total: {total_amount:,.2f}</b>", st["detail"]))
    elif doc_type == DOC_TYPE_GRN:
        total_cost = payload.get("total_cost") or Decimal("0")
        flow.append(Paragraph(f"<b>Total cost: {total_cost:,.2f}</b>", st["detail"]))

    flow.append(Spacer(1, 7 * mm))

    # ----- 6b. Footer: prepared by, printed by, served by only (till/paybill in metadata; no duplication) -----
    if doc_type in (DOC_TYPE_SALES_INVOICE, DOC_TYPE_QUOTATION):
        flow.append(
            build_sales_quotation_footer_table(
                prepared_by=payload.get("prepared_by"),
                printed_by=payload.get("printed_by"),
                served_by=payload.get("served_by"),
                with_border=False,
            )
        )
        flow.append(Spacer(1, 4 * mm))
    if doc_type == DOC_TYPE_SALES_INVOICE:
        tag_center = ParagraphStyle(
            name="sales_pdf_tagline",
            parent=st["detail"],
            alignment=TA_CENTER,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#333333"),
        )
        kra_any = bool(
            (payload.get("kra_receipt_number") or "").strip()
            or (payload.get("kra_signature") or "").strip()
            or payload.get("kra_qr_png_bytes")
        )
        if not kra_any:
            flow.append(Paragraph("<b>Powered by SightOps</b>", tag_center))

    # ----- 7. Approval block (purchase order only) -----
    if doc_type == DOC_TYPE_PURCHASE_ORDER:
        flow.extend(
            build_approval_block_flowables(
                approver_name=payload.get("approver_name") or "",
                approved_at_str=payload.get("approved_at_str") or "—",
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
    """Format approval datetime for PDF; uses actual approved_at, displayed in local time."""
    if dt is None:
        return "—"
    if hasattr(dt, "astimezone") and getattr(dt, "tzinfo", None) is not None:
        try:
            dt = dt.astimezone()  # convert to server local time for display
        except Exception:
            pass
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
    prepared_by: Optional[str] = None,
    printed_by: Optional[str] = None,
    served_by: Optional[str] = None,
) -> bytes:
    """Build A4 PDF for a sales quotation. Logo right, company left; footer: prepared/printed/served."""
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
        "prepared_by": prepared_by,
        "printed_by": printed_by,
        "served_by": served_by,
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
    items: Optional[List[Dict[str, Any]]] = None,
    total_exclusive: Optional[Decimal] = None,
    vat_amount: Optional[Decimal] = None,
    total_inclusive: Optional[Decimal] = None,
    notes: Optional[str] = None,
    till_number: Optional[str] = None,
    paybill: Optional[str] = None,
    prepared_by: Optional[str] = None,
    printed_by: Optional[str] = None,
    served_by: Optional[str] = None,
    kra_receipt_number: Optional[str] = None,
    kra_signature: Optional[str] = None,
    kra_qr_code: Optional[str] = None,
    kra_submitted_at: Optional[datetime] = None,
    kra_cu_device_serial: Optional[str] = None,
    kra_invoice_number: Optional[str] = None,
    etims_trader_invoicing_system_name: Optional[str] = None,
    fiscal_receipt: bool = False,
    show_batch_expiry: bool = False,
) -> bytes:
    """Build A4 PDF for a sales invoice. Logo right, company left; footer: prepared/printed/served, till; no status."""
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
    # Customer defaults to "Walk in"; payment/till/paybill go in one line in metadata (no extra_client for Payment).
    payload = {
        "company_name": company_name,
        "company_address": company_address,
        "company_phone": company_phone,
        "company_pin": company_pin,
        "company_logo_bytes": company_logo_bytes,
        "branch_name": branch_name,
        "branch_address": branch_address,
        "document_title": "TAX INVOICE" if fiscal_receipt else "CASH RECEIPT",
        "non_fiscal_warning": None if fiscal_receipt else "THIS IS NOT A TAX INVOICE",
        "document_number": invoice_no or "",
        "metadata_rows": metadata,
        "client_label": "Customer",
        "client_name": (customer_name or "").strip() or "Walk in",
        "extra_client_rows": extra_client if extra_client else None,
        "payment_mode": payment_mode,
        "till_number": till_number,
        "paybill": (paybill or "").strip() or None,
        "prepared_by": prepared_by,
        "printed_by": printed_by,
        "served_by": served_by,
        "items": items,
        "total_exclusive": total_exclusive,
        "vat_amount": vat_amount,
        "total_inclusive": total_inclusive,
        "notes": notes,
        "kra_receipt_number": (kra_receipt_number or "").strip() or None,
        "kra_invoice_number": (kra_invoice_number or kra_receipt_number or "").strip() or None,
        "kra_signature": (kra_signature or "").strip() or None,
        "kra_qr_png_bytes": kra_qr_png_bytes(kra_qr_code),
        "kra_submitted_at": kra_submitted_at,
        "kra_cu_device_serial": (kra_cu_device_serial or "").strip() or None,
        "etims_trader_invoicing_system_name": (etims_trader_invoicing_system_name or "").strip() or None,
        "show_batch_expiry": show_batch_expiry,
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


def build_customer_statement_pdf(
    *,
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    company_logo_bytes: Optional[bytes] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    customer_name: str,
    customer_pin: Optional[str] = None,
    from_date: date,
    to_date: date,
    opening_balance: Decimal,
    closing_balance: Decimal,
    lines: List[Dict[str, Any]],
    prepared_by: Optional[str] = None,
    generated_at_utc: Optional[str] = None,
    integrity_status: str = "PASS",
    doctrine: str = "operational_ar_v1",
    integrity_warnings: Optional[List[str]] = None,
    statement_type: str = "summary",
) -> bytes:
    """
    Operational AR customer statement PDF.
    On integrity FAIL, adds a prominent DRAFT watermark (not for external use).
    """
    integrity_fail = (integrity_status or "").upper() == "FAIL"
    st_type = (statement_type or "summary").strip().lower()
    styles = get_document_styles()
    detail_style = styles.get("detail_small") or styles["detail"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=20 * mm)

    def _watermark(canv, _doc):
        if not integrity_fail:
            return
        canv.saveState()
        canv.setFont("Helvetica-Bold", 42)
        canv.setFillColor(colors.HexColor("#cc0000"), alpha=0.12)
        canv.translate(A4[0] / 2, A4[1] / 2)
        canv.rotate(35)
        canv.drawCentredString(0, 0, "DRAFT — NOT FOR EXTERNAL USE")
        canv.restoreState()

    story: List[Any] = []
    header = build_document_header(
        company_name=company_name,
        company_address=company_address,
        company_phone=company_phone,
        company_pin=company_pin,
        company_logo_bytes=company_logo_bytes,
        branch_name=branch_name,
        branch_address=branch_address,
    )
    story.append(header)
    story.append(Spacer(1, 7 * mm))
    title = "CUSTOMER ACCOUNT STATEMENT"
    if st_type == "detailed":
        title += " (DETAILED)"
    story.append(Paragraph(title, styles["heading"]))
    story.append(Spacer(1, 6))
    gen_at = generated_at_utc or datetime.now(timezone.utc).isoformat()
    meta = [
        ("Customer:", customer_name),
        ("PIN:", customer_pin or "—"),
        ("Period:", f"{_format_date(from_date)} to {_format_date(to_date)}"),
        ("Generated (UTC):", gen_at[:19].replace("T", " ") if gen_at else "—"),
        ("Prepared by:", prepared_by or "—"),
        ("Doctrine:", doctrine),
        ("Integrity:", integrity_status),
    ]
    meta_table = Table([[Paragraph(xml_escape(k), styles["detail"]), Paragraph(xml_escape(str(v)), styles["detail"])] for k, v in meta], colWidths=[90, 380])
    meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(meta_table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Opening balance: {_money(opening_balance)}", styles["detail"]))
    # A4 content width ≈ 174mm after margins — narrow numeric cols, wide description.
    col_date = 16 * mm
    col_desc = 78 * mm
    col_ref = 24 * mm
    col_debit = 16 * mm
    col_credit = 16 * mm
    col_balance = 18 * mm
    col_widths = [col_date, col_desc, col_ref, col_debit, col_credit, col_balance]

    header_style = ParagraphStyle(
        "StmtHeader",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8,
        spaceAfter=0,
    )

    def _stmt_desc_cell(text: str, *, is_detail: bool) -> Paragraph:
        safe = xml_escape(str(text or ""))
        style = _STMT_DESC_DETAIL_STYLE if is_detail else _STMT_DESC_STYLE
        return Paragraph(safe, style)

    def _stmt_ref_cell(text: str) -> Paragraph:
        safe = xml_escape(str(text or "—"))
        return Paragraph(safe, _STMT_REF_STYLE)

    table_data: List[List[Any]] = [
        [
            Paragraph("Date", header_style),
            Paragraph("Description", header_style),
            Paragraph("Reference", header_style),
            Paragraph("Debit", header_style),
            Paragraph("Credit", header_style),
            Paragraph("Balance", header_style),
        ]
    ]
    for line in lines:
        is_detail = bool(line.get("is_detail"))
        desc = str(line.get("description") or line.get("entry_type") or "")
        if is_detail and line.get("line_amount") is not None:
            desc = f"{desc} — {_money(line.get('line_amount'))}"
        ref = str(line.get("reference") or ("—" if not is_detail else ""))
        table_data.append(
            [
                _format_date(line.get("date")) if not is_detail else "",
                _stmt_desc_cell(desc, is_detail=is_detail),
                _stmt_ref_cell(ref) if not is_detail else Paragraph("", _STMT_REF_STYLE),
                _money(line.get("debit")) if not is_detail else "",
                _money(line.get("credit")) if not is_detail else "",
                _money(line.get("balance")) if not is_detail else "",
            ]
        )
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("FONTSIZE", (3, 1), (-1, -1), 6.5),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (0, 0), (2, -1), "LEFT"),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Closing balance:</b> {_money(closing_balance)}", styles["detail"]))
    if integrity_warnings:
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Integrity notes:</b>", styles["detail"]))
        for w in integrity_warnings[:8]:
            story.append(Paragraph(f"• {xml_escape(w)}", detail_style))
    if integrity_fail:
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                "<font color='#b91c1c'><b>This statement failed operational AR reconciliation. "
                "Do not issue externally without investigation.</b></font>",
                styles["detail"],
            )
        )

    doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    return buf.getvalue()


def _money(v) -> str:
    try:
        d = Decimal(str(v or 0))
        return f"{d:,.2f}"
    except Exception:
        return str(v or "0.00")
