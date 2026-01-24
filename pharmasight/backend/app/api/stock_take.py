"""
Stock Take API routes for multi-user stock take sessions
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from app.database import get_db
from app.models import (
    StockTakeSession, StockTakeCount, StockTakeCounterLock, StockTakeAdjustment,
    User, Item, Branch, Company, UserRole, UserBranchRole, InventoryLedger
)
from app.schemas.stock_take import (
    StockTakeSessionCreate, StockTakeSessionUpdate, StockTakeSessionResponse,
    StockTakeCountCreate, StockTakeCountResponse,
    StockTakeLockResponse, StockTakeLockRequest,
    StockTakeProgressResponse, CounterProgress,
    StockTakeAdjustmentCreate, StockTakeAdjustmentResponse,
    SessionJoinRequest, SessionJoinResponse
)
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================
# Helper Functions
# ============================================

def generate_session_code(db: Session) -> str:
    """Generate a unique session code (e.g., ST-MAR25A)"""
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
# Session Management Endpoints
# ============================================

@router.post("/sessions", response_model=StockTakeSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    session_data: StockTakeSessionCreate,
    created_by: UUID = Query(..., description="User ID creating the session"),
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
def get_session(session_id: UUID, db: Session = Depends(get_db)):
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
def get_session_by_code(session_code: str, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
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
    
    return get_session(session_id, db)


@router.post("/sessions/{session_id}/start", response_model=StockTakeSessionResponse)
def start_session(
    session_id: UUID,
    user_id: UUID = Query(..., description="User ID starting the session"),
    db: Session = Depends(get_db)
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
    
    return get_session(session_id, db)


# ============================================
# Count Management Endpoints
# ============================================

@router.post("/counts", response_model=StockTakeCountResponse, status_code=status.HTTP_201_CREATED)
def create_count(
    count_data: StockTakeCountCreate,
    counted_by: UUID = Query(..., description="User ID making the count"),
    db: Session = Depends(get_db)
):
    """
    Create a stock take count
    
    Only allowed counters can count items in active sessions.
    """
    # Get session
    session = db.query(StockTakeSession).filter(
        StockTakeSession.id == count_data.session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check session is active
    if session.status != 'ACTIVE':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is not active (current: {session.status})"
        )
    
    # Check authorization
    if not authorize_stock_take_access(counted_by, count_data.session_id, 'count', db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to count items in this session"
        )
    
    # Get system quantity
    system_quantity = InventoryService.get_current_stock(
        db, count_data.item_id, session.branch_id
    )
    
    # Calculate variance
    variance = count_data.counted_quantity - system_quantity
    
    # Create count (upsert - allow updating existing count)
    existing = db.query(StockTakeCount).filter(
        and_(
            StockTakeCount.session_id == count_data.session_id,
            StockTakeCount.item_id == count_data.item_id,
            StockTakeCount.counted_by == counted_by
        )
    ).first()
    
    if existing:
        existing.counted_quantity = count_data.counted_quantity
        existing.system_quantity = system_quantity
        existing.variance = variance
        existing.shelf_location = count_data.shelf_location
        existing.notes = count_data.notes
        existing.counted_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        count = existing
    else:
        count = StockTakeCount(
            session_id=count_data.session_id,
            item_id=count_data.item_id,
            counted_by=counted_by,
            shelf_location=count_data.shelf_location,
            counted_quantity=count_data.counted_quantity,
            system_quantity=system_quantity,
            variance=variance,
            notes=count_data.notes
        )
        db.add(count)
        db.commit()
        db.refresh(count)
    
    # Get item and counter names
    item = db.query(Item).filter(Item.id == count_data.item_id).first()
    counter = db.query(User).filter(User.id == counted_by).first()
    
    return StockTakeCountResponse(
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
    )


@router.get("/sessions/{session_id}/counts", response_model=List[StockTakeCountResponse])
def list_counts(
    session_id: UUID,
    counter_id: Optional[UUID] = Query(None, description="Filter by counter"),
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
def list_locks(session_id: UUID, db: Session = Depends(get_db)):
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
def get_progress(session_id: UUID, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
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
