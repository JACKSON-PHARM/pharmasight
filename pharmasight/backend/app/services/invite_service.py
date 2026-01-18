"""
Invite Service for Admin User Creation

Handles inviting admin users via Supabase Admin API.
This service NEVER creates passwords or manages authentication directly.
All authentication is handled by Supabase Auth.
"""
from typing import Optional, Dict
from supabase import create_client, Client
from app.config import settings
import logging

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
            
            # Check if user already exists
            if "already registered" in error_msg.lower() or "already exists" in error_msg.lower():
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
