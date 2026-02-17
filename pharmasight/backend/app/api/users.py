"""
User Management API

Handles user creation, listing, updating, activating/deactivating, and deletion.
Admin-only endpoints for managing organization users.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional
from uuid import UUID
import secrets
import hashlib
from datetime import datetime
from app.dependencies import get_tenant_db
from app.models.user import User, UserRole, UserBranchRole
from app.models.company import Branch
from app.models.permission import Permission, RolePermission
from app.schemas.user import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
    UserRoleResponse, UserActivateRequest, UserRoleUpdate,
    InvitationResponse
)
from app.services.invite_service import InviteService
from app.utils.username_generator import generate_username_from_name
import logging

logger = logging.getLogger(__name__)

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
def list_roles(db: Session = Depends(get_tenant_db)):
    """
    List all available roles
    
    Returns list of system roles (Admin, Pharmacist, Cashier, etc.)
    """
    roles = db.query(UserRole).order_by(UserRole.role_name).all()
    return roles


# -----------------------------------------------------------------------------
# Permissions (Vyapar-style matrix)
# -----------------------------------------------------------------------------


try:
    from app.permission_config import HQ_ONLY_PERMISSIONS
except ImportError:
    HQ_ONLY_PERMISSIONS = frozenset()


@router.get("/permissions/hq-only")
def list_hq_only_permissions():
    """Return permission names that are restricted to HQ branch only."""
    return {"permissions": list(HQ_ONLY_PERMISSIONS)}


@router.get("/permissions")
def list_permissions(db: Session = Depends(get_tenant_db)):
    """
    List all permissions grouped by module for the permission matrix UI.
    Returns: [{ module, permissions: [{ id, name, action, description }] }]
    """
    perms = db.query(Permission).order_by(Permission.module, Permission.action).all()
    by_module: dict = {}
    for p in perms:
        if p.module not in by_module:
            by_module[p.module] = []
        by_module[p.module].append({
            "id": str(p.id),
            "name": p.name,
            "action": p.action,
            "description": p.description or "",
        })
    return [{"module": m, "permissions": arr} for m, arr in sorted(by_module.items())]


@router.get("/users/roles/{role_id}/permissions")
def get_role_permissions(role_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get permission names granted to a role (global, branch_id=null)."""
    role = db.query(UserRole).filter(UserRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    rps = (
        db.query(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role_id, RolePermission.branch_id.is_(None))
        .all()
    )
    return {"permissions": [r[0] for r in rps]}


class RolePermissionsUpdate(BaseModel):
    permissions: List[str]  # list of permission names e.g. ["sales.view", "sales.create"]


@router.put("/users/roles/{role_id}/permissions")
def update_role_permissions(
    role_id: UUID,
    payload: RolePermissionsUpdate,
    db: Session = Depends(get_tenant_db),
):
    """Replace role's permissions with the given list. branch_id=null (global)."""
    role = db.query(UserRole).filter(UserRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    # Delete existing global permissions for this role
    db.query(RolePermission).filter(
        RolePermission.role_id == role_id,
        RolePermission.branch_id.is_(None),
    ).delete()
    # Resolve permission names to IDs and insert
    for name in payload.permissions:
        perm = db.query(Permission).filter(Permission.name == name).first()
        if perm:
            rp = RolePermission(role_id=role_id, permission_id=perm.id, branch_id=None)
            db.add(rp)
    db.commit()
    return {"success": True, "permissions": payload.permissions}


class RoleUpdate(BaseModel):
    role_name: Optional[str] = None
    description: Optional[str] = None


@router.patch("/users/roles/{role_id}")
def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    db: Session = Depends(get_tenant_db),
):
    """Update role name and description."""
    role = db.query(UserRole).filter(UserRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if payload.role_name is not None:
        role.role_name = payload.role_name.strip()
    if payload.description is not None:
        role.description = payload.description
    db.commit()
    db.refresh(role)
    return {"id": str(role.id), "role_name": role.role_name, "description": role.description or ""}


@router.get("/users", response_model=UserListResponse)
def list_users(
    include_deleted: bool = Query(False, description="Include soft-deleted users"),
    db: Session = Depends(get_tenant_db)
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
            username=getattr(user, 'username', None),
            full_name=user.full_name,
            phone=user.phone,
            is_active=user.is_active,
            is_pending=user.is_pending if user.is_pending else False,
            password_set=user.password_set if user.password_set else False,
            invitation_code=user.invitation_code if user.is_pending else None,
            deleted_at=user.deleted_at,
            branch_roles=branch_roles,
            created_at=user.created_at,
            updated_at=user.updated_at
        ))
    
    return UserListResponse(users=user_responses, total=len(user_responses))


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: UUID, db: Session = Depends(get_tenant_db)):
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
        username=getattr(user, 'username', None),
        full_name=user.full_name,
        phone=user.phone,
        is_active=user.is_active,
        is_pending=user.is_pending if user.is_pending else False,
        password_set=user.password_set if user.password_set else False,
        invitation_code=user.invitation_code if user.is_pending else None,
        deleted_at=user.deleted_at,
        branch_roles=branch_roles,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


