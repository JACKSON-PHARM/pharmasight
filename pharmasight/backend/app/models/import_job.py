"""
Import Job model for tracking Excel import progress
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base
import uuid


class ImportJob(Base):
    """Tracks Excel import jobs with progress"""
    __tablename__ = "import_jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # File tracking
    file_hash = Column(String(64), nullable=False, index=True)
    file_name = Column(String(255), nullable=True)
    
    # Status tracking
    status = Column(String(20), nullable=False, default="pending", index=True)
    # Status values: 'pending', 'processing', 'completed', 'failed', 'cancelled'
    
    # Progress tracking
    total_rows = Column(Integer, nullable=False, default=0)
    processed_rows = Column(Integer, nullable=False, default=0)
    last_batch = Column(Integer, nullable=False, default=0)
    
    # Results
    stats = Column(JSON, nullable=True)  # Store import statistics
    error_message = Column(String(1000), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    def to_dict(self):
        """Convert to dictionary for API response"""
        progress_pct = (self.processed_rows / self.total_rows * 100) if self.total_rows > 0 else 0
        
        return {
            "id": str(self.id),
            "company_id": str(self.company_id),
            "branch_id": str(self.branch_id) if self.branch_id else None,
            "user_id": str(self.user_id),
            "file_hash": self.file_hash,
            "file_name": self.file_name,
            "status": self.status,
            "total_rows": self.total_rows,
            "processed_rows": self.processed_rows,
            "last_batch": self.last_batch,
            "progress_percent": round(progress_pct, 1),
            "stats": self.stats,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
