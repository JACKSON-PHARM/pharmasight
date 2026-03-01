"""
Stock Take API routes for multi-user stock take sessions
"""
import io
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from app.dependencies import get_tenant_db, get_current_user
from app.config import settings
from app.models import (
    StockTakeSession, StockTakeCount, StockTakeCounterLock, StockTakeAdjustment,
    User, Item, Branch, Company, UserRole, UserBranchRole, InventoryLedger
)
from decimal import Decimal
from app.schemas.stock_take import (
    StockTakeSessionCreate, StockTakeSessionUpdate, StockTakeSessionResponse,
    StockTakeCountCreate, StockTakeCountBranchCreate, StockTakeCountResponse,
    StockTakeLockResponse, StockTakeLockRequest,
    StockTakeProgressResponse, CounterProgress,
    StockTakeAdjustmentCreate, StockTakeAdjustmentResponse,
    SessionJoinRequest, SessionJoinResponse
)
from app.services.inventory_service import InventoryService
from app.services.snapshot_service import SnapshotService
from app.services.snapshot_refresh_service import SnapshotRefreshService

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================
# Helper Functions
# ============================================

def generate_session_code(db: Session) -> str:
    """
    Generate a unique session code (e.g., ST-MAR25A)
    
    NOTE: This code is INTERNAL ONLY - users never see or use it.
    Users are automatically onboarded when they select a branch in stock take mode.
    The code exists only because the database schema requires it (NOT NULL UNIQUE).
    """
    from sqlalchemy import text
    result = db.execute(text("SELECT generate_stock_take_session_code()"))
    return result.scalar()


def get_user_role(user_id: UUID, branch_id: UUID, db: Session) -> Optional[str]:
    """Get user's role for a branch"""
    role = db.query(UserRole.role_name).join(
        UserBranchRole, UserRole.id == UserBranchRole.role_id
    ).filter(
        and_(
            UserBranchRole.user_id == user_id,
            UserBranchRole.branch_id == branch_id
        )
    ).first()
    return role[0] if role else None


def authorize_stock_take_access(
    user_id: UUID,
    session_id: UUID,
    required_role: str,
    db: Session
) -> bool:
    """
    Authorize user access to stock take operations
    
    Args:
        user_id: User ID
        session_id: Session ID
        required_role: 'admin', 'counter', 'auditor', or 'review'
        db: Database session
    
    Returns:
        True if authorized, False otherwise
    """
    session = db.query(StockTakeSession).filter(StockTakeSession.id == session_id).first()
    if not session:
        return False
    
    user_role = get_user_role(user_id, session.branch_id, db)
    
    # Admin/Auditor can do anything
    if user_role in ['admin', 'auditor', 'Super Admin']:
        return True
    
    # Supervisor can review but not count
    if required_role == 'review' and user_role == 'supervisor':
        return True
    
    # Counter can only count if allowed
    if required_role == 'count' and user_role == 'counter':
        return user_id in (session.allowed_counters or [])
    
    return False


def cleanup_expired_locks(db: Session):
    """Clean up expired locks"""
    from sqlalchemy import text
    db.execute(text("SELECT cleanup_expired_stock_take_locks()"))
    db.commit()


# ============================================
# Stock Take Recording Template (A4 PDF)
# ============================================

def _build_stock_take_template_pdf() -> bytes:
    """Build A4 PDF template: front + back pages with headers for more items."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="Title", parent=styles["Heading1"], fontSize=16, spaceAfter=12
    )
    sub_style = ParagraphStyle(
        name="Sub", parent=styles["Normal"], fontSize=10, spaceAfter=6
    )
    flow = []
    # ----- Page 1 (Front) -----
    flow.append(Paragraph("Stock Take Recording Sheet", title_style))
    flow.append(Paragraph("Front", sub_style))
    flow.append(Spacer(1, 6 * mm))
    placeholders = [
        ["Shelf Name:", "_________________________", "Counted By:", "_________________________"],
        ["Verified By:", "_________________________", "Keyed In By:", "_________________________"],
    ]
    t_place = Table(placeholders, colWidths=[22 * mm, 65 * mm, 22 * mm, 65 * mm])
    t_place.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t_place)
    flow.append(Spacer(1, 8 * mm))
    headers = ["#", "Item Name", "Wholesale Units", "Retail Units", "Expiry Date", "Batch Number"]
    col_widths = [8 * mm, 55 * mm, 28 * mm, 26 * mm, 28 * mm, 35 * mm]
    data1 = [headers]
    for i in range(1, 28):
        data1.append([str(i), "", "", "", "", ""])
    tbl1 = Table(data1, colWidths=col_widths, repeatRows=1)
    tbl1.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(tbl1)
    flow.append(PageBreak())
    # ----- Page 2 (Back) -----
    flow.append(Paragraph("Stock Take Recording Sheet", title_style))
    flow.append(Paragraph("Back", sub_style))
    flow.append(Spacer(1, 6 * mm))
    flow.append(Table(placeholders, colWidths=[22 * mm, 65 * mm, 22 * mm, 65 * mm]))
    flow.append(Spacer(1, 8 * mm))
    data2 = [headers]
    for i in range(28, 55):  # rows 28–54 on back
        data2.append([str(i), "", "", "", "", ""])
    tbl2 = Table(data2, colWidths=col_widths, repeatRows=1)
    tbl2.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(tbl2)
    doc.build(flow)
    return buf.getvalue()


def _build_stock_take_template_html() -> str:
    """Build printable HTML template: front + back pages with headers (same as PDF)."""
    meta = """<table class="meta">
        <tr><td class="label">Shelf Name:</td><td style="width:32%">_________________________</td><td class="label">Counted By:</td><td style="width:32%">_________________________</td></tr>
        <tr><td class="label">Verified By:</td><td>_________________________</td><td class="label">Keyed In By:</td><td>_________________________</td></tr>
    </table>"""
    thead = "<thead><tr><th>#</th><th>Item Name</th><th>Wholesale Units</th><th>Retail Units</th><th>Expiry Date</th><th>Batch Number</th></tr></thead>"
    rows_front = "".join(f'<tr><td>{i}</td><td></td><td></td><td></td><td></td><td></td></tr>' for i in range(1, 28))
    rows_back = "".join(f'<tr><td>{i}</td><td></td><td></td><td></td><td></td><td></td></tr>' for i in range(28, 55))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Take Recording Sheet</title>
    <style>
        @media print {{ body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }} .page-break {{ page-break-before: always; }} }}
        body {{ font-family: Helvetica, Arial, sans-serif; font-size: 12px; margin: 15mm; max-width: 210mm; }}
        h1 {{ font-size: 16px; margin-bottom: 4px; }}
        .page-title {{ font-size: 10px; color: #666; margin-bottom: 8px; }}
        .meta {{ margin-bottom: 10px; border-collapse: collapse; width: 100%; }}
        .meta td {{ padding: 4px 8px; border: 1px solid #ccc; }}
        .meta .label {{ width: 22%; background: #f5f5f5; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
        th, td {{ border: 1px solid #999; padding: 3px 6px; text-align: left; font-size: 11px; }}
        th {{ background: #e8e8e8; }}
        .no-print {{ margin-top: 16px; }}
        @media print {{ .no-print {{ display: none; }} }}
    </style>
</head>
<body>
    <div class="sheet">
        <h1>Stock Take Recording Sheet</h1>
        <p class="page-title">Front</p>
        {meta}
        <table>
            {thead}
            <tbody>{rows_front}</tbody>
        </table>
    </div>
    <div class="sheet page-break">
        <h1>Stock Take Recording Sheet</h1>
        <p class="page-title">Back</p>
        {meta}
        <table>
            {thead}
            <tbody>{rows_back}</tbody>
        </table>
    </div>
    <p class="no-print">Print both pages (Ctrl+P / Cmd+P) or &quot;Save as PDF&quot; to keep a copy.</p>
</body>
</html>"""


@router.get("/template/pdf")
def download_stock_take_template(current_user_and_db: tuple = Depends(get_current_user)):
    """
    Download an A4 PDF template for recording counted drugs during stock take.
    Fields: Item Name, Wholesale Units, Retail Units, Expiry Date, Batch Number.
    Placeholders: Shelf Name, Counted By, Verified By, Keyed In By.
    """
    try:
        pdf_bytes = _build_stock_take_template_pdf()
    except ImportError as e:
        logger.warning("Stock take template PDF: reportlab not installed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF generation unavailable. Install reportlab: pip install reportlab",
        )
    except Exception as e:
        logger.exception("Stock take template PDF generation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF generation failed: {str(e)}",
        )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=stock-take-recording-sheet.pdf"},
    )


