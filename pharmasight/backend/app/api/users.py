"""
User Management API

Handles user creation, listing, updating, activating/deactivating, and deletion.
Admin-only endpoints for managing organization users.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List
from uuid import UUID
import secrets
import hashlib
from datetime import datetime
from app.database import get_db
from app.models.user import User, UserRole, UserBranchRole
from app.models.company import Branch
from app.schemas.user import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
    UserRoleResponse, UserActivateRequest, UserRoleUpdate,
    InvitationResponse
)

router = APIRouter()


def generate_invitation_code() -> str:
    """Generate a simple 6-digit invitation code"""
    return ''.join(secrets.choice('0123456789') for _ in range(6))


def generate_invitation_token() -> str:
    """Generate a secure invitation token"""
    token = secrets.token_urlsafe(32)
    return token


def get_role_by_name(role_name: str, db: Session) -> UserRole:
    """Get role by name, create if it doesn't exist"""
    role = db.query(UserRole).filter(UserRole.role_name == role_name.lower()).first()
    if not role:
        # Role doesn't exist, create it
        role = UserRole(role_name=role_name.lower(), description=f"{role_name} role")
        db.add(role)
        db.flush()
    return role


@router.get("/users/roles", response_model=List[UserRoleResponse])
def list_roles(db: Session = Depends(get_db)):
    """
    List all available roles
    
    Returns list of system roles (Admin, Pharmacist, Cashier, etc.)
    """
    roles = db.query(UserRole).order_by(UserRole.role_name).all()
    return roles


