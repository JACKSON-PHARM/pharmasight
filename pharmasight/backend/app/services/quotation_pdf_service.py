"""
Sales Quotation PDF generation (on-demand, no approval).
Used for Download PDF: build PDF from quotation + company/branch, return bytes.
"""
from decimal import Decimal
from datetime import date, datetime
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


def build_quotation_pdf(
    company_name: str,
    company_address: Optional[str] = None,
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
    """
    Build an A4 PDF for a sales quotation.
    Returns PDF bytes for download (no storage).
    """
    items = items or []
    total_exclusive = total_exclusive or Decimal("0")
    vat_amount = vat_amount or Decimal("0")
    total_inclusive = total_inclusive or Decimal("0")
    quotation_date = quotation_date or date.today()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    company_name_style = ParagraphStyle(
        name="CompanyName",
        parent=styles["Normal"],
        fontSize=13,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )
    detail_style = ParagraphStyle(
        name="Detail",
        parent=styles["Normal"],
        fontSize=11,
        spaceAfter=2,
    )
    heading_style = ParagraphStyle(
        name="QuotHeading",
        parent=styles["Heading1"],
        fontSize=14,
        spaceAfter=8,
        alignment=1,
    )
    flow = []

    # ----- Company / Branch -----
    flow.append(Paragraph(company_name or "—", company_name_style))
    if company_address:
        flow.append(Paragraph(company_address, detail_style))
    if branch_name or branch_address:
        branch_parts = [branch_name or "", branch_address or ""]
        flow.append(Paragraph("Branch: " + " — ".join(p for p in branch_parts if p), detail_style))
    flow.append(Spacer(1, 6 * mm))

    # ----- Title -----
    flow.append(Paragraph("SALES QUOTATION", heading_style))
    flow.append(Paragraph(quotation_no or "", detail_style))
    flow.append(Spacer(1, 4 * mm))

    # ----- Quotation info -----
    info_rows = [
        ["Date:", quotation_date.strftime("%Y-%m-%d") if hasattr(quotation_date, "strftime") else str(quotation_date)],
        ["Customer:", (customer_name or "—").strip()],
    ]
    if valid_until:
        info_rows.append(["Valid until:", valid_until.strftime("%Y-%m-%d") if hasattr(valid_until, "strftime") else str(valid_until)])
    if reference:
        info_rows.append(["Reference:", reference])
    t_info = Table(info_rows, colWidths=[28 * mm, 80 * mm])
    t_info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(t_info)
    flow.append(Spacer(1, 6 * mm))

    # ----- Items: Description | Qty | Unit Price | Total -----
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
        unit_price = row.get("unit_price_exclusive") if "unit_price_exclusive" in row else row.get("unit_price")
        up_str = f"{unit_price:,.2f}" if unit_price is not None else "—"
        line_total = row.get("line_total_inclusive") if "line_total_inclusive" in row else row.get("total")
        if line_total is None:
            line_total = row.get("line_total_exclusive")
        tot_str = f"{line_total:,.2f}" if line_total is not None else "—"
        data.append([name, qty_str, up_str, tot_str])
    if len(data) == 1:
        data.append(["—", "—", "—", "—"])
    t_items = Table(data, colWidths=col_widths, repeatRows=1)
    t_items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t_items)
    flow.append(Spacer(1, 4 * mm))

    # ----- Totals -----
    flow.append(Paragraph(f"<b>Net: {total_exclusive:,.2f}</b>", detail_style))
    flow.append(Paragraph(f"<b>VAT: {vat_amount:,.2f}</b>", detail_style))
    flow.append(Paragraph(f"<b>Total: {total_inclusive:,.2f}</b>", detail_style))
    if notes:
        flow.append(Spacer(1, 4 * mm))
        flow.append(Paragraph(f"Notes: {notes}", detail_style))

    doc.build(flow)
    return buf.getvalue()
