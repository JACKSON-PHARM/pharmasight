"""
Authentication API
Handles username-based login (looks up email from username).

Uses get_tenant_db: LEGACY when no X-Tenant-* header, TENANT DB when resolved.
When no tenant header and user not in legacy DB, discovers which tenant the user
belongs to so the app can route them to their tenant data.
If the same username exists in more than one tenant, we require tenant context (link or picker).
"""
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database_master import get_master_db
from app.dependencies import get_tenant_db, get_tenant_from_header, tenant_db_session
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter()


class UsernameLoginRequest(BaseModel):
    """Username-based login request"""
    username: str
    password: str


class UsernameLoginResponse(BaseModel):
    """Username login response with email for Supabase Auth and tenant context."""
    email: str
    user_id: str
    username: Optional[str] = None  # Display name for UI (e.g. B-BRIDGIT1)
    full_name: Optional[str] = None
    tenant_subdomain: Optional[str] = None  # So frontend knows which tenant DB to use for this session


def _find_user_in_db(db: Session, normalized_username: str, check_email: bool) -> Optional[User]:
    """Look up user by username (and optionally email) in the given session."""
    user = db.query(User).filter(
        func.lower(func.trim(User.username)) == normalized_username,
        User.is_active == True,
        User.deleted_at.is_(None)
    ).first()
    if not user and check_email:
        user = db.query(User).filter(
            func.lower(func.trim(User.email)) == normalized_username,
            User.is_active == True,
            User.deleted_at.is_(None)
        ).first()
    return user


def _find_user_in_all_tenants(
    master_db: Session, normalized_username: str, check_email: bool
) -> List[Tuple[Tenant, User]]:
    """
    Find all tenants where this username exists.
    Returns list of (tenant, user) so we can detect collisions (same username in 2+ tenants).
    """
    tenants = master_db.query(Tenant).filter(
        Tenant.database_url.isnot(None),
        Tenant.status != "cancelled",
    ).all()
    found: List[Tuple[Tenant, User]] = []
    for tenant in tenants:
        try:
            with tenant_db_session(tenant) as db:
                user = _find_user_in_db(db, normalized_username, check_email)
                if user:
                    found.append((tenant, user))
        except Exception:
            continue
    return found


@router.post("/auth/username-login", response_model=UsernameLoginResponse)
def username_login(
    request: UsernameLoginRequest,
    tenant: Optional[Tenant] = Depends(get_tenant_from_header),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """
    Lookup user by username and return email for Supabase Auth.

    - With X-Tenant-Subdomain: lookup in that tenant's DB; return tenant_subdomain so frontend persists it.
    - Without header: lookup in legacy DB; if not found, discover tenant by searching provisioned tenant DBs,
      then return user and tenant_subdomain so the app knows where the user belongs.
    """
    normalized_username = request.username.lower().strip()
    check_email = "@" in request.username

    user = _find_user_in_db(db, normalized_username, check_email)

    if not user and tenant is None:
        # No tenant header and not in legacy DB: discover which tenant(s) this user belongs to
        found_list = _find_user_in_all_tenants(master_db, normalized_username, check_email)
        if len(found_list) == 0:
            pass  # fall through to 404 below
        elif len(found_list) == 1:
            tenant, user = found_list[0]
            return UsernameLoginResponse(
                email=user.email,
                user_id=str(user.id),
                username=getattr(user, "username", None) or None,
                full_name=user.full_name,
                tenant_subdomain=tenant.subdomain,
            )
        else:
            # Same username exists in more than one tenant: require tenant context (invite link or picker)
            tenants_info = [
                {"subdomain": t.subdomain, "name": t.name}
                for t, _ in found_list
            ]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "multiple_tenants",
                    "message": (
                        "This username exists in more than one organization. "
                        "Please sign in using the link from your invite email, or add ?tenant=SUBDOMAIN to the URL "
                        "(e.g. ...#login?tenant=your-org-subdomain)."
                    ),
                    "tenants": tenants_info,
                },
            )
    elif not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    else:
        return UsernameLoginResponse(
            email=user.email,
            user_id=str(user.id),
            username=getattr(user, "username", None) or None,
            full_name=user.full_name,
            tenant_subdomain=tenant.subdomain if tenant else None,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="User not found"
    )