@router.get("/users", response_model=UserListResponse)
def list_users(
    include_deleted: bool = Query(False, description="Include soft-deleted users"),
    db: Session = Depends(get_db)
):
    """
    List all users in the organization
    
    Returns list of users with their roles and branch assignments.
    Only active users are returned by default (unless include_deleted=True).
    """
    query = db.query(User)
    
    # Filter out soft-deleted users unless include_deleted is True
    if not include_deleted:
        query = query.filter(User.deleted_at.is_(None))
    
    users = query.order_by(User.created_at.desc()).all()
    
    # Populate branch roles for each user
    user_responses = []
    for user in users:
        # Get branch roles with role and branch details
        branch_roles_query = db.query(
            UserBranchRole,
            UserRole.role_name,
            Branch.name.label('branch_name')
        ).join(
            UserRole, UserBranchRole.role_id == UserRole.id
        ).join(
            Branch, UserBranchRole.branch_id == Branch.id
        ).filter(
            UserBranchRole.user_id == user.id
        ).all()
        
        branch_roles = []
        for ubr, role_name, branch_name in branch_roles_query:
            from app.schemas.user import UserBranchRoleResponse
            branch_roles.append(UserBranchRoleResponse(
                id=ubr.id,
                user_id=ubr.user_id,
                branch_id=ubr.branch_id,
                role_id=ubr.role_id,
                role_name=role_name,
                branch_name=branch_name,
                created_at=ubr.created_at
            ))
        
        user_responses.append(UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            is_active=user.is_active,
            is_pending=user.is_pending if user.is_pending else False,
            password_set=user.password_set if user.password_set else False,
            invitation_code=user.invitation_code if user.is_pending else None,
            branch_roles=branch_roles,
            created_at=user.created_at,
            updated_at=user.updated_at
        ))
    
    return UserListResponse(users=user_responses, total=len(user_responses))


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    """Get user by ID with role information"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get branch roles with details
    branch_roles_query = db.query(
        UserBranchRole,
        UserRole.role_name,
        Branch.name.label('branch_name')
    ).join(
        UserRole, UserBranchRole.role_id == UserRole.id
    ).join(
        Branch, UserBranchRole.branch_id == Branch.id
    ).filter(
        UserBranchRole.user_id == user.id
    ).all()
    
    branch_roles = []
    for ubr, role_name, branch_name in branch_roles_query:
        from app.schemas.user import UserBranchRoleResponse
        branch_roles.append(UserBranchRoleResponse(
            id=ubr.id,
            user_id=ubr.user_id,
            branch_id=ubr.branch_id,
            role_id=ubr.role_id,
            role_name=role_name,
            branch_name=branch_name,
            created_at=ubr.created_at
        ))
    
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        is_active=user.is_active,
        is_pending=user.is_pending if user.is_pending else False,
        password_set=user.password_set if user.password_set else False,
        invitation_code=user.invitation_code if user.is_pending else None,
        branch_roles=branch_roles,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


@router.post("/users", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Create a new user (Admin-only)
    
    Creates a user in the database with:
    - Email (required)
    - Role (required) - will be assigned to branch if branch_id provided
    - Branch (optional)
    
    User is created as inactive/pending with invitation code.
    Returns invitation token and code for user setup.
    """
    # Check if user with email already exists
    existing_user = db.query(User).filter(
        and_(User.email == user_data.email, User.deleted_at.is_(None))
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email {user_data.email} already exists"
        )
    
    # Generate unique invitation token and code
    invitation_token = generate_invitation_token()
    invitation_code = generate_invitation_code()
    
    # Ensure invitation code is unique
    while db.query(User).filter(User.invitation_code == invitation_code).first():
        invitation_code = generate_invitation_code()
    
    # Ensure invitation token is unique
    while db.query(User).filter(User.invitation_token == invitation_token).first():
        invitation_token = generate_invitation_token()
    
    # Create user (without Supabase Auth user_id for now - will be set on first login)
    # For invited users, we'll create a temporary UUID, then update it when they set password
    import uuid
    temp_user_id = uuid.uuid4()
    
    new_user = User(
        id=temp_user_id,  # Temporary ID - will be updated when user sets password via Supabase Auth
        email=user_data.email,
        full_name=user_data.full_name,
        phone=user_data.phone,
        is_active=False,  # Inactive until password is set
        is_pending=True,  # Pending password setup
        password_set=False,
        invitation_token=invitation_token,
        invitation_code=invitation_code
    )
    
    db.add(new_user)
    db.flush()  # Get the ID
    
    # Get or create role
    role = get_role_by_name(user_data.role_name, db)
    
    # Assign role to branch if branch_id provided
    if user_data.branch_id:
        # Verify branch exists
        branch = db.query(Branch).filter(Branch.id == user_data.branch_id).first()
        if not branch:
            db.rollback()
            raise HTTPException(status_code=404, detail="Branch not found")
        
        # Create user-branch-role assignment
        user_branch_role = UserBranchRole(
            user_id=new_user.id,
            branch_id=user_data.branch_id,
            role_id=role.id
        )
        db.add(user_branch_role)
    
    db.commit()
    db.refresh(new_user)
    
    # Build invitation link (frontend URL with token)
    invitation_link = f"/invite?token={invitation_token}"
    
    return InvitationResponse(
        user_id=new_user.id,
        email=new_user.email,
        invitation_token=invitation_token,
        invitation_code=invitation_code,
        invitation_link=invitation_link,
        message=f"User created successfully. Invitation code: {invitation_code}"
    )


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, user_update: UserUpdate, db: Session = Depends(get_db)):
    """Update user details (full_name, phone, is_active)"""
    user = db.query(User).filter(
        and_(User.id == user_id, User.deleted_at.is_(None))
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update fields
    update_data = user_update.model_dump(exclude_unset=True) if hasattr(user_update, 'model_dump') else user_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    
    # Return updated user with roles
    return get_user(user_id, db)


@router.patch("/users/{user_id}/activate", response_model=UserResponse)
def activate_user(user_id: UUID, activate_data: UserActivateRequest, db: Session = Depends(get_db)):
    """Activate or deactivate a user"""
    user = db.query(User).filter(
        and_(User.id == user_id, User.deleted_at.is_(None))
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_active = activate_data.is_active
    db.commit()
    db.refresh(user)
    
    return get_user(user_id, db)


@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
def delete_user(user_id: UUID, db: Session = Depends(get_db)):
    """
    Soft delete a user
    
    Sets deleted_at timestamp instead of actually deleting the record.
    User is marked as inactive and excluded from normal queries.
    """
    user = db.query(User).filter(
        and_(User.id == user_id, User.deleted_at.is_(None))
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Soft delete
    user.deleted_at = datetime.utcnow()
    user.is_active = False  # Also deactivate
    
    db.commit()
    
    return {"success": True, "message": "User deleted successfully"}


@router.post("/users/{user_id}/roles", response_model=UserResponse)
def assign_role(
    user_id: UUID,
    role_data: UserRoleUpdate,
    db: Session = Depends(get_db)
):
    """
    Assign or update user role for a branch
    
    If branch_id is provided, assigns role to that specific branch.
    If branch_id is None, assigns role to all branches (or primary branch logic).
    """
    user = db.query(User).filter(
        and_(User.id == user_id, User.deleted_at.is_(None))
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get role
    role = get_role_by_name(role_data.role_name, db)
    
    if role_data.branch_id:
        # Assign to specific branch
        branch = db.query(Branch).filter(Branch.id == role_data.branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        # Check if assignment already exists
        existing = db.query(UserBranchRole).filter(
            and_(
                UserBranchRole.user_id == user_id,
                UserBranchRole.branch_id == role_data.branch_id,
                UserBranchRole.role_id == role.id
            )
        ).first()
        
        if not existing:
            # Create new assignment
            user_branch_role = UserBranchRole(
                user_id=user_id,
                branch_id=role_data.branch_id,
                role_id=role.id
            )
            db.add(user_branch_role)
            db.commit()
    else:
        # For now, require branch_id. In future, could assign to all branches
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="branch_id is required for role assignment"
        )
    
    return get_user(user_id, db)