@router.get("/template/html", response_class=HTMLResponse)
def get_stock_take_template_html(current_user_and_db: tuple = Depends(get_current_user)):
    """
    Printable HTML template (same layout as PDF). Use when PDF is unavailable
    or user prefers to print from browser (Print → Save as PDF).
    """
    return HTMLResponse(content=_build_stock_take_template_html())


# ============================================
# Session Management Endpoints
# ============================================

@router.post("/sessions", response_model=StockTakeSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    session_data: StockTakeSessionCreate,
    created_by: UUID = Query(..., description="User ID creating the session"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create a new stock take session (Admin/Auditor only)
    
    Only one active session per branch at a time.
    """
    # Check if user is admin/auditor
    user_role = get_user_role(created_by, session_data.branch_id, db)
    if user_role not in ['admin', 'auditor', 'Super Admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and auditors can create stock take sessions"
        )
    
    # Check if there's already an active session for this branch
    existing = db.query(StockTakeSession).filter(
        and_(
            StockTakeSession.branch_id == session_data.branch_id,
            StockTakeSession.status.in_(['DRAFT', 'ACTIVE', 'PAUSED'])
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Branch already has an active session: {existing.session_code}"
        )
    
    # Get company_id from branch
    branch = db.query(Branch).filter(Branch.id == session_data.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    # Generate session code
    session_code = generate_session_code(db)
    
    # Create session
    new_session = StockTakeSession(
        company_id=branch.company_id,
        branch_id=session_data.branch_id,
        session_code=session_code,
        status='DRAFT',
        created_by=created_by,
        allowed_counters=session_data.allowed_counters or [],
        assigned_shelves=session_data.assigned_shelves or {},
        is_multi_user=session_data.is_multi_user,
        notes=session_data.notes
    )
    
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    # Get creator name
    creator = db.query(User).filter(User.id == created_by).first()
    creator_name = creator.full_name if creator else None
    
    return StockTakeSessionResponse(
        id=new_session.id,
        company_id=new_session.company_id,
        branch_id=new_session.branch_id,
        session_code=new_session.session_code,
        status=new_session.status,
        created_by=new_session.created_by,
        allowed_counters=new_session.allowed_counters or [],
        assigned_shelves=new_session.assigned_shelves or {},
        is_multi_user=new_session.is_multi_user,
        notes=new_session.notes,
        started_at=new_session.started_at,
        completed_at=new_session.completed_at,
        created_at=new_session.created_at,
        updated_at=new_session.updated_at,
        creator_name=creator_name,
        counter_count=len(new_session.allowed_counters or []),
        total_items_counted=0,
        total_items_assigned=0
    )


@router.get("/sessions", response_model=List[StockTakeSessionResponse])
def list_sessions(
    branch_id: Optional[UUID] = Query(None, description="Filter by branch"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """List stock take sessions"""
    query = db.query(StockTakeSession)
    
    if branch_id:
        query = query.filter(StockTakeSession.branch_id == branch_id)
    
    if status_filter:
        query = query.filter(StockTakeSession.status == status_filter)
    
    sessions = query.order_by(desc(StockTakeSession.created_at)).all()
    
    result = []
    for session in sessions:
        creator = db.query(User).filter(User.id == session.created_by).first()
        
        # Count items
        count_query = db.query(func.count(StockTakeCount.id)).filter(
            StockTakeCount.session_id == session.id
        )
        total_counted = count_query.scalar() or 0
        
        result.append(StockTakeSessionResponse(
            id=session.id,
            company_id=session.company_id,
            branch_id=session.branch_id,
            session_code=session.session_code,
            status=session.status,
            created_by=session.created_by,
            allowed_counters=session.allowed_counters or [],
            assigned_shelves=session.assigned_shelves or {},
            is_multi_user=session.is_multi_user,
            notes=session.notes,
            started_at=session.started_at,
            completed_at=session.completed_at,
            created_at=session.created_at,
            updated_at=session.updated_at,
            creator_name=creator.full_name if creator else None,
            counter_count=len(session.allowed_counters or []),
            total_items_counted=total_counted,
            total_items_assigned=0  # Would need to calculate from assigned_shelves
        ))
    
    return result


@router.get("/sessions/{session_id}", response_model=StockTakeSessionResponse)
def get_session(
    session_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get a stock take session by ID"""
    session = db.query(StockTakeSession).filter(StockTakeSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    creator = db.query(User).filter(User.id == session.created_by).first()
    
    # Count items
    total_counted = db.query(func.count(StockTakeCount.id)).filter(
        StockTakeCount.session_id == session.id
    ).scalar() or 0
    
    return StockTakeSessionResponse(
        id=session.id,
        company_id=session.company_id,
        branch_id=session.branch_id,
        session_code=session.session_code,
        status=session.status,
        created_by=session.created_by,
        allowed_counters=session.allowed_counters or [],
        assigned_shelves=session.assigned_shelves or {},
        is_multi_user=session.is_multi_user,
        notes=session.notes,
        started_at=session.started_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
        creator_name=creator.full_name if creator else None,
        counter_count=len(session.allowed_counters or []),
        total_items_counted=total_counted,
        total_items_assigned=0
    )


@router.get("/sessions/code/{session_code}", response_model=StockTakeSessionResponse)
def get_session_by_code(
    session_code: str,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get a stock take session by code"""
    session = db.query(StockTakeSession).filter(
        StockTakeSession.session_code == session_code.upper()
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    creator = db.query(User).filter(User.id == session.created_by).first()
    
    total_counted = db.query(func.count(StockTakeCount.id)).filter(
        StockTakeCount.session_id == session.id
    ).scalar() or 0
    
    return StockTakeSessionResponse(
        id=session.id,
        company_id=session.company_id,
        branch_id=session.branch_id,
        session_code=session.session_code,
        status=session.status,
        created_by=session.created_by,
        allowed_counters=session.allowed_counters or [],
        assigned_shelves=session.assigned_shelves or {},
        is_multi_user=session.is_multi_user,
        notes=session.notes,
        started_at=session.started_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
        creator_name=creator.full_name if creator else None,
        counter_count=len(session.allowed_counters or []),
        total_items_counted=total_counted,
        total_items_assigned=0
    )


@router.put("/sessions/{session_id}", response_model=StockTakeSessionResponse)
def update_session(
    session_id: UUID,
    session_update: StockTakeSessionUpdate,
    user_id: UUID = Query(..., description="User ID making the update"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Update a stock take session (Admin/Auditor only)"""
    session = db.query(StockTakeSession).filter(StockTakeSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check authorization
    user_role = get_user_role(user_id, session.branch_id, db)
    if user_role not in ['admin', 'auditor', 'Super Admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and auditors can update sessions"
        )
    
    # Update fields
    if session_update.status:
        if session_update.status == 'ACTIVE' and session.status == 'DRAFT':
            session.started_at = datetime.utcnow()
        elif session_update.status in ['COMPLETED', 'CANCELLED']:
            session.completed_at = datetime.utcnow()
        session.status = session_update.status
    
    if session_update.allowed_counters is not None:
        session.allowed_counters = session_update.allowed_counters
    
    if session_update.assigned_shelves is not None:
        session.assigned_shelves = session_update.assigned_shelves
    
    if session_update.notes is not None:
        session.notes = session_update.notes
    
    db.commit()
    db.refresh(session)
    
    return get_session(session_id, current_user_and_db, db)


@router.post("/sessions/{session_id}/start", response_model=StockTakeSessionResponse)
def start_session(
    session_id: UUID,
    user_id: UUID = Query(..., description="User ID starting the session"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Start a stock take session (Admin/Auditor only)"""
    session = db.query(StockTakeSession).filter(StockTakeSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.status != 'DRAFT':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is not in DRAFT status (current: {session.status})"
        )
    
    user_role = get_user_role(user_id, session.branch_id, db)
    if user_role not in ['admin', 'auditor', 'Super Admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and auditors can start sessions"
        )
    
    session.status = 'ACTIVE'
    session.started_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    
    return get_session(session_id, current_user_and_db, db)


# ============================================
# Count Management Endpoints
# ============================================

@router.post("/counts", status_code=status.HTTP_201_CREATED)
def create_count(
    count_data: dict,
    counted_by: UUID = Query(..., description="User ID making the count"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create a stock take count
    
    Supports both formats:
    1. Session-based: {session_id, item_id, counted_quantity, ...}
    2. Branch-based: {branch_id, item_id, counted_quantity, item_updates, ...}
    """
    try:
        # Initialize variables
        item = None
        item_id = None
        branch_id = None
        session_id = None
        shelf_location = None
        batch_number = None
        expiry_date = None
        unit_name = None
        quantity_in_unit = None
        notes = None
        item_updates = None
        counted_quantity = 0
        
        # Determine if branch-based or session-based
        if 'branch_id' in count_data:
            # Branch-based flow
            branch_id = UUID(count_data['branch_id'])
            item_id = UUID(count_data['item_id'])
            shelf_location = count_data.get('shelf_location')
            batch_number = count_data.get('batch_number')
            expiry_date = count_data.get('expiry_date')
            unit_name = count_data.get('unit_name')
            quantity_in_unit = count_data.get('quantity_in_unit')
            notes = count_data.get('notes')
            item_updates = count_data.get('item_updates')
            
            # Validate required fields
            if not shelf_location or not shelf_location.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Shelf location is required. Please specify where the count is being performed."
                )
            
            # Get item to check batch/expiry requirements
            item = db.query(Item).filter(Item.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
            
            # Validate batch/expiry if required
            if item.is_controlled and not batch_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Batch number is required for this item"
                )
            
            if item.track_expiry and not expiry_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Expiry date is required for this item"
                )
            
            # Convert quantity to base units if unit_name is provided
            if unit_name and quantity_in_unit is not None:
                try:
                    from app.services.inventory_service import InventoryService
                    counted_quantity = InventoryService.convert_to_base_units(
                        db, item_id, float(quantity_in_unit), unit_name
                    )
                except ValueError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid unit '{unit_name}': {str(e)}"
                    )
            else:
                # Fallback: use counted_quantity directly (assumed to be in base units)
                counted_quantity = int(count_data.get('counted_quantity', 0))
                quantity_in_unit = counted_quantity
                unit_name = item.base_unit  # Default to base unit
            
            # Get active session for branch
            session = db.query(StockTakeSession).filter(
                and_(
                    StockTakeSession.branch_id == branch_id,
                    StockTakeSession.status == 'ACTIVE'
                )
            ).first()
            
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No active stock take session for this branch"
                )
            
            session_id = session.id
            
        elif 'session_id' in count_data:
            # Session-based flow
            session_id = UUID(count_data['session_id'])
            item_id = UUID(count_data['item_id'])
            shelf_location = count_data.get('shelf_location')
            batch_number = count_data.get('batch_number')
            expiry_date = count_data.get('expiry_date')
            unit_name = count_data.get('unit_name')
            quantity_in_unit = count_data.get('quantity_in_unit')
            notes = count_data.get('notes')
            item_updates = None
            
            # Validate required fields
            if not shelf_location or not shelf_location.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Shelf location is required. Please specify where the count is being performed."
                )
            
            # Get item to check batch/expiry requirements and convert units
            item = db.query(Item).filter(Item.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
            
            # Validate batch/expiry if required
            if item.is_controlled and not batch_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Batch number is required for this item"
                )
            
            if item.track_expiry and not expiry_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Expiry date is required for this item"
                )
            
            # Convert quantity to base units if unit_name is provided
            if unit_name and quantity_in_unit is not None:
                try:
                    from app.services.inventory_service import InventoryService
                    counted_quantity = InventoryService.convert_to_base_units(
                        db, item_id, float(quantity_in_unit), unit_name
                    )
                except ValueError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid unit '{unit_name}': {str(e)}"
                    )
            else:
                # Fallback: use counted_quantity directly (assumed to be in base units)
                counted_quantity = int(count_data.get('counted_quantity', 0))
                quantity_in_unit = counted_quantity
                unit_name = item.base_unit  # Default to base unit
            
            # Get session
            session = db.query(StockTakeSession).filter(
                StockTakeSession.id == session_id
            ).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            
            # Check authorization for session-based
            if session.allowed_counters and len(session.allowed_counters) > 0:
                if not authorize_stock_take_access(counted_by, session_id, 'count', db):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You are not authorized to count items in this session"
                    )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either session_id or branch_id must be provided"
            )
        
        # Check session is active
        if session.status != 'ACTIVE':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session is not active (current: {session.status})"
            )
        
        # Get system quantity
        system_quantity = InventoryService.get_current_stock(
            db, item_id, session.branch_id
        )
        
        # Calculate variance
        variance = counted_quantity - system_quantity
        
        # Parse expiry_date if provided
        expiry_date_parsed = None
        if expiry_date:
            from datetime import datetime as dt
            if isinstance(expiry_date, str):
                expiry_date_parsed = dt.strptime(expiry_date, '%Y-%m-%d').date()
            else:
                expiry_date_parsed = expiry_date
        
        # Validate shelf name uniqueness (no two shelves can have same name in same session)
        # Check if shelf name already exists with different counter
        existing_shelf = db.query(StockTakeCount).filter(
            and_(
                StockTakeCount.session_id == session_id,
                StockTakeCount.shelf_location == shelf_location,
                StockTakeCount.counted_by != counted_by
            )
        ).first()
        
        if existing_shelf:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Shelf name '{shelf_location}' already exists and was counted by another user. Please use a different shelf name."
            )
        
        # Create count (allow multiple counts per item per shelf - different shelves = different batches)
        # Check if count exists for same item, shelf, batch, and expiry (same batch on same shelf)
        existing = db.query(StockTakeCount).filter(
            and_(
                StockTakeCount.session_id == session_id,
                StockTakeCount.item_id == item_id,
                StockTakeCount.counted_by == counted_by,
                StockTakeCount.shelf_location == shelf_location,
                StockTakeCount.batch_number == (batch_number if batch_number else None),
                StockTakeCount.expiry_date == expiry_date_parsed
            )
        ).first()
        
        if existing:
            # Update existing count for same shelf/batch
            existing.counted_quantity = counted_quantity
            existing.system_quantity = system_quantity
            existing.variance = variance
            existing.unit_name = unit_name
            existing.quantity_in_unit = quantity_in_unit
            existing.notes = notes
            existing.counted_at = datetime.utcnow()
            # Reset verification status if updating (counter is correcting)
            if existing.verification_status == 'REJECTED':
                existing.verification_status = 'PENDING'
                existing.verified_by = None
                existing.verified_at = None
                existing.rejection_reason = None
            db.commit()
            db.refresh(existing)
            count = existing
        else:
            # Create new count (different shelf or batch)
            count = StockTakeCount(
                session_id=session_id,
                item_id=item_id,
                counted_by=counted_by,
                shelf_location=shelf_location,
                batch_number=batch_number,
                expiry_date=expiry_date_parsed,
                unit_name=unit_name,
                quantity_in_unit=quantity_in_unit,
                counted_quantity=counted_quantity,
                system_quantity=system_quantity,
                variance=variance,
                notes=notes
            )
            db.add(count)
            db.commit()
            db.refresh(count)
        
        # Update item if provided and allowed (branch-based flow)
        if item_updates and 'branch_id' in count_data:
            # item already queried above in branch-based flow
            if item:
                if 'pack_size' in item_updates:
                    item.pack_size = item_updates['pack_size']
                if 'breaking_bulk_unit' in item_updates:
                    item.breaking_bulk_unit = item_updates['breaking_bulk_unit']
                db.commit()
        
        # Ensure item is available for response
        # Item was already queried in both branch-based and session-based flows above
        # But ensure it's available here
        if not item:
            item = db.query(Item).filter(Item.id == item_id).first()
        
        # Get counter name
        counter = db.query(User).filter(User.id == counted_by).first()
        
        logger.info(f"Count saved: item {item_id}, quantity {counted_quantity}, user {counted_by}")
        
        return {
            "success": True,
            "id": str(count.id),
            "session_id": str(count.session_id),
            "item_id": str(count.item_id),
            "counted_by": str(count.counted_by),
            "shelf_location": count.shelf_location,
            "batch_number": count.batch_number,
            "expiry_date": count.expiry_date.isoformat() if count.expiry_date else None,
            "unit_name": count.unit_name,
            "quantity_in_unit": float(count.quantity_in_unit) if count.quantity_in_unit else None,
            "counted_quantity": count.counted_quantity,
            "system_quantity": count.system_quantity,
            "variance": count.variance,
            "notes": count.notes,
            "verification_status": count.verification_status or 'PENDING',
            "counted_at": count.counted_at.isoformat() if count.counted_at else None,
            "created_at": count.created_at.isoformat() if count.created_at else None,
            "item_name": item.name if item else None,
            "counter_name": counter.full_name if counter else None
        }
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Invalid data format in create_count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid data format: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error saving count: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save count: {str(e)}"
        )


