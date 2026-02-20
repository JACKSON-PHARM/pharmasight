"""
Generate immutable Purchase Order PDF for approved POs.
Embeds company logo, stamp, approver signature and PPB/compliance info.
"""
import io
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

from app.services.tenant_storage_service import download_file

logger = logging.getLogger(__name__)


def _get_image_bytes(stored_path: Optional[str], max_size: int = 120) -> Optional[bytes]:
    if not stored_path or not stored_path.startswith("tenant-assets/"):
        return None
    return download_file(stored_path)


def build_po_pdf(
    *,
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    company_logo_path: Optional[str] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    order_number: str,
    order_date: datetime,
    supplier_name: str,
    reference: Optional[str] = None,
    items: list,
    total_amount: Decimal,
    document_branding: Optional[Dict[str, Any]] = None,
    stamp_path: Optional[str] = None,
    approver_name: Optional[str] = None,
    approver_designation: Optional[str] = None,
    approver_ppb_number: Optional[str] = None,
    signature_path: Optional[str] = None,
    approved_at: Optional[datetime] = None,
) -> bytes:
    """
    Build PO PDF and return bytes. Items: list of dicts with item_name, quantity, unit_name,
    unit_price, total_price, is_controlled (optional).
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    story = []

    # Header: logo (if path and bytes) + company info
    header_data = []
    if company_logo_path:
        logo_bytes = _get_image_bytes(company_logo_path)
        if logo_bytes:
            try:
                img = Image(io.BytesIO(logo_bytes), width=40 * mm, height=20 * mm)
                header_data.append(img)
            except Exception:
                pass
    company_lines = [company_name]
    if company_address:
        company_lines.append(company_address)
    if company_phone:
        company_lines.append(f"TEL: {company_phone}")
    if company_pin:
        company_lines.append(f"PIN: {company_pin}")
    header_data.append(Paragraph("<br/>".join(company_lines), styles["Normal"]))
    story.append(Table([header_data], colWidths=[50 * mm, 140 * mm]))
    story.append(Spacer(1, 8 * mm))

    # Title
    story.append(Paragraph("PURCHASE ORDER", ParagraphStyle(name="Title", fontSize=16, spaceAfter=6)))
    story.append(Paragraph(order_number, styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    # PO details
    order_date_str = order_date.strftime("%B %d, %Y") if isinstance(order_date, datetime) else str(order_date)
    details = [
        ["Date:", order_date_str, "Supplier:", supplier_name or "—"],
        ["Branch:", branch_name or "—", "Reference:", reference or "—"],
    ]
    story.append(Table(details, colWidths=[25 * mm, 70 * mm, 30 * mm, 70 * mm]))
    story.append(Spacer(1, 8 * mm))

    # Line items
    table_data = [["Item", "Description", "Qty", "Unit Price", "Total"]]
    for it in items:
        desc = (it.get("item_name") or "—") + (" (Controlled Item)" if it.get("is_controlled") else "")
        table_data.append([
            it.get("item_code") or "—",
            desc,
            str(it.get("quantity", 0)),
            f"KES {float(it.get('unit_price') or 0):,.2f}",
            f"KES {float(it.get('total_price') or 0):,.2f}",
        ])
    table_data.append(["", "", "", "Total:", f"KES {float(total_amount):,.2f}"])
    t = Table(table_data, colWidths=[25 * mm, 70 * mm, 20 * mm, 35 * mm, 35 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(t)
    story.append(Spacer(1, 12 * mm))

    # Approval block: stamp (left) + signature (right)
    approval_cells = []
    if stamp_path:
        stamp_bytes = _get_image_bytes(stamp_path)
        if stamp_bytes:
            try:
                stamp_img = Image(io.BytesIO(stamp_bytes), width=45 * mm, height=45 * mm)
                approval_cells.append(stamp_img)
            except Exception:
                approval_cells.append(Paragraph("", styles["Normal"]))
        else:
            approval_cells.append(Paragraph("", styles["Normal"]))
    else:
        approval_cells.append(Paragraph("", styles["Normal"]))
    right_block = []
    if approver_name:
        right_block.append(f"<b>Approved By:</b> {approver_name}")
    if approver_designation:
        right_block.append(approver_designation)
    if approver_ppb_number:
        right_block.append(f"PPB No: {approver_ppb_number}")
    if signature_path:
        sig_bytes = _get_image_bytes(signature_path)
        if sig_bytes:
            try:
                sig_img = Image(io.BytesIO(sig_bytes), width=40 * mm, height=15 * mm)
                right_block.append(sig_img)
            except Exception:
                pass
    if approved_at:
        right_block.append(f"Approved On: {approved_at.strftime('%B %d, %Y, %H:%M')}")
    approval_cells.append(Paragraph("<br/>".join(right_block), styles["Normal"]))
    story.append(Table([approval_cells], colWidths=[50 * mm, 120 * mm]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "This document was digitally approved and generated via Pharmasight.",
        ParagraphStyle(name="Footer", fontSize=8, textColor=colors.grey),
    ))
    if approved_at:
        story.append(Paragraph(
            f"Approval timestamp: {approved_at.isoformat()}",
            ParagraphStyle(name="Footer2", fontSize=7, textColor=colors.grey),
        ))

    doc.build(story)
    return buffer.getvalue()
