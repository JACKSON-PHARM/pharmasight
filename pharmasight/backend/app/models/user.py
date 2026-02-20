"""
User and UserRole models
"""
from sqlalchemy import Column, String, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class User(Base):
    """
    User model
    
    All users belong to the single company in this database.
    No company_id needed - there is only one company.
    User ID must match Supabase Auth user_id.
    
    NEW FIELDS (for invitation system):
    - invitation_token: Unique token for invitation link
    - invitation_code: Simple code for invitation (alternative to link)
    - is_pending: Whether user is pending password setup
    - password_set: Whether user has set their password
    - deleted_at: Soft delete timestamp (NULL = active, timestamp = deleted)
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True)  # Must match Supabase Auth user_id
    email = Column(String(255), nullable=False, unique=True)
    username = Column(String(100), unique=True, nullable=True)  # Unique username for login
    full_name = Column(String(255))
    phone = Column(String(50))
    is_active = Column(Boolean, default=True)
    
    # NEW: Invitation fields
    invitation_token = Column(String(255), unique=True, nullable=True)
    invitation_code = Column(String(50), unique=True, nullable=True)
    is_pending = Column(Boolean, default=False)  # True for newly invited users
    password_set = Column(Boolean, default=False)  # Set to True after first login with password
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)  # Soft delete timestamp

    # Internal auth (dual-auth with Supabase): when set, user can login with internal JWT
    password_hash = Column(String(255), nullable=True)
    password_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    branch_roles = relationship("UserBranchRole", back_populates="user", cascade="all, delete-orphan")


class UserRole(Base):
    """System role definitions"""
    __tablename__ = "user_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_name = Column(String(50), nullable=False, unique=True)
    description = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    user_branch_roles = relationship("UserBranchRole", back_populates="role")
    role_permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")


class UserBranchRole(Base):
    """
    User-Branch-Role mapping
    
    THIS IS THE ONLY WAY USERS ACCESS BRANCHES.
    No company-level roles exist.
    Users can only access branches they are explicitly assigned to.
    """
    __tablename__ = "user_branch_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("user_roles.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="branch_roles")
    branch = relationship("Branch")
    role = relationship("UserRole", back_populates="user_branch_roles")

    __table_args__ = (
        {"comment": "ONLY way users access branches. No company-level roles. Users can only access branches they are assigned to."},
    )

