"""
Purchase Order PDF generation (approved PO with company details and approval block).
Used when approving a PO: build PDF, upload to tenant storage, set pdf_path.
Supports embedding logo, stamp, and approver signature when bytes are provided.
"""
from decimal import Decimal
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# Max display sizes for embedded images (preserve aspect ratio)
LOGO_MAX_WIDTH_MM = 40
LOGO_MAX_HEIGHT_MM = 18
STAMP_MAX_WIDTH_MM = 28
STAMP_MAX_HEIGHT_MM = 28
SIGNATURE_MAX_WIDTH_MM = 35
SIGNATURE_MAX_HEIGHT_MM = 15


def _image_flowable_from_bytes(
    data: bytes,
    max_width_mm: float,
    max_height_mm: float,
) -> Optional[RLImage]:
    """Build a ReportLab Image flowable from bytes, scaling to fit within max size."""
    if not data:
        return None
    try:
        from PIL import Image as PILImage
        pil_img = PILImage.open(BytesIO(data))
        w_px, h_px = pil_img.size
        if w_px <= 0 or h_px <= 0:
            return None
        w_pt = max_width_mm * mm
        h_pt = max_height_mm * mm
        scale_w = w_pt / w_px
        scale_h = h_pt / h_px
        scale = min(scale_w, scale_h, 1.0)
        out_w = w_px * scale
        out_h = h_px * scale
        rl_img = RLImage(BytesIO(data), width=out_w, height=out_h)
        return rl_img
    except Exception:
        return None


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
    """
    Build an A4 PDF for an approved purchase order.
    Pass company_logo_bytes, stamp_bytes, signature_bytes to embed images (e.g. from tenant storage).
    Returns PDF bytes for upload to tenant storage.
    """
    items = items or []
    total_amount = total_amount or Decimal("0")
    document_branding = document_branding or {}
    order_date = order_date or datetime.utcnow()
    approved_at = approved_at or datetime.utcnow()

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
    company_detail_style = ParagraphStyle(
        name="CompanyDetail",
        parent=styles["Normal"],
        fontSize=11,
        spaceAfter=2,
    )
    heading_style = ParagraphStyle(
        name="POHeading",
        parent=styles["Heading1"],
        fontSize=14,
        spaceAfter=8,
        alignment=1,
    )
    flow = []

    # ----- Logo (top) -----
    if company_logo_bytes:
        logo_img = _image_flowable_from_bytes(
            company_logo_bytes,
            LOGO_MAX_WIDTH_MM,
            LOGO_MAX_HEIGHT_MM,
        )
        if logo_img:
            flow.append(logo_img)
            flow.append(Spacer(1, 4 * mm))

    # ----- Company / Branch -----
    flow.append(Paragraph(company_name or "—", company_name_style))
    if company_address:
        flow.append(Paragraph(company_address, company_detail_style))
    parts = []
    if company_phone:
        parts.append(f"Ph: {company_phone}")
    if company_pin:
        parts.append(f"PIN: {company_pin}")
    if parts:
        flow.append(Paragraph(" | ".join(parts), company_detail_style))
    if branch_name or branch_address:
        branch_parts = [branch_name or "", branch_address or ""]
        flow.append(Paragraph("Branch: " + " — ".join(p for p in branch_parts if p), company_detail_style))
    flow.append(Spacer(1, 4 * mm))

    # ----- Stamp (company stamp, e.g. compliance) -----
    if stamp_bytes:
        stamp_img = _image_flowable_from_bytes(
            stamp_bytes,
            STAMP_MAX_WIDTH_MM,
            STAMP_MAX_HEIGHT_MM,
        )
        if stamp_img:
            flow.append(stamp_img)
            flow.append(Spacer(1, 4 * mm))

    flow.append(Spacer(1, 2 * mm))

    # ----- Title -----
    flow.append(Paragraph("PURCHASE ORDER", heading_style))
    flow.append(Paragraph(order_number or "", company_detail_style))
    flow.append(Spacer(1, 4 * mm))

    # ----- Order info -----
    order_info = [
        ["Order date:", order_date.strftime("%Y-%m-%d %H:%M") if hasattr(order_date, "strftime") else str(order_date)],
        ["Supplier:", supplier_name],
    ]
    if reference:
        order_info.append(["Reference:", reference])
    t_info = Table(order_info, colWidths=[25 * mm, 80 * mm])
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
        name = (row.get("item_name") or "").strip() or "—"
        qty = row.get("quantity")
        qty_str = f"{qty:,.2f}" if qty is not None else "—"
        unit = row.get("unit_name") or ""
        if unit:
            qty_str = f"{qty_str} {unit}"
        unit_price = row.get("unit_price")
        up_str = f"{unit_price:,.2f}" if unit_price is not None else "—"
        total_price = row.get("total_price")
        tot_str = f"{total_price:,.2f}" if total_price is not None else "—"
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

    # ----- Total -----
    total_str = f"{total_amount:,.2f}"
    flow.append(Paragraph(f"<b>Total: {total_str}</b>", company_detail_style))
    flow.append(Spacer(1, 8 * mm))

    # ----- Approval block (signature image + text) -----
    flow.append(Paragraph("Approval", company_name_style))
    if signature_bytes:
        sig_img = _image_flowable_from_bytes(
            signature_bytes,
            SIGNATURE_MAX_WIDTH_MM,
            SIGNATURE_MAX_HEIGHT_MM,
        )
        if sig_img:
            flow.append(sig_img)
            flow.append(Spacer(1, 2 * mm))
    approval_lines = [f"Approved by: {approver_name}"]
    if approver_designation:
        approval_lines.append(f"Designation: {approver_designation}")
    if approver_ppb_number:
        approval_lines.append(f"PPB No.: {approver_ppb_number}")
    approval_lines.append(
        f"Date: {approved_at.strftime('%Y-%m-%d %H:%M') if hasattr(approved_at, 'strftime') else approved_at}"
    )
    for line in approval_lines:
        flow.append(Paragraph(line, company_detail_style))

    doc.build(flow)
    return buf.getvalue()
