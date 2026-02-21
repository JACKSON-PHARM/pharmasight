"""
Central PDF building blocks for all transaction documents (PO, sales invoice, quotation, GRN, etc.).
Ensures consistent: header (company + logo) with border, document metadata + client with border,
and approval block with stamp (bottom-right, faded) and signature overlay (solid).
"""
from io import BytesIO
from typing import Any, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Flowable,
    Image as RLImage,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# Max display sizes (mm)
LOGO_MAX_WIDTH_MM = 40
LOGO_MAX_HEIGHT_MM = 18
STAMP_MAX_WIDTH_MM = 32
STAMP_MAX_HEIGHT_MM = 32
SIGNATURE_MAX_WIDTH_MM = 38
SIGNATURE_MAX_HEIGHT_MM = 16

# Stamp opacity (faded); signature is 1.0 (solid)
STAMP_OPACITY = 0.45


def _escape(s: str) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
        return RLImage(BytesIO(data), width=out_w, height=out_h)
    except Exception:
        return None


def _image_size_from_bytes(data: bytes, max_width_mm: float, max_height_mm: float) -> Tuple[float, float]:
    """Return (width_pt, height_pt) for image from bytes, scaled to fit max mm."""
    if not data:
        return (0.0, 0.0)
    try:
        from PIL import Image as PILImage
        pil_img = PILImage.open(BytesIO(data))
        w_px, h_px = pil_img.size
        if w_px <= 0 or h_px <= 0:
            return (0.0, 0.0)
        w_pt = max_width_mm * mm
        h_pt = max_height_mm * mm
        scale = min(w_pt / w_px, h_pt / h_px, 1.0)
        return (w_px * scale, h_px * scale)
    except Exception:
        return (0.0, 0.0)


class StampAndSignatureFlowable(Flowable):
    """
    Draws stamp (faded) at bottom-right, then signature (solid) overlaid on it.
    Used in the approval block so stamp is not at top-center.
    """

    def __init__(
        self,
        stamp_bytes: Optional[bytes] = None,
        signature_bytes: Optional[bytes] = None,
    ):
        self.stamp_bytes = stamp_bytes
        self.signature_bytes = signature_bytes
        self._stamp_w, self._stamp_h = _image_size_from_bytes(
            stamp_bytes or b"", STAMP_MAX_WIDTH_MM, STAMP_MAX_HEIGHT_MM
        )
        self._sig_w, self._sig_h = _image_size_from_bytes(
            signature_bytes or b"", SIGNATURE_MAX_WIDTH_MM, SIGNATURE_MAX_HEIGHT_MM
        )
        # Box size: max of both + small padding; min size so we have room
        pad = 4 * mm
        self._width = max(self._stamp_w, self._sig_w) + pad
        self._height = max(self._stamp_h, self._sig_h) + pad

    def wrap(self, availWidth, availHeight):
        return (self._width, self._height)

    def draw(self):
        canvas = self.canv
        if not self.stamp_bytes and not self.signature_bytes:
            return
        # Our flowable is positioned at (0,0) bottom-left by the frame; we draw in our box
        # Right-align: draw so right edge of images aligns with our right edge
        x_right = self._width
        y_base = 0

        # 1) Draw stamp first (faded), right-aligned at bottom
        if self.stamp_bytes and self._stamp_w > 0 and self._stamp_h > 0:
            canvas.saveState()
            canvas.setFillAlpha(STAMP_OPACITY)
            canvas.setStrokeAlpha(STAMP_OPACITY)
            try:
                reader = ImageReader(BytesIO(self.stamp_bytes))
                x_stamp = x_right - self._stamp_w
                canvas.drawImage(reader, x_stamp, y_base, width=self._stamp_w, height=self._stamp_h)
            except Exception:
                pass
            canvas.restoreState()

        # 2) Draw signature (solid) overlaid, right-aligned
        if self.signature_bytes and self._sig_w > 0 and self._sig_h > 0:
            canvas.saveState()
            canvas.setFillAlpha(1.0)
            canvas.setStrokeAlpha(1.0)
            try:
                reader = ImageReader(BytesIO(self.signature_bytes))
                x_sig = x_right - self._sig_w
                # Slight vertical nudge so signature sits nicely over stamp
                y_sig = y_base + (self._height - self._sig_h) * 0.3
                canvas.drawImage(reader, x_sig, y_sig, width=self._sig_w, height=self._sig_h)
            except Exception:
                pass
            canvas.restoreState()


def get_document_styles() -> dict:
    """Shared styles for all transaction documents."""
    styles = getSampleStyleSheet()
    return {
        "company_name": ParagraphStyle(
            name="CompanyName",
            parent=styles["Normal"],
            fontSize=13,
            fontName="Helvetica-Bold",
            spaceAfter=4,
        ),
        "detail": ParagraphStyle(
            name="Detail",
            parent=styles["Normal"],
            fontSize=11,
            spaceAfter=2,
        ),
        "heading": ParagraphStyle(
            name="DocHeading",
            parent=styles["Heading1"],
            fontSize=14,
            spaceAfter=8,
            alignment=1,
        ),
        "detail_small": ParagraphStyle(
            name="DetailSmall",
            parent=styles["Normal"],
            fontSize=10,
            leading=12,
            spaceAfter=0,
        ),
    }