@router.get("/sessions/{session_id}/counts", response_model=List[StockTakeCountResponse])
def list_counts(
    session_id: UUID,
    counter_id: Optional[UUID] = Query(None, description="Filter by counter"),
    db: Session = Depends(get_tenant_db)
):
    """List counts for a session"""
    query = db.query(StockTakeCount).filter(
        StockTakeCount.session_id == session_id
    )
    
    if counter_id:
        query = query.filter(StockTakeCount.counted_by == counter_id)
    
    counts = query.order_by(desc(StockTakeCount.counted_at)).all()
    
    result = []
    for count in counts:
        item = db.query(Item).filter(Item.id == count.item_id).first()
        counter = db.query(User).filter(User.id == count.counted_by).first()
        
        result.append(StockTakeCountResponse(
            id=count.id,
            session_id=count.session_id,
            item_id=count.item_id,
            counted_by=count.counted_by,
            shelf_location=count.shelf_location,
            counted_quantity=count.counted_quantity,
            system_quantity=count.system_quantity,
            variance=count.variance,
            notes=count.notes,
            counted_at=count.counted_at,
            created_at=count.created_at,
            item_name=item.name if item else None,
            counter_name=counter.full_name if counter else None
        ))
    
    return result


# ============================================
# Lock Management Endpoints
# ============================================