@router.get("/users/{user_id}/permissions")
def get_user_permissions(
    user_id: UUID,
    branch_id: Optional[UUID] = Query(None, description="Branch ID to check permissions for"),
    db: Session = Depends(get_tenant_db)
):
    """
    Get all permissions for a user, combining role permissions.
    Returns permissions from all roles the user has at the specified branch (or all branches if branch_id is None).
    """
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get user's branch-role assignments
    ubr_query = db.query(UserBranchRole).join(UserRole).filter(UserBranchRole.user_id == user_id)
    if branch_id:
        ubr_query = ubr_query.filter(UserBranchRole.branch_id == branch_id)
    
    user_branch_roles = ubr_query.all()
    
    if not user_branch_roles:
        return {"permissions": []}
    
    # Collect all permission names from user's roles
    permission_names = set()
    for ubr in user_branch_roles:
        # Get permissions for this role (global or branch-specific)
        rps = db.query(Permission.name).join(
            RolePermission, RolePermission.permission_id == Permission.id
        ).filter(
            RolePermission.role_id == ubr.role_id,
            or_(
                RolePermission.branch_id.is_(None),  # Global permissions
                RolePermission.branch_id == ubr.branch_id  # Branch-specific permissions
            )
        ).all()
        permission_names.update(r[0] for r in rps)
    
    return {"permissions": sorted(list(permission_names))}


@router.post("/users", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_data: UserCreate, db: Session = Depends(get_tenant_db)):
    """
    Create a new user (Admin-only)
    
    Creates a user in the database with:
    - Email (required)
    - Role (required) - will be assigned to branch if branch_id provided
    - Branch (optional)
    
    User is created as inactive/pending with invitation code.
    Returns invitation token and code for user setup.
    """
    # Normalize email (lowercase, trim)
    normalized_email = user_data.email.lower().strip()
    if not normalized_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is required"
        )
    
    # Generate username if not provided
    if user_data.username:
        normalized_username = user_data.username.lower().strip()
    elif user_data.full_name:
        # Auto-generate username from full_name
        try:
            normalized_username = generate_username_from_name(
                user_data.full_name,
                db_session=db
            ).lower()
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot generate username: {str(e)}. Please provide a username or full_name."
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either username or full_name is required to create a user"
        )
    
    # Check if user with email already exists (case-insensitive, including soft-deleted)
    existing_user = db.query(User).filter(
        func.lower(func.trim(User.email)) == normalized_email
    ).first()
    if existing_user:
        if existing_user.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with email {user_data.email} already exists. Please use a different email address."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with email {user_data.email} was previously deleted. Please contact an administrator to restore this account."
            )
    
    # Check if username already exists
    existing_username = db.query(User).filter(
        func.lower(func.trim(User.username)) == normalized_username
    ).first()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{user_data.username}' is already taken. Please choose a different username."
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
        email=normalized_email,  # Use normalized email
        username=normalized_username,  # Username for login
        full_name=user_data.full_name,
        phone=user_data.phone,
        is_active=False,  # Inactive until password is set
        is_pending=True,  # Pending password setup
        password_set=False,
        invitation_token=invitation_token,
        invitation_code=invitation_code
    )
    
    try:
        db.add(new_user)
        db.flush()  # Get the ID
    except Exception as e:
        db.rollback()
        # Check if it's a duplicate email or username error
        error_str = str(e).lower()
        if "duplicate key value violates unique constraint" in error_str:
            if "email" in error_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User with email {user_data.email} already exists. Please use a different email address."
                )
            elif "username" in error_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Username '{user_data.username}' is already taken. Please choose a different username."
                )
        # Re-raise other errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating user: {str(e)}"
        )
    
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
    
    # Send invitation email via Supabase Auth
    email_sent = False
    email_error = None
    try:
        # Create user in Supabase Auth and send invite email
        invite_result = InviteService.invite_admin_user(
            email=normalized_email,  # Use normalized email
            full_name=user_data.full_name,
            redirect_to=f"/invite?token={invitation_token}"
        )
        
        if invite_result.get("success"):
            email_sent = True
            # Note: Supabase Auth user_id will be linked when user sets password
            # For now, we use a temporary UUID and link it later
            logger.info(f"Invitation email sent to {user_data.email}")
        else:
            email_error = invite_result.get("error", "Unknown error")
            logger.warning(f"Failed to send invitation email: {email_error}")
    except Exception as e:
        email_error = str(e)
        logger.error(f"Error sending invitation email: {email_error}")
        # Don't fail the user creation if email fails - user can still use invitation code
    
    # Build invitation link (frontend URL with token)
    invitation_link = f"/invite?token={invitation_token}"
    
    message = f"User created successfully. Invitation code: {invitation_code}"
    if email_sent:
        message += " Invitation email sent."
    elif email_error:
        message += f" Note: Email could not be sent ({email_error}). User can still use the invitation code."
    
    return InvitationResponse(
        user_id=new_user.id,
        email=new_user.email,
        username=normalized_username,  # Include generated username
        invitation_token=invitation_token,
        invitation_code=invitation_code,
        invitation_link=invitation_link,
        message=message
    )


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, user_update: UserUpdate, db: Session = Depends(get_tenant_db)):
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
def activate_user(user_id: UUID, activate_data: UserActivateRequest, db: Session = Depends(get_tenant_db)):
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
def delete_user(user_id: UUID, db: Session = Depends(get_tenant_db)):
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


@router.post("/users/{user_id}/restore", response_model=UserResponse, status_code=status.HTTP_200_OK)
def restore_user(user_id: UUID, db: Session = Depends(get_tenant_db)):
    """
    Restore a soft-deleted user
    
    Removes the deleted_at timestamp to restore the user.
    User will need to be activated separately if needed.
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not deleted and cannot be restored"
        )
    
    # Restore user
    user.deleted_at = None
    
    db.commit()
    db.refresh(user)
    
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
        deleted_at=user.deleted_at,
        branch_roles=branch_roles,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


@router.post("/users/{user_id}/roles", response_model=UserResponse)
def assign_role(
    user_id: UUID,
    role_data: UserRoleUpdate,
    db: Session = Depends(get_tenant_db)
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