def build_document_header(
    company_name: str,
    company_address: Optional[str] = None,
    company_phone: Optional[str] = None,
    company_pin: Optional[str] = None,
    branch_name: Optional[str] = None,
    branch_address: Optional[str] = None,
    company_logo_bytes: Optional[bytes] = None,
    with_border: bool = True,
) -> Table:
    """
    Header: company details (left), logo (right). Optional border around the block.
    Used by PO, sales invoice, quotation, GRN, supplier invoice.
    """
    st = get_document_styles()
    left_lines = [f"<b>{_escape(company_name or '—')}</b>"]
    if company_address:
        left_lines.append(_escape(company_address))
    parts = []
    if company_phone:
        parts.append(f"Ph: {company_phone}")
    if company_pin:
        parts.append(f"PIN: {company_pin}")
    if parts:
        left_lines.append(" | ".join(parts))
    if branch_name or branch_address:
        branch_parts = [branch_name or "", branch_address or ""]
        left_lines.append("Branch: " + " — ".join(p for p in branch_parts if p))
    left_para = Paragraph(
        "<br/>".join(left_lines),
        ParagraphStyle(name="CompanyBlock", parent=st["detail"], fontSize=11, leading=14, spaceAfter=0),
    )
    right_cell = _image_flowable_from_bytes(
        company_logo_bytes, LOGO_MAX_WIDTH_MM, LOGO_MAX_HEIGHT_MM
    ) if company_logo_bytes else Spacer(1, 2 * mm)
    table = Table([[left_para, right_cell]], colWidths=[110 * mm, 75 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]
    if with_border:
        style.append(("BOX", (0, 0), (-1, -1), 0.5, colors.grey))
    table.setStyle(TableStyle(style))
    return table


def build_document_metadata_client_table(
    metadata_rows: List[Tuple[str, str]],
    client_label: str,
    client_name: str,
    extra_client_rows: Optional[List[Tuple[str, str]]] = None,
    with_border: bool = True,
) -> Table:
    """
    One bordered table: document metadata (e.g. Order date, Reference) and client block
    (e.g. Supplier: X / Customer: Y). Used by PO (supplier), sales (customer), quotation (customer), etc.
    """
    extra_client_rows = extra_client_rows or []
    data = list(metadata_rows)
    data.append(("", ""))  # blank spacer row to separate metadata from client section
    data.append((client_label + ":", (client_name or "—").strip()))
    data.extend(extra_client_rows)
    col_widths = [40 * mm, 145 * mm]
    t = Table(data, colWidths=col_widths)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]
    if with_border:
        style.append(("BOX", (0, 0), (-1, -1), 0.5, colors.grey))
    t.setStyle(TableStyle(style))
    return t


def build_payment_details_table(
    till_number: Optional[str] = None,
    paybill: Optional[str] = None,
    with_border: bool = True,
) -> Table:
    """
    Payment details block for sales invoice only (Till number, Paybill).
    Not used for purchase orders, quotations, or supplier invoices.
    """
    rows = []
    if till_number:
        rows.append(("Till:", till_number.strip()))
    if paybill:
        rows.append(("Paybill:", paybill.strip()))
    if not rows:
        return Table([["—", "—"]], colWidths=[25 * mm, 160 * mm])
    col_widths = [40 * mm, 145 * mm]
    t = Table(rows, colWidths=col_widths)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]
    if with_border:
        style.append(("BOX", (0, 0), (-1, -1), 0.5, colors.grey))
    t.setStyle(TableStyle(style))
    return t


def build_approval_block_flowables(
    approver_name: str,
    approved_at_str: str,
    approver_designation: Optional[str] = None,
    approver_ppb_number: Optional[str] = None,
    stamp_bytes: Optional[bytes] = None,
    signature_bytes: Optional[bytes] = None,
) -> List[Any]:
    """
    Approval section: left = text (Approved by, Designation, PPB No., Date);
    right = stamp (faded) with signature (solid) overlay at bottom-right.
    Returns list of flowables (heading + table with text left, stamp+signature right).
    """
    st = get_document_styles()
    flow = []
    flow.append(Paragraph("Approval", st["heading"]))
    approval_lines = [f"Approved by: {approver_name}"]
    if approver_designation:
        approval_lines.append(f"Designation: {approver_designation}")
    if approver_ppb_number:
        approval_lines.append(f"PPB No.: {approver_ppb_number}")
    approval_lines.append(f"Date: {approved_at_str}")
    left_block = Paragraph("<br/>".join(approval_lines), ParagraphStyle(
        name="ApprovalText", parent=st["detail"], fontSize=11, leading=14, spaceAfter=0
    ))
    right_block = StampAndSignatureFlowable(stamp_bytes=stamp_bytes, signature_bytes=signature_bytes)
    # Table: left column text, right column stamp+signature (right-aligned in cell)
    approval_table = Table(
        [[left_block, right_block]],
        colWidths=[90 * mm, 95 * mm],
    )
    approval_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(approval_table)
    return flow