@router.post("/locks", response_model=StockTakeLockResponse)
def lock_item(
    lock_request: StockTakeLockRequest,
    counter_id: UUID = Query(..., description="User ID requesting the lock"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Lock an item for counting (prevents duplicate counting)
    
    Lock expires after 5 minutes.
    """
    cleanup_expired_locks(db)
    
    # Check if item is already locked
    existing_lock = db.query(StockTakeCounterLock).filter(
        and_(
            StockTakeCounterLock.session_id == lock_request.session_id,
            StockTakeCounterLock.item_id == lock_request.item_id,
            StockTakeCounterLock.expires_at > datetime.utcnow()
        )
    ).first()
    
    if existing_lock:
        if existing_lock.counter_id != counter_id:
            counter = db.query(User).filter(User.id == existing_lock.counter_id).first()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Item is being counted by {counter.full_name if counter else 'another user'}"
            )
        else:
            # Extend lock
            existing_lock.expires_at = datetime.utcnow() + timedelta(minutes=5)
            existing_lock.locked_at = datetime.utcnow()
            db.commit()
            db.refresh(existing_lock)
            
            item = db.query(Item).filter(Item.id == lock_request.item_id).first()
            counter = db.query(User).filter(User.id == counter_id).first()
            
            return StockTakeLockResponse(
                id=existing_lock.id,
                session_id=existing_lock.session_id,
                item_id=existing_lock.item_id,
                counter_id=existing_lock.counter_id,
                locked_at=existing_lock.locked_at,
                expires_at=existing_lock.expires_at,
                counter_name=counter.full_name if counter else None,
                item_name=item.name if item else None,
                is_expired=False
            )
    
    # Create new lock
    new_lock = StockTakeCounterLock(
        session_id=lock_request.session_id,
        item_id=lock_request.item_id,
        counter_id=counter_id,
        expires_at=datetime.utcnow() + timedelta(minutes=5)
    )
    
    db.add(new_lock)
    db.commit()
    db.refresh(new_lock)
    
    item = db.query(Item).filter(Item.id == lock_request.item_id).first()
    counter = db.query(User).filter(User.id == counter_id).first()
    
    return StockTakeLockResponse(
        id=new_lock.id,
        session_id=new_lock.session_id,
        item_id=new_lock.item_id,
        counter_id=new_lock.counter_id,
        locked_at=new_lock.locked_at,
        expires_at=new_lock.expires_at,
        counter_name=counter.full_name if counter else None,
        item_name=item.name if item else None,
        is_expired=False
    )


@router.get("/sessions/{session_id}/locks", response_model=List[StockTakeLockResponse])
def list_locks(
    session_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """List active locks for a session"""
    cleanup_expired_locks(db)
    
    locks = db.query(StockTakeCounterLock).filter(
        and_(
            StockTakeCounterLock.session_id == session_id,
            StockTakeCounterLock.expires_at > datetime.utcnow()
        )
    ).all()
    
    result = []
    for lock in locks:
        item = db.query(Item).filter(Item.id == lock.item_id).first()
        counter = db.query(User).filter(User.id == lock.counter_id).first()
        
        result.append(StockTakeLockResponse(
            id=lock.id,
            session_id=lock.session_id,
            item_id=lock.item_id,
            counter_id=lock.counter_id,
            locked_at=lock.locked_at,
            expires_at=lock.expires_at,
            counter_name=counter.full_name if counter else None,
            item_name=item.name if item else None,
            is_expired=False
        ))
    
    return result


# ============================================
# Progress Endpoints
# ============================================

@router.get("/sessions/{session_id}/progress", response_model=StockTakeProgressResponse)
def get_progress(session_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get progress for a stock take session"""
    session = db.query(StockTakeSession).filter(StockTakeSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get all counts
    counts = db.query(StockTakeCount).filter(
        StockTakeCount.session_id == session_id
    ).all()
    
    # Get active locks
    cleanup_expired_locks(db)
    locks = db.query(StockTakeCounterLock).filter(
        and_(
            StockTakeCounterLock.session_id == session_id,
            StockTakeCounterLock.expires_at > datetime.utcnow()
        )
    ).all()
    
    # Calculate counter progress
    counter_progress = {}
    assigned_shelves = session.assigned_shelves or {}
    
    for counter_id in session.allowed_counters or []:
        counter = db.query(User).filter(User.id == counter_id).first()
        if not counter:
            continue
        
        counter_counts = [c for c in counts if c.counted_by == counter_id]
        counter_shelves = assigned_shelves.get(str(counter_id), [])
        
        # Estimate items assigned (would need actual item-shelf mapping)
        items_assigned = len(counter_shelves) * 10  # Rough estimate
        
        counter_progress[counter_id] = CounterProgress(
            counter_id=counter_id,
            counter_name=counter.full_name or counter.email,
            assigned_shelves=counter_shelves,
            items_counted=len(counter_counts),
            items_assigned=items_assigned,
            progress_percent=(len(counter_counts) / items_assigned * 100) if items_assigned > 0 else 0
        )
    
    # Get recent counts (last 20)
    recent_counts_query = db.query(StockTakeCount).filter(
        StockTakeCount.session_id == session_id
    ).order_by(desc(StockTakeCount.counted_at)).limit(20)
    
    recent_counts = []
    for count in recent_counts_query.all():
        item = db.query(Item).filter(Item.id == count.item_id).first()
        counter = db.query(User).filter(User.id == count.counted_by).first()
        
        recent_counts.append(StockTakeCountResponse(
            id=count.id,
            session_id=count.session_id,
            item_id=count.item_id,
            counted_by=count.counted_by,
            shelf_location=count.shelf_location,
            counted_quantity=count.counted_quantity,
            system_quantity=count.system_quantity,
            variance=count.variance,
            notes=count.notes,
            counted_at=count.counted_at,
            created_at=count.created_at,
            item_name=item.name if item else None,
            counter_name=counter.full_name if counter else None
        ))
    
    # Calculate overall progress
    total_items = 100  # Would need to calculate from assigned shelves
    total_counted = len(set(c.item_id for c in counts))
    total_locked = len(locks)
    
    return StockTakeProgressResponse(
        session_id=session.id,
        session_code=session.session_code,
        status=session.status,
        total_items=total_items,
        total_counted=total_counted,
        total_locked=total_locked,
        progress_percent=(total_counted / total_items * 100) if total_items > 0 else 0,
        counters=list(counter_progress.values()),
        recent_counts=recent_counts
    )


# ============================================
# Session Join Endpoints
# ============================================

@router.post("/sessions/join", response_model=SessionJoinResponse)
def join_session(
    join_request: SessionJoinRequest,
    user_id: UUID = Query(..., description="User ID joining the session"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Join a stock take session with a code"""
    session = db.query(StockTakeSession).filter(
        StockTakeSession.session_code == join_request.session_code.upper()
    ).first()
    
    if not session:
        return SessionJoinResponse(
            success=False,
            message="Session not found"
        )
    
    if not session.is_multi_user:
        return SessionJoinResponse(
            success=False,
            message="This session does not allow additional counters"
        )
    
    if session.status != 'ACTIVE':
        return SessionJoinResponse(
            success=False,
            message=f"Session is not active (current: {session.status})"
        )
    
    # Add user to allowed_counters if not already there
    if user_id not in (session.allowed_counters or []):
        if session.allowed_counters is None:
            session.allowed_counters = []
        session.allowed_counters.append(user_id)
        db.commit()
        db.refresh(session)
    
    creator = db.query(User).filter(User.id == session.created_by).first()
    total_counted = db.query(func.count(StockTakeCount.id)).filter(
        StockTakeCount.session_id == session.id
    ).scalar() or 0
    
    session_response = StockTakeSessionResponse(
        id=session.id,
        company_id=session.company_id,
        branch_id=session.branch_id,
        session_code=session.session_code,
        status=session.status,
        created_by=session.created_by,
        allowed_counters=session.allowed_counters or [],
        assigned_shelves=session.assigned_shelves or {},
        is_multi_user=session.is_multi_user,
        notes=session.notes,
        started_at=session.started_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
        creator_name=creator.full_name if creator else None,
        counter_count=len(session.allowed_counters or []),
        total_items_counted=total_counted,
        total_items_assigned=0
    )
    
    return SessionJoinResponse(
        success=True,
        session=session_response,
        message="Successfully joined session"
    )


# ============================================
# Branch-Based Stock Take Endpoints (Automatic Participation)
# ============================================

@router.get("/branch/{branch_id}/status")
def get_branch_status(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get stock take status for a branch
    
    Returns whether the branch is currently in stock take mode.
    """
    try:
        # Check for active session
        active_session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if active_session:
            creator = db.query(User).filter(User.id == active_session.created_by).first()
            total_counted = db.query(func.count(func.distinct(StockTakeCount.item_id))).filter(
                StockTakeCount.session_id == active_session.id
            ).scalar() or 0
            
            return {
                "inStockTake": True,
                "sessionId": str(active_session.id),
                "sessionCode": active_session.session_code,
                "session": {
                    "id": str(active_session.id),
                    "company_id": str(active_session.company_id),
                    "branch_id": str(active_session.branch_id),
                    "session_code": active_session.session_code,
                    "status": active_session.status,
                    "created_by": str(active_session.created_by) if active_session.created_by else None,
                    "allowed_counters": [str(c) for c in (active_session.allowed_counters or [])],
                    "assigned_shelves": active_session.assigned_shelves or {},
                    "is_multi_user": active_session.is_multi_user,
                    "notes": active_session.notes,
                    "started_at": active_session.started_at.isoformat() if active_session.started_at else None,
                    "completed_at": active_session.completed_at.isoformat() if active_session.completed_at else None,
                    "created_at": active_session.created_at.isoformat() if active_session.created_at else None,
                    "updated_at": active_session.updated_at.isoformat() if active_session.updated_at else None,
                    "creator_name": creator.full_name if creator else None,
                    "counter_count": len(active_session.allowed_counters or []),
                    "total_items_counted": total_counted,
                    "total_items_assigned": 0
                }
            }
        else:
            return {
                "inStockTake": False,
                "sessionId": None,
                "sessionCode": None,
                "session": None
            }
    except Exception as e:
        logger.error(f"Error getting branch status for {branch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get branch status: {str(e)}"
        )


@router.get("/branch/{branch_id}/has-drafts")
def check_draft_documents(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Check if branch has any draft documents that would prevent stock take
    
    Returns detailed information about draft documents with counts by type.
    """
    try:
        from app.models.sale import SalesInvoice, CreditNote
        from app.models.purchase import SupplierInvoice
        
        reasons = []
        draft_details = {
            "sales": 0,
            "purchases": 0,
            "credit_notes": 0
        }
        
        # Check for draft sales invoices
        # Also check for NULL status (backward compatibility)
        try:
            draft_sales = db.query(SalesInvoice).filter(
                and_(
                    SalesInvoice.branch_id == branch_id,
                    or_(
                        SalesInvoice.status == 'DRAFT',
                        SalesInvoice.status.is_(None)  # NULL status treated as draft
                    )
                )
            ).count()
            
            draft_details["sales"] = draft_sales
            if draft_sales > 0:
                reasons.append(f"{draft_sales} draft sales invoice(s) must be completed or cancelled")
                logger.info(f"Found {draft_sales} draft sales invoices for branch {branch_id}")
        except Exception as e:
            logger.warning(f"Error checking draft sales invoices: {str(e)}")
        
        # Check for draft purchase invoices
        # Also check for NULL status (backward compatibility - old invoices might have NULL status)
        try:
            draft_purchase_query = db.query(SupplierInvoice).filter(
                and_(
                    SupplierInvoice.branch_id == branch_id,
                    or_(
                        SupplierInvoice.status == 'DRAFT',
                        SupplierInvoice.status.is_(None)  # NULL status treated as draft
                    )
                )
            )
            draft_purchases = draft_purchase_query.count()
            
            # Get actual invoice IDs for debugging (first 5)
            draft_invoice_ids = [str(inv.id) for inv in draft_purchase_query.limit(5).all()]
            
            draft_details["purchases"] = draft_purchases
            if draft_purchases > 0:
                reasons.append(f"{draft_purchases} draft purchase invoice(s) must be completed or cancelled")
                logger.info(f"Found {draft_purchases} draft purchase invoices for branch {branch_id}: {draft_invoice_ids[:3]}")
                # Add debug info (only in development)
                if settings.DEBUG:
                    draft_details["purchase_invoice_ids"] = draft_invoice_ids
        except Exception as e:
            logger.warning(f"Error checking draft purchase invoices: {str(e)}")
        
        # Check for draft credit notes (if they have status field)
        # Note: CreditNote might not have status, check model first
        try:
            # CreditNote doesn't have status field, so skip this check
            draft_credits = 0
            draft_details["credit_notes"] = draft_credits
        except Exception as e:
            logger.warning(f"Error checking draft credit notes: {str(e)}")
            pass
        
        result = {
            "hasDrafts": len(reasons) > 0,
            "reasons": reasons,
            "details": draft_details
        }
        
        logger.info(f"Draft check for branch {branch_id}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error checking draft documents for branch {branch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check draft documents: {str(e)}"
        )


@router.post("/branch/{branch_id}/start")
def start_branch_stock_take(
    branch_id: UUID,
    user_id: UUID = Query(None, description="User ID starting the stock take (optional)"),
    db: Session = Depends(get_tenant_db)
):
    """
    Start stock take for a branch (automatic participation)
    
    Creates an active session and sets branch to stock take mode.
    All users in the branch automatically participate - NO session codes needed.
    
    IMPORTANT: Session codes are generated internally (database requirement) but
    are NEVER shown to users. Users are automatically redirected when they select
    a branch that is in stock take mode.
    """
    try:
        # Check for existing active session
        existing = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if existing:
            logger.warning(f"Attempt to start stock take for branch {branch_id} but session {existing.id} already active")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch already has an active stock take session"
            )
        
        # Get branch
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            logger.error(f"Branch {branch_id} not found when starting stock take")
            raise HTTPException(status_code=404, detail="Branch not found")
        
        # Generate INTERNAL session code (database requirement - NOT user-facing)
        # IMPORTANT: Users are automatically onboarded - they NEVER see or use this code
        # The code exists only because database schema requires NOT NULL UNIQUE
        session_code = None
        try:
            session_code = generate_session_code(db)
            # Verify the code fits DB column (VARCHAR(10) or VARCHAR(20) after migration)
            if session_code and len(session_code) > 10:
                session_code = session_code[:10]
                logger.warning(f"Generated code truncated to 10 chars for DB: {session_code}")
            logger.info(f"Generated internal session code: {session_code} for branch {branch_id} (users won't see this)")
        except Exception as e:
            logger.error(f"Failed to generate session code: {str(e)}", exc_info=True)
            # Rollback the transaction if it failed (this is critical!)
            try:
                db.rollback()
            except Exception as rollback_error:
                logger.error(f"Failed to rollback transaction: {str(rollback_error)}")
            # Fallback: use short code that fits VARCHAR(10) until migration to VARCHAR(20) is run
            import uuid
            fallback_code = f"ST-{str(uuid.uuid4()).replace('-', '')[:6].upper()}"  # ST- + 6 hex = 9 chars
            if len(fallback_code) > 10:
                fallback_code = fallback_code[:10]
            session_code = fallback_code
            logger.warning(f"Using fallback internal session code: {session_code}")
        
        # Ensure we have a session code (database requires NOT NULL); max 10 chars until DB is VARCHAR(20)
        if not session_code:
            import uuid
            session_code = f"ST-{str(uuid.uuid4()).replace('-', '')[:6].upper()}"
            if len(session_code) > 10:
                session_code = session_code[:10]
        
        # Create session with auto-join enabled (all users can participate)
        # Empty allowed_counters means all users can participate
        new_session = StockTakeSession(
            company_id=branch.company_id,
            branch_id=branch_id,
            session_code=session_code,
            status='ACTIVE',  # Start immediately
            created_by=user_id,  # User who started it (or None if system)
            allowed_counters=[],  # Empty = all users can participate
            assigned_shelves={},
            is_multi_user=True,
            notes=f"Automatic branch stock take for {branch.name}",
            started_at=datetime.utcnow()
        )
        
        db.add(new_session)
        try:
            db.commit()
            db.refresh(new_session)
            logger.info(f"Stock take session {new_session.id} started successfully for branch {branch_id}")
        except Exception as commit_error:
            logger.error(f"Failed to commit stock take session: {str(commit_error)}", exc_info=True)
            db.rollback()
            # Check if it's a transaction error
            error_str = str(commit_error)
            if "InFailedSqlTransaction" in error_str or "current transaction is aborted" in error_str.lower():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database transaction error. Please ensure the database migration has been run. Error: " + error_str
                )
            raise
        
        return {
            "success": True,
            "sessionId": str(new_session.id),
            # Note: sessionCode included for debugging but not shown to users
            "sessionCode": session_code,
            "message": "Stock take started successfully"
        }
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error starting stock take for branch {branch_id}: {str(e)}", exc_info=True)
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.error(f"Failed to rollback after error: {str(rollback_error)}")
        
        error_str = str(e)
        if "InFailedSqlTransaction" in error_str or "current transaction is aborted" in error_str.lower():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database transaction error. The session_code column may still be VARCHAR(6). Please run the database migration: database/fix_stock_take_session_code_length.sql"
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start stock take: {error_str}"
        )


@router.get("/branch/{branch_id}/my-counts")
def get_my_counts(
    branch_id: UUID,
    user_id: UUID = Query(..., description="User ID"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get counts for current user in branch's active stock take"""
    try:
        # Get active session
        session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if not session:
            return []
        
        # Check if session is completed (counts are locked)
        is_completed = session.status == 'COMPLETED'
        
        # Get user's counts
        counts = db.query(StockTakeCount).filter(
            and_(
                StockTakeCount.session_id == session.id,
                StockTakeCount.counted_by == user_id
            )
        ).order_by(desc(StockTakeCount.counted_at)).all()
        
        result = []
        for count in counts:
            item = db.query(Item).filter(Item.id == count.item_id).first()
            
            result.append({
                "id": str(count.id),
                "session_id": str(count.session_id),
                "item_id": str(count.item_id),
                "counted_by": str(count.counted_by),
                "item_name": item.name if item else None,
                "shelf_location": count.shelf_location,
                "batch_number": count.batch_number,
                "expiry_date": count.expiry_date.isoformat() if count.expiry_date else None,
                "unit_name": count.unit_name,
                "quantity_in_unit": float(count.quantity_in_unit) if count.quantity_in_unit else None,
                "counted_quantity": count.counted_quantity,
                "system_quantity": count.system_quantity,
                "variance": count.variance,
                "difference": count.variance,  # Alias for frontend
                "notes": count.notes,
                "counted_at": count.counted_at.isoformat() if count.counted_at else None,
                "created_at": count.created_at.isoformat() if count.created_at else None,
                "is_completed": is_completed,  # Flag to indicate if session is completed (counts locked)
                "verification_status": count.verification_status or 'PENDING'
            })
        
        return result
    except Exception as e:
        logger.error(f"Error getting counts for user {user_id} in branch {branch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get counts: {str(e)}"
        )


@router.get("/branch/{branch_id}/progress")
def get_branch_progress(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get progress for branch's active stock take"""
    try:
        # Get active session
        session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if not session:
            return {
                "counted_items": 0,
                "total_items": 0,
                "total_counted": 0,
                "percentage": 0
            }
        
        # Get unique items counted
        unique_items = db.query(func.count(func.distinct(StockTakeCount.item_id))).filter(
            StockTakeCount.session_id == session.id
        ).scalar() or 0
        
        # Estimate total items (would need actual item count for branch)
        # For now, use a placeholder - backend should calculate from items table
        total_items_query = db.query(func.count(Item.id)).filter(
            Item.company_id == session.company_id
        )
        total_items = total_items_query.scalar() or 0
        
        percentage = (unique_items / total_items * 100) if total_items > 0 else 0
        
        return {
            "counted_items": unique_items,
            "total_items": total_items,
            "total_counted": unique_items,  # Alias
            "percentage": round(percentage, 2)
        }
    except Exception as e:
        logger.error(f"Error getting progress for branch {branch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get progress: {str(e)}"
        )


@router.get("/branch/{branch_id}/locks")
def get_branch_locks(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get active locks for branch's stock take"""
    cleanup_expired_locks(db)
    
    # Get active session
    session = db.query(StockTakeSession).filter(
        and_(
            StockTakeSession.branch_id == branch_id,
            StockTakeSession.status == 'ACTIVE'
        )
    ).first()
    
    if not session:
        return []
    
    # Get active locks
    locks = db.query(StockTakeCounterLock).filter(
        and_(
            StockTakeCounterLock.session_id == session.id,
            StockTakeCounterLock.expires_at > datetime.utcnow()
        )
    ).all()
    
    result = []
    for lock in locks:
        item = db.query(Item).filter(Item.id == lock.item_id).first()
        counter = db.query(User).filter(User.id == lock.counter_id).first()
        
        result.append({
            "item_id": str(lock.item_id),
            "counter_id": str(lock.counter_id),
            "counter_name": counter.full_name if counter else None,
            "item_name": item.name if item else None,
            "expires_at": lock.expires_at.isoformat() if lock.expires_at else None
        })
    
    return result


@router.post("/branch/{branch_id}/complete")
def complete_branch_stock_take(
    branch_id: UUID,
    user_id: UUID = Query(None, description="User ID completing the stock take (optional)"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Complete stock take for branch.
    Row-level lock on session prevents concurrent complete; entire operation in one transaction.
    """
    try:
        # Lock active session row before processing to prevent concurrent complete
        session = (
            db.query(StockTakeSession)
            .filter(
                and_(
                    StockTakeSession.branch_id == branch_id,
                    StockTakeSession.status == 'ACTIVE'
                )
            )
            .with_for_update()
            .first()
        )
        if not session:
            logger.warning(f"Attempt to complete stock take for branch {branch_id} but no active session found")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active stock take session found for this branch"
            )
        
        # Get all counts
        counts = db.query(StockTakeCount).filter(
            StockTakeCount.session_id == session.id
        ).all()
        
        # Get branch and item details for ledger entries
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        # Use provided user_id or session creator or first counter
        completing_user_id = user_id or session.created_by
        if not completing_user_id and counts:
            completing_user_id = counts[0].counted_by
        
        if not completing_user_id:
            logger.warning(f"No user_id available for completing stock take session {session.id}")
            completing_user_id = session.created_by  # Fallback to session creator
        
        # Item IDs that were counted (any count in this session)
        counted_item_ids = {c.item_id for c in counts}

        # Uncounted items with stock: zero out (record in ledger so stock becomes 0)
        # Compute BEFORE applying count adjustments so we use pre-completion stock.
        items_with_stock = db.query(InventoryLedger.item_id).filter(
            and_(
                InventoryLedger.branch_id == branch_id,
            )
        ).group_by(InventoryLedger.item_id).having(
            func.sum(InventoryLedger.quantity_delta) > 0
        ).all()
        items_with_stock_ids = {r[0] for r in items_with_stock}
        uncounted_with_stock = [
            (item_id, InventoryService.get_current_stock(db, item_id, branch_id))
            for item_id in (items_with_stock_ids - counted_item_ids)
        ]
        uncounted_with_stock = [(iid, q) for iid, q in uncounted_with_stock if q > 0]

        from app.services.canonical_pricing import CanonicalPricingService

        # 1) Update inventory for each count (variance adjustments)
        items_updated = 0
        errors = []
        for count in counts:
            try:
                variance = count.variance
                if variance != 0:
                    item = db.query(Item).filter(Item.id == count.item_id).first()
                    if not item:
                        logger.warning(f"Item {count.item_id} not found when completing stock take")
                        continue
                    unit_cost = CanonicalPricingService.get_best_available_cost(db, count.item_id, branch_id, branch.company_id)
                    total_cost = abs(variance) * unit_cost
                    ledger_entry = InventoryLedger(
                        company_id=branch.company_id,
                        branch_id=branch_id,
                        item_id=count.item_id,
                        transaction_type='ADJUSTMENT',
                        reference_type='STOCK_TAKE',
                        reference_id=session.id,
                        quantity_delta=variance,
                        unit_cost=unit_cost,
                        total_cost=total_cost,
                        created_by=completing_user_id,
                        notes='Stock take count adjustment'
                    )
                    db.add(ledger_entry)
                    SnapshotService.upsert_inventory_balance(db, branch.company_id, branch_id, count.item_id, variance)
                    SnapshotRefreshService.schedule_snapshot_refresh(db, branch.company_id, branch_id, item_id=count.item_id)
                    items_updated += 1
            except Exception as e:
                logger.error(f"Error updating inventory for item {count.item_id}: {str(e)}")
                errors.append(f"Item {count.item_id}: {str(e)}")
                continue

        # 2) Zero out uncounted items: one ADJUSTMENT per item to bring stock to 0
        items_zeroed = 0
        for item_id, current_stock in uncounted_with_stock:
            try:
                if current_stock <= 0:
                    continue
                unit_cost = CanonicalPricingService.get_best_available_cost(db, item_id, branch_id, branch.company_id)
                total_cost = abs(Decimal(str(current_stock))) * unit_cost
                qty_delta = -Decimal(str(current_stock))
                ledger_entry = InventoryLedger(
                    company_id=branch.company_id,
                    branch_id=branch_id,
                    item_id=item_id,
                    transaction_type='ADJUSTMENT',
                    reference_type='STOCK_TAKE',
                    reference_id=session.id,
                    quantity_delta=qty_delta,
                    unit_cost=unit_cost,
                    total_cost=total_cost,
                    created_by=completing_user_id,
                    notes='Stock take: uncounted item zeroed out'
                )
                db.add(ledger_entry)
                SnapshotService.upsert_inventory_balance(db, branch.company_id, branch_id, item_id, qty_delta)
                SnapshotRefreshService.schedule_snapshot_refresh(db, branch.company_id, branch_id, item_id=item_id)
                items_zeroed += 1
            except Exception as e:
                logger.error(f"Error zeroing item {item_id}: {str(e)}")
                errors.append(f"Item {item_id} (zero out): {str(e)}")

        # Mark session as completed
        session.status = 'COMPLETED'
        session.completed_at = datetime.utcnow()
        db.commit()

        logger.info(
            f"Stock take session {session.id} completed for branch {branch_id}. "
            f"Items updated from counts: {items_updated}, items zeroed (uncounted): {items_zeroed}"
        )

        result = {
            "success": True,
            "message": "Stock take completed and inventory updated",
            "session_id": str(session.id),
            "items_updated": items_updated,
            "items_zeroed": items_zeroed,
            "total_counts": len(counts)
        }
        if errors:
            result["warnings"] = errors
            result["message"] = f"Stock take completed with {len(errors)} warnings"
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing stock take for branch {branch_id}: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete stock take: {str(e)}"
        )


@router.post("/branch/{branch_id}/cancel")
def cancel_branch_stock_take(
    branch_id: UUID,
    user_id: UUID = Query(None, description="User ID cancelling the stock take (optional)"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Cancel stock take for branch
    
    Discards all counts and returns branch to normal mode.
    Only admin can cancel.
    """
    try:
        # Get active session
        session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active stock take session found for this branch"
            )
        
        # Verify user is admin (session creator or has admin role)
        if user_id:
            user_role = get_user_role(user_id, branch_id, db)
            if not user_role or not (user_role == 'admin' or user_id == session.created_by):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only administrators can cancel stock take sessions"
                )
        
        # Delete all counts for this session
        count_deleted = db.query(StockTakeCount).filter(
            StockTakeCount.session_id == session.id
        ).delete()
        
        # Delete all locks
        db.query(StockTakeCounterLock).filter(
            StockTakeCounterLock.session_id == session.id
        ).delete()
        
        # Mark session as cancelled
        session.status = 'CANCELLED'
        session.completed_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"Stock take session {session.id} cancelled for branch {branch_id}. {count_deleted} counts discarded.")
        
        return {
            "success": True,
            "message": "Stock take cancelled and all counts discarded",
            "counts_deleted": count_deleted
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling stock take for branch {branch_id}: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel stock take: {str(e)}"
        )


@router.get("/branch/{branch_id}/variance-report")
def get_stock_take_variance_report(
    branch_id: UUID,
    session_id: UUID = Query(..., description="Completed stock take session ID"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Variance report for a completed stock take: counted items (system vs counted vs variance)
    and uncounted items that were zeroed out. Use for follow-up and auditing.
    """
    session = db.query(StockTakeSession).filter(
        and_(
            StockTakeSession.id == session_id,
            StockTakeSession.branch_id == branch_id,
            StockTakeSession.status == 'COMPLETED'
        )
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed stock take session not found for this branch"
        )

    # Counted items: from stock_take_counts (aggregate by item: use latest or sum by item)
    counts_by_item = {}
    for c in db.query(StockTakeCount).filter(StockTakeCount.session_id == session_id).order_by(desc(StockTakeCount.counted_at)):
        # Keep latest count per item (or sum counted_quantity if multiple shelves)
        if c.item_id not in counts_by_item:
            counts_by_item[c.item_id] = {
                "system_quantity": c.system_quantity,
                "counted_quantity": c.counted_quantity,
                "variance": c.variance,
            }
        else:
            counts_by_item[c.item_id]["counted_quantity"] += c.counted_quantity
            counts_by_item[c.item_id]["variance"] = counts_by_item[c.item_id]["counted_quantity"] - counts_by_item[c.item_id]["system_quantity"]

    counted_item_ids = set(counts_by_item.keys())

    # Zeroed items: ledger entries for this session with negative delta and item not in counts
    zeroed = db.query(InventoryLedger).filter(
        and_(
            InventoryLedger.reference_type == 'STOCK_TAKE',
            InventoryLedger.reference_id == session_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.quantity_delta < 0
        )
    ).all()
    zeroed_by_item = {}
    for row in zeroed:
        if row.item_id in counted_item_ids:
            continue
        if row.item_id not in zeroed_by_item:
            zeroed_by_item[row.item_id] = 0
        zeroed_by_item[row.item_id] += abs(float(row.quantity_delta))

    rows = []
    for item_id, data in counts_by_item.items():
        item = db.query(Item).filter(Item.id == item_id).first()
        rows.append({
            "item_id": str(item_id),
            "item_name": item.name if item else None,
            "system_quantity": data["system_quantity"],
            "counted_quantity": data["counted_quantity"],
            "variance": data["variance"],
            "zeroed_out": False,
        })
    for item_id, prev_qty in zeroed_by_item.items():
        item = db.query(Item).filter(Item.id == item_id).first()
        rows.append({
            "item_id": str(item_id),
            "item_name": item.name if item else None,
            "system_quantity": int(prev_qty),
            "counted_quantity": 0,
            "variance": -int(prev_qty),
            "zeroed_out": True,
        })

    return {
        "session_id": str(session_id),
        "branch_id": str(branch_id),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "rows": sorted(rows, key=lambda r: (r["zeroed_out"], (r["item_name"] or "").lower())),
    }


@router.get("/counts/{count_id}")
def get_count(
    count_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get a single count by ID"""
    count = db.query(StockTakeCount).filter(StockTakeCount.id == count_id).first()
    if not count:
        raise HTTPException(status_code=404, detail="Count not found")
    
    # Check if session is completed (read-only)
    session = db.query(StockTakeSession).filter(StockTakeSession.id == count.session_id).first()
    is_completed = session and session.status == 'COMPLETED'
    
    item = db.query(Item).filter(Item.id == count.item_id).first()
    counter = db.query(User).filter(User.id == count.counted_by).first()
    
    return {
        "id": str(count.id),
        "session_id": str(count.session_id),
        "item_id": str(count.item_id),
        "counted_by": str(count.counted_by),
        "shelf_location": count.shelf_location,
        "batch_number": count.batch_number,
        "expiry_date": count.expiry_date.isoformat() if count.expiry_date else None,
        "unit_name": count.unit_name,
        "quantity_in_unit": float(count.quantity_in_unit) if count.quantity_in_unit else None,
        "counted_quantity": count.counted_quantity,
        "system_quantity": count.system_quantity,
        "variance": count.variance,
        "notes": count.notes,
        "counted_at": count.counted_at.isoformat() if count.counted_at else None,
        "created_at": count.created_at.isoformat() if count.created_at else None,
        "item_name": item.name if item else None,
        "counter_name": counter.full_name if counter else None,
        "is_completed": is_completed,
        "can_edit": not is_completed  # Can only edit if session not completed
    }


@router.put("/counts/{count_id}")
def update_count(
    count_id: UUID,
    count_data: dict,
    user_id: UUID = Query(..., description="User ID updating the count"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Update an existing count (only before session completion)"""
    try:
        count = db.query(StockTakeCount).filter(StockTakeCount.id == count_id).first()
        if not count:
            raise HTTPException(status_code=404, detail="Count not found")
        
        # Verify user owns this count
        if str(count.counted_by) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own counts"
            )
        
        # Check if session is completed (cannot edit after completion)
        session = db.query(StockTakeSession).filter(StockTakeSession.id == count.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if session.status == 'COMPLETED':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit counts after stock take is completed. Only admin can revert."
            )
        
        # Get item for validation
        item = db.query(Item).filter(Item.id == count.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        # Update fields
        shelf_location = count_data.get('shelf_location')
        batch_number = count_data.get('batch_number')
        expiry_date = count_data.get('expiry_date')
        unit_name = count_data.get('unit_name')
        quantity_in_unit = count_data.get('quantity_in_unit')
        notes = count_data.get('notes')
        
        # Validate shelf location
        if shelf_location:
            if not shelf_location.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Shelf location cannot be empty"
                )
            count.shelf_location = shelf_location.strip()
        
        # Validate batch/expiry if required
        if item.is_controlled and batch_number is not None:
            if not batch_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Batch number is required for this item"
                )
            count.batch_number = batch_number
        
        if item.track_expiry and expiry_date is not None:
            if not expiry_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Expiry date is required for this item"
                )
            # Parse expiry date
            from datetime import datetime as dt
            if isinstance(expiry_date, str):
                count.expiry_date = dt.strptime(expiry_date, '%Y-%m-%d').date()
            else:
                count.expiry_date = expiry_date
        
        # Update quantity if unit_name and quantity_in_unit provided
        if unit_name and quantity_in_unit is not None:
            try:
                from app.services.inventory_service import InventoryService
                counted_quantity = InventoryService.convert_to_base_units(
                    db, count.item_id, float(quantity_in_unit), unit_name
                )
                count.unit_name = unit_name
                count.quantity_in_unit = quantity_in_unit
                count.counted_quantity = counted_quantity
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid unit '{unit_name}': {str(e)}"
                )
        elif 'counted_quantity' in count_data:
            # Direct quantity update (assumed base units)
            count.counted_quantity = int(count_data['counted_quantity'])
        
        # Update system quantity (recalculate)
        count.system_quantity = InventoryService.get_current_stock(
            db, count.item_id, session.branch_id
        )
        
        # Recalculate variance
        count.variance = count.counted_quantity - count.system_quantity
        
        # Update notes
        if notes is not None:
            count.notes = notes
        
        count.counted_at = datetime.utcnow()
        db.commit()
        db.refresh(count)
        
        logger.info(f"Count {count_id} updated by user {user_id}")
        
        return {
            "success": True,
            "id": str(count.id),
            "message": "Count updated successfully",
            "counted_quantity": count.counted_quantity,
            "system_quantity": count.system_quantity,
            "variance": count.variance
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating count {count_id}: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update count: {str(e)}"
        )


@router.delete("/counts/{count_id}")
def delete_count(
    count_id: UUID,
    user_id: UUID = Query(..., description="User ID deleting the count"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Delete a count (only before session completion)"""
    try:
        count = db.query(StockTakeCount).filter(StockTakeCount.id == count_id).first()
        if not count:
            raise HTTPException(status_code=404, detail="Count not found")
        
        # Verify user owns this count
        if str(count.counted_by) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own counts"
            )
        
        # Check if session is completed (cannot delete after completion)
        session = db.query(StockTakeSession).filter(StockTakeSession.id == count.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if session.status == 'COMPLETED':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete counts after stock take is completed. Only admin can revert."
            )
        
        db.delete(count)
        db.commit()
        
        logger.info(f"Count {count_id} deleted by user {user_id}")
        
        return {
            "success": True,
            "message": "Count deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting count {count_id}: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete count: {str(e)}"
        )


# ============================================
# Shelf Management Endpoints
# ============================================

@router.get("/branch/{branch_id}/shelves")
def get_shelves(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get all shelves with counts for a branch's active stock take"""
    try:
        # Get active session
        session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if not session:
            return []
        
        # Get unique shelves with their counts
        shelves_query = db.query(
            StockTakeCount.shelf_location,
            func.count(func.distinct(StockTakeCount.item_id)).label('item_count'),
            func.max(StockTakeCount.verification_status).label('verification_status'),
            func.max(StockTakeCount.counted_by).label('counted_by'),
            func.max(StockTakeCount.verified_by).label('verified_by'),
            func.max(StockTakeCount.verified_at).label('verified_at'),
            func.max(StockTakeCount.rejection_reason).label('rejection_reason')
        ).filter(
            StockTakeCount.session_id == session.id
        ).group_by(
            StockTakeCount.shelf_location
        ).all()
        
        result = []
        for shelf_data in shelves_query:
            # Get counter name
            counter = db.query(User).filter(User.id == shelf_data.counted_by).first() if shelf_data.counted_by else None
            verifier = db.query(User).filter(User.id == shelf_data.verified_by).first() if shelf_data.verified_by else None
            
            result.append({
                "name": shelf_data.shelf_location,
                "item_count": shelf_data.item_count or 0,
                "verification_status": shelf_data.verification_status or 'PENDING',
                "counter_name": counter.full_name if counter else None,
                "verified_by_name": verifier.full_name if verifier else None,
                "verified_at": shelf_data.verified_at.isoformat() if shelf_data.verified_at else None,
                "rejection_reason": shelf_data.rejection_reason
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting shelves for branch {branch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get shelves: {str(e)}"
        )


@router.get("/branch/{branch_id}/shelves/{shelf_name}/counts")
def get_shelf_counts(
    branch_id: UUID,
    shelf_name: str,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get all counts for a specific shelf"""
    try:
        # Get active session
        session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="No active stock take session")
        
        # Get counts for this shelf
        counts = db.query(StockTakeCount).filter(
            and_(
                StockTakeCount.session_id == session.id,
                StockTakeCount.shelf_location == shelf_name
            )
        ).order_by(StockTakeCount.counted_at).all()
        
        result = []
        for count in counts:
            item = db.query(Item).filter(Item.id == count.item_id).first()
            
            result.append({
                "id": str(count.id),
                "item_id": str(count.item_id),
                "item_name": item.name if item else None,
                "shelf_location": count.shelf_location,
                "batch_number": count.batch_number,
                "expiry_date": count.expiry_date.isoformat() if count.expiry_date else None,
                "unit_name": count.unit_name,
                "quantity_in_unit": float(count.quantity_in_unit) if count.quantity_in_unit else None,
                "counted_quantity": count.counted_quantity,
                "system_quantity": count.system_quantity,
                "variance": count.variance,
                "notes": count.notes,
                "verification_status": count.verification_status or 'PENDING'
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting counts for shelf {shelf_name}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get shelf counts: {str(e)}"
        )


@router.post("/branch/{branch_id}/shelves/{shelf_name}/approve")
def approve_shelf(
    branch_id: UUID,
    shelf_name: str,
    user_id: UUID = Query(..., description="User ID approving the shelf"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Approve all counts for a shelf"""
    try:
        # Get active session
        session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="No active stock take session")
        
        # Get all counts for this shelf
        counts = db.query(StockTakeCount).filter(
            and_(
                StockTakeCount.session_id == session.id,
                StockTakeCount.shelf_location == shelf_name
            )
        ).all()
        
        if not counts:
            raise HTTPException(status_code=404, detail=f"No counts found for shelf '{shelf_name}'")
        
        # Update all counts to APPROVED
        approved_count = 0
        for count in counts:
            count.verification_status = 'APPROVED'
            count.verified_by = user_id
            count.verified_at = datetime.utcnow()
            count.rejection_reason = None
            approved_count += 1
        
        db.commit()
        
        logger.info(f"Shelf '{shelf_name}' approved by user {user_id}. {approved_count} counts approved.")
        
        return {
            "success": True,
            "message": f"Shelf '{shelf_name}' approved successfully",
            "counts_approved": approved_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving shelf {shelf_name}: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve shelf: {str(e)}"
        )


@router.post("/branch/{branch_id}/shelves/{shelf_name}/reject")
def reject_shelf(
    branch_id: UUID,
    shelf_name: str,
    rejection_data: dict,
    user_id: UUID = Query(..., description="User ID rejecting the shelf"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Reject all counts for a shelf (return to counter)"""
    try:
        # Get active session
        session = db.query(StockTakeSession).filter(
            and_(
                StockTakeSession.branch_id == branch_id,
                StockTakeSession.status == 'ACTIVE'
            )
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="No active stock take session")
        
        # Get all counts for this shelf
        counts = db.query(StockTakeCount).filter(
            and_(
                StockTakeCount.session_id == session.id,
                StockTakeCount.shelf_location == shelf_name
            )
        ).all()
        
        if not counts:
            raise HTTPException(status_code=404, detail=f"No counts found for shelf '{shelf_name}'")
        
        rejection_reason = rejection_data.get('reason', '').strip() if rejection_data else ''
        
        # Update all counts to REJECTED
        rejected_count = 0
        for count in counts:
            count.verification_status = 'REJECTED'
            count.verified_by = user_id
            count.verified_at = datetime.utcnow()
            count.rejection_reason = rejection_reason
            rejected_count += 1
        
        db.commit()
        
        logger.info(f"Shelf '{shelf_name}' rejected by user {user_id}. {rejected_count} counts rejected. Reason: {rejection_reason}")
        
        return {
            "success": True,
            "message": f"Shelf '{shelf_name}' rejected and returned to counter",
            "counts_rejected": rejected_count,
            "rejection_reason": rejection_reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting shelf {shelf_name}: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject shelf: {str(e)}"
        )

