"""
On-demand PDF generation for transaction documents (sales invoice, GRN, supplier invoice).
Same flow pattern as quotation: no approval; build PDF and return bytes for download.
"""
from decimal import Decimal
from datetime import date
from io import BytesIO
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


def _doc_styles():
    styles = getSampleStyleSheet()
    return {
        "company_name": ParagraphStyle(
            name="CompanyName", parent=styles["Normal"],
            fontSize=13, fontName="Helvetica-Bold", spaceAfter=4,
        ),
        "detail": ParagraphStyle(
            name="Detail", parent=styles["Normal"],
            fontSize=11, spaceAfter=2,
        ),
        "heading": ParagraphStyle(
            name="Heading", parent=styles["Heading1"],
            fontSize=14, spaceAfter=8, alignment=1,
        ),
    }


def _items_table(flow, items: List[Dict], detail_style) -> None:
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
        unit_price = row.get("unit_price_exclusive") or row.get("unit_price") or row.get("unit_cost")
        up_str = f"{unit_price:,.2f}" if unit_price is not None else "—"
        line_total = row.get("line_total_inclusive") or row.get("total") or row.get("total_cost") or row.get("line_total_exclusive")
        tot_str = f"{line_total:,.2f}" if line_total is not None else "—"
        data.append([name, qty_str, up_str, tot_str])
    if len(data) == 1:
        data.append(["—", "—", "—", "—"])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)


def build_sales_invoice_pdf(
    company_name: str,
    company_address: Optional[str] = None,
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
) -> bytes:
    """Build A4 PDF for a sales invoice. Returns bytes for download."""
    items = items or []
    total_exclusive = total_exclusive or Decimal("0")
    vat_amount = vat_amount or Decimal("0")
    total_inclusive = total_inclusive or Decimal("0")
    invoice_date = invoice_date or date.today()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    st = _doc_styles()
    flow = []
    flow.append(Paragraph(company_name or "—", st["company_name"]))
    if company_address:
        flow.append(Paragraph(company_address, st["detail"]))
    if branch_name or branch_address:
        flow.append(Paragraph("Branch: " + " — ".join(p for p in [branch_name or "", branch_address or ""] if p), st["detail"]))
    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph("SALES INVOICE", st["heading"]))
    flow.append(Paragraph(invoice_no or "", st["detail"]))
    flow.append(Spacer(1, 4 * mm))
    info = [["Date:", invoice_date.strftime("%Y-%m-%d") if hasattr(invoice_date, "strftime") else str(invoice_date)], ["Customer:", (customer_name or "—").strip()]]
    if customer_phone:
        info.append(["Phone:", customer_phone])
    if payment_mode:
        info.append(["Payment:", payment_mode])
    if status:
        info.append(["Status:", status])
    t_info = Table(info, colWidths=[28*mm, 80*mm])
    t_info.setStyle(TableStyle([("FONTNAME", (0,0), (-1,-1), "Helvetica"), ("FONTSIZE", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 2), ("TOPPADDING", (0,0), (-1,-1), 2)]))
    flow.append(t_info)
    flow.append(Spacer(1, 6 * mm))
    _items_table(flow, items, st["detail"])
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(f"<b>Net: {total_exclusive:,.2f}</b>", st["detail"]))
    flow.append(Paragraph(f"<b>VAT: {vat_amount:,.2f}</b>", st["detail"]))
    flow.append(Paragraph(f"<b>Total: {total_inclusive:,.2f}</b>", st["detail"]))
    if notes:
        flow.append(Spacer(1, 4 * mm))
        flow.append(Paragraph(f"Notes: {notes}", st["detail"]))
    doc.build(flow)
    return buf.getvalue()


def build_grn_pdf(
    company_name: str,
    company_address: Optional[str] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    grn_no: str = "",
    date_received: Optional[date] = None,
    supplier_name: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    total_cost: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> bytes:
    """Build A4 PDF for a GRN. Returns bytes for download."""
    items = items or []
    total_cost = total_cost or Decimal("0")
    date_received = date_received or date.today()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    st = _doc_styles()
    flow = []
    flow.append(Paragraph(company_name or "—", st["company_name"]))
    if company_address:
        flow.append(Paragraph(company_address, st["detail"]))
    if branch_name or branch_address:
        flow.append(Paragraph("Branch: " + " — ".join(p for p in [branch_name or "", branch_address or ""] if p), st["detail"]))
    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph("GOODS RECEIVED NOTE", st["heading"]))
    flow.append(Paragraph(grn_no or "", st["detail"]))
    flow.append(Spacer(1, 4 * mm))
    info = [["Date received:", date_received.strftime("%Y-%m-%d") if hasattr(date_received, "strftime") else str(date_received)], ["Supplier:", (supplier_name or "—").strip()]]
    t_info = Table(info, colWidths=[28*mm, 80*mm])
    t_info.setStyle(TableStyle([("FONTNAME", (0,0), (-1,-1), "Helvetica"), ("FONTSIZE", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 2), ("TOPPADDING", (0,0), (-1,-1), 2)]))
    flow.append(t_info)
    flow.append(Spacer(1, 6 * mm))
    _items_table(flow, items, st["detail"])
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(f"<b>Total cost: {total_cost:,.2f}</b>", st["detail"]))
    if notes:
        flow.append(Spacer(1, 4 * mm))
        flow.append(Paragraph(f"Notes: {notes}", st["detail"]))
    doc.build(flow)
    return buf.getvalue()


def build_supplier_invoice_pdf(
    company_name: str,
    company_address: Optional[str] = None,
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
    """Build A4 PDF for a supplier (purchase) invoice. Returns bytes for download."""
    items = items or []
    total_exclusive = total_exclusive or Decimal("0")
    vat_amount = vat_amount or Decimal("0")
    total_inclusive = total_inclusive or Decimal("0")
    invoice_date = invoice_date or date.today()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    st = _doc_styles()
    flow = []
    flow.append(Paragraph(company_name or "—", st["company_name"]))
    if company_address:
        flow.append(Paragraph(company_address, st["detail"]))
    if branch_name or branch_address:
        flow.append(Paragraph("Branch: " + " — ".join(p for p in [branch_name or "", branch_address or ""] if p), st["detail"]))
    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph("SUPPLIER INVOICE", st["heading"]))
    flow.append(Paragraph(invoice_number or "", st["detail"]))
    flow.append(Spacer(1, 4 * mm))
    info = [["Date:", invoice_date.strftime("%Y-%m-%d") if hasattr(invoice_date, "strftime") else str(invoice_date)], ["Supplier:", (supplier_name or "—").strip()]]
    if reference:
        info.append(["Reference:", reference])
    if status:
        info.append(["Status:", status])
    t_info = Table(info, colWidths=[28*mm, 80*mm])
    t_info.setStyle(TableStyle([("FONTNAME", (0,0), (-1,-1), "Helvetica"), ("FONTSIZE", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 2), ("TOPPADDING", (0,0), (-1,-1), 2)]))
    flow.append(t_info)
    flow.append(Spacer(1, 6 * mm))
    _items_table(flow, items, st["detail"])
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(f"<b>Net: {total_exclusive:,.2f}</b>", st["detail"]))
    flow.append(Paragraph(f"<b>VAT: {vat_amount:,.2f}</b>", st["detail"]))
    flow.append(Paragraph(f"<b>Total: {total_inclusive:,.2f}</b>", st["detail"]))
    if notes:
        flow.append(Spacer(1, 4 * mm))
        flow.append(Paragraph(f"Notes: {notes}", st["detail"]))
    doc.build(flow)
    return buf.getvalue()
