"""
Pydantic schemas for Stock Take API
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from uuid import UUID
from datetime import datetime


# ============================================
# Stock Take Session Schemas
# ============================================

class StockTakeSessionCreate(BaseModel):
    """Schema for creating a new stock take session"""
    branch_id: UUID
    allowed_counters: List[UUID] = Field(default_factory=list, description="List of user IDs allowed to count")
    assigned_shelves: Dict[str, List[str]] = Field(default_factory=dict, description="Map of user_id -> shelf_locations")
    is_multi_user: bool = Field(default=True, description="Whether this is a multi-user session")
    notes: Optional[str] = None


class StockTakeSessionUpdate(BaseModel):
    """Schema for updating a stock take session"""
    status: Optional[str] = None  # DRAFT, ACTIVE, PAUSED, COMPLETED, CANCELLED
    allowed_counters: Optional[List[UUID]] = None
    assigned_shelves: Optional[Dict[str, List[str]]] = None
    notes: Optional[str] = None


class StockTakeSessionResponse(BaseModel):
    """Schema for stock take session response"""
    id: UUID
    company_id: UUID
    branch_id: UUID
    session_code: str
    status: str
    created_by: UUID
    allowed_counters: List[UUID]
    assigned_shelves: Dict[str, List[str]]
    is_multi_user: bool
    notes: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    # Computed fields (will be populated by API)
    creator_name: Optional[str] = None
    counter_count: int = 0
    total_items_counted: int = 0
    total_items_assigned: int = 0

    class Config:
        from_attributes = True


# ============================================
# Stock Take Count Schemas
# ============================================

class StockTakeCountCreate(BaseModel):
    """Schema for creating a stock take count"""
    session_id: UUID
    item_id: UUID
    counted_quantity: int = Field(..., description="Counted quantity in base units")
    shelf_location: Optional[str] = None
    notes: Optional[str] = None


class StockTakeCountBranchCreate(BaseModel):
    """Schema for creating a stock take count (branch-based, automatic participation)"""
    branch_id: UUID
    item_id: UUID
    counted_quantity: int = Field(..., description="Counted quantity in base units")
    shelf_location: Optional[str] = None
    notes: Optional[str] = None
    item_updates: Optional[dict] = None  # For pack_size, breaking_bulk_unit updates


class StockTakeCountResponse(BaseModel):
    """Schema for stock take count response"""
    id: UUID
    session_id: UUID
    item_id: UUID
    counted_by: UUID
    shelf_location: Optional[str]
    counted_quantity: int
    system_quantity: int
    variance: int
    notes: Optional[str]
    counted_at: datetime
    created_at: datetime
    
    # Computed fields
    item_name: Optional[str] = None
    counter_name: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================
# Stock Take Lock Schemas
# ============================================

class StockTakeLockResponse(BaseModel):
    """Schema for stock take lock response"""
    id: UUID
    session_id: UUID
    item_id: UUID
    counter_id: UUID
    locked_at: datetime
    expires_at: datetime
    
    # Computed fields
    counter_name: Optional[str] = None
    item_name: Optional[str] = None
    is_expired: bool = False

    class Config:
        from_attributes = True


class StockTakeLockRequest(BaseModel):
    """Schema for requesting a lock on an item"""
    session_id: UUID
    item_id: UUID


# ============================================
# Stock Take Progress Schemas
# ============================================

class CounterProgress(BaseModel):
    """Progress information for a single counter"""
    counter_id: UUID
    counter_name: str
    assigned_shelves: List[str]
    items_counted: int
    items_assigned: int
    progress_percent: float


class StockTakeProgressResponse(BaseModel):
    """Overall progress for a stock take session"""
    session_id: UUID
    session_code: str
    status: str
    total_items: int
    total_counted: int
    total_locked: int
    progress_percent: float
    counters: List[CounterProgress]
    recent_counts: List[StockTakeCountResponse]


# ============================================
# Stock Take Adjustment Schemas
# ============================================

class StockTakeAdjustmentCreate(BaseModel):
    """Schema for creating a stock take adjustment"""
    session_id: UUID
    item_id: UUID
    adjustment_quantity: int = Field(..., description="Adjustment quantity (can be positive or negative, base units)")
    reason: Optional[str] = None


class StockTakeAdjustmentResponse(BaseModel):
    """Schema for stock take adjustment response"""
    id: UUID
    session_id: UUID
    item_id: UUID
    adjustment_quantity: int
    reason: Optional[str]
    approved_by: Optional[UUID]
    created_at: datetime
    
    # Computed fields
    item_name: Optional[str] = None
    approver_name: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================
# Session Join Schemas
# ============================================

class SessionJoinRequest(BaseModel):
    """Schema for joining a session with a code"""
    session_code: str


class SessionJoinResponse(BaseModel):
    """Response when joining a session"""
    success: bool
    session: Optional[StockTakeSessionResponse] = None
    message: str
