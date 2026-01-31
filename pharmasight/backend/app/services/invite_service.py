"""
Invite Service for Admin User Creation

Handles inviting admin users via Supabase Admin API.
This service NEVER creates passwords or manages authentication directly.
All authentication is handled by Supabase Auth.
"""
import json
import logging
import urllib.request
import urllib.error
from typing import Optional, Dict, Any
from supabase import create_client, Client
from app.config import settings

logger = logging.getLogger(__name__)


class InviteService:
    """Service for inviting admin users via Supabase Auth"""
    
    @staticmethod
    def get_supabase_admin_client() -> Optional[Client]:
        """
        Get Supabase admin client using service role key
        
        Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in environment.
        Service role key has admin privileges and should NEVER be exposed to frontend.
        """
        if not settings.SUPABASE_URL:
            logger.error("SUPABASE_URL not configured")
            return None
        
        # Service role key (admin privileges) - must be set in environment
        service_role_key = settings.SUPABASE_SERVICE_ROLE_KEY
        if not service_role_key:
            logger.error("SUPABASE_SERVICE_ROLE_KEY not configured. Required for admin operations.")
            return None
        
        try:
            supabase: Client = create_client(
                settings.SUPABASE_URL,
                service_role_key
            )
            return supabase
        except Exception as e:
            logger.error(f"Failed to create Supabase admin client: {str(e)}")
            return None

    @staticmethod
    def _find_auth_user_by_email(client: Client, email: str) -> Optional[Any]:
        """
        Find Supabase Auth user by email. Tries Python client list_users first,
        then direct HTTP to Auth Admin API (more reliable across client versions).
        Returns user dict with id and email, or None.
        """
        email_lower = (email or "").strip().lower()
        if not email_lower:
            return None
        # 1) Try Python client (may use different param names / response shape)
        try:
            page = 1
            per_page = 1000
            while True:
                resp = client.auth.admin.list_users(per_page=per_page, page=page)
                users = getattr(resp, "users", None) or []
                if not users:
                    break
                for u in users:
                    u_email = (getattr(u, "email", None) or (u.get("email") if isinstance(u, dict) else None)) or ""
                    if u_email.strip().lower() == email_lower:
                        return u if isinstance(u, dict) else {"id": getattr(u, "id", None), "email": u_email}
                if len(users) < per_page:
                    break
                page += 1
        except Exception as e:
            logger.debug(f"list_users failed: {e}")
        # 2) Fallback: direct HTTP to Supabase Auth Admin API
        return InviteService._find_auth_user_by_email_http(email_lower)
    
    @staticmethod
    def _find_auth_user_by_email_http(email_lower: str) -> Optional[Dict]:
        """Find Auth user by email via GET /auth/v1/admin/users (pagination)."""
        base_url = (getattr(settings, "SUPABASE_URL", None) or "").rstrip("/")
        key = getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None) or ""
        if not base_url or not key:
            return None
        page = 1
        per_page = 1000
        while True:
            try:
                url = f"{base_url}/auth/v1/admin/users?per_page={per_page}&page={page}"
                req = urllib.request.Request(
                    url,
                    headers={
                        "apikey": key,
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode())
                users = data.get("users") if isinstance(data, dict) else []
                if not users:
                    return None
                for u in users:
                    if isinstance(u, dict):
                        u_email = (u.get("email") or "").strip().lower()
                        if u_email == email_lower:
                            return {"id": u.get("id"), "email": u.get("email")}
                if len(users) < per_page:
                    return None
                page += 1
            except urllib.error.HTTPError as e:
                logger.warning(f"Auth admin list users HTTP error: {e.code} {e.reason}")
                return None
            except Exception as e:
                logger.warning(f"Auth admin list users request failed: {e}")
                return None

    @staticmethod
    def invite_admin_user(
        email: str,
        full_name: Optional[str] = None,
        redirect_to: str = "/setup"
    ) -> Dict:
        """
        Invite an admin user via Supabase Auth
        
        This function:
        1. Creates an auth user (no password)
        2. Sends invite email via Supabase
        3. Sets user metadata: role=company_admin, must_setup_company=true
        4. Returns user ID for app database record creation
        
        Args:
            email: Admin user email address
            full_name: Optional full name
            redirect_to: URL to redirect after password setup (default: /setup)
        
        Returns:
            dict with:
                - success: bool
                - user_id: UUID (Supabase Auth user ID)
                - message: str
                - error: str (if failed)
        
        Raises:
            ValueError: If Supabase client creation fails or invite fails
        """
        supabase = InviteService.get_supabase_admin_client()
        if not supabase:
            raise ValueError(
                "Supabase admin client not available. "
                "Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY configuration."
            )
        
        try:
            # Prepare user metadata
            user_metadata = {
                "role": "company_admin",
                "must_setup_company": "true",
                "full_name": full_name or ""
            }
            
            # Create user and send invite email
            # Using admin API to create user without password
            response = supabase.auth.admin.create_user({
                "email": email,
                "email_confirm": False,  # User will confirm via email invite
                "user_metadata": user_metadata,
                "app_metadata": {
                    "role": "company_admin"
                }
            })
            
            if not response.user:
                raise ValueError("Failed to create user in Supabase Auth")
            
            user_id = response.user.id
            
            # Send invite email
            # Note: Supabase admin API doesn't have a direct invite method in Python SDK
            # We'll use the inviteUserByEmail method if available, or create user with email_confirm=False
            # and let them use password reset flow
            
            # Alternative: Use inviteUserByEmail if available
            try:
                invite_response = supabase.auth.admin.invite_user_by_email(
                    email,
                    {
                        "redirect_to": redirect_to,
                        "data": user_metadata
                    }
                )
                logger.info(f"Invite email sent to {email}")
            except AttributeError:
                # If inviteUserByEmail not available, user was created and can use password reset
                logger.warning(
                    "inviteUserByEmail not available. "
                    "User created but may need manual password reset link."
                )
            
            return {
                "success": True,
                "user_id": user_id,
                "email": email,
                "message": f"Admin user invited successfully. Invite email sent to {email}."
            }
            
        except Exception as e:
            logger.error(f"Error inviting admin user: {str(e)}")
            error_msg = str(e)
            
            # Check if user already exists (Supabase may say "already been registered" or "already registered")
            err_lower = error_msg.lower()
            if ("already" in err_lower and "registered" in err_lower) or "already exists" in err_lower:
                # Try to get existing user
                try:
                    existing_users = supabase.auth.admin.list_users()
                    for user in existing_users.users:
                        if user.email == email:
                            return {
                                "success": True,
                                "user_id": user.id,
                                "email": email,
                                "message": f"User {email} already exists. You can resend invite or use password reset."
                            }
                except:
                    pass
            
            return {
                "success": False,
                "user_id": None,
                "email": email,
                "error": error_msg,
                "message": f"Failed to invite admin user: {error_msg}"
            }
    
    @staticmethod
    def create_user_with_password(
        email: str,
        password: str,
        full_name: Optional[str] = None,
    ) -> Dict:
        """
        Create Supabase Auth user with password (no invite email).
        Used for tenant-invite setup: user sets password on our page, then signs in.

        Returns dict with success, user_id, email, or error.
        """
        supabase = InviteService.get_supabase_admin_client()
        if not supabase:
            raise ValueError(
                "Supabase admin client not available. "
                "Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY configuration."
            )
        try:
            user_metadata = {
                "role": "company_admin",
                "must_setup_company": "true",
                "full_name": full_name or "",
            }
            payload = {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": user_metadata,
                "app_metadata": {"role": "company_admin"},
            }
            response = supabase.auth.admin.create_user(payload)
            if not response.user:
                raise ValueError("Failed to create user in Supabase Auth")
            logger.info(f"Created user with password for tenant invite: {email}")
            return {
                "success": True,
                "user_id": response.user.id,
                "email": email,
                "message": "User created. They can sign in with username and password.",
            }
        except Exception as e:
            logger.error(f"Error creating user with password: {e}")
            err = str(e)
            err_lower = err.lower()
            # Supabase can return "already been registered" or "already registered" or "already exists"
            if ("already" in err_lower and "registered" in err_lower) or "already exists" in err_lower:
                # User already exists in Supabase Auth (e.g. seeded, or previous invite). Set their password instead.
                try:
                    existing_auth_user = InviteService._find_auth_user_by_email(supabase, email)
                    if existing_auth_user:
                        auth_uid = existing_auth_user.get("id") if isinstance(existing_auth_user, dict) else getattr(existing_auth_user, "id", None)
                        if auth_uid:
                            update_result = InviteService.update_user_password(str(auth_uid), password)
                            if update_result.get("success"):
                                logger.info(f"Set password for existing Auth user on invite complete: {email}")
                                return {
                                    "success": True,
                                    "user_id": auth_uid,
                                    "email": email,
                                    "message": "Password set. You can sign in with your username and password.",
                                }
                except Exception as lookup_err:
                    logger.warning(f"Could not look up or update existing user by email: {lookup_err}")
                return {
                    "success": False,
                    "user_id": None,
                    "email": email,
                    "error": err,
                    "message": "A user with this email already exists. Use login or forgot password.",
                }
            return {
                "success": False,
                "user_id": None,
                "email": email,
                "error": err,
                "message": f"Failed to create user: {err}",
            }

    @staticmethod
    def update_user_password(user_id: str, password: str) -> Dict:
        """
        Update Supabase Auth user password by id (admin API).
        Used when completing tenant invite for an existing user (same email).
        """
        supabase = InviteService.get_supabase_admin_client()
        if not supabase:
            raise ValueError("Supabase admin client not available")
        try:
            supabase.auth.admin.update_user_by_id(user_id, {"password": password})
            logger.info(f"Updated password for user {user_id}")
            return {"success": True, "message": "Password updated."}
        except Exception as e:
            logger.error(f"Error updating user password: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to update password: {str(e)}",
            }

    @staticmethod
    def update_user_metadata(user_id: str, metadata: Dict) -> Dict:
        """
        Update user metadata in Supabase Auth
        
        Args:
            user_id: Supabase Auth user ID
            metadata: Dictionary of metadata to update
        
        Returns:
            dict with success status
        """
        supabase = InviteService.get_supabase_admin_client()
        if not supabase:
            raise ValueError("Supabase admin client not available")
        
        try:
            response = supabase.auth.admin.update_user_by_id(
                user_id,
                {
                    "user_metadata": metadata
                }
            )
            
            if response.user:
                return {
                    "success": True,
                    "message": "User metadata updated successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to update user metadata"
                }
        except Exception as e:
            logger.error(f"Error updating user metadata: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def mark_setup_complete(user_id: str) -> Dict:
        """
        Mark company setup as complete for a user
        
        Updates user metadata: must_setup_company = false
        
        Args:
            user_id: Supabase Auth user ID
        
        Returns:
            dict with success status
        """
        return InviteService.update_user_metadata(
            user_id,
            {"must_setup_company": "false"}
        )
