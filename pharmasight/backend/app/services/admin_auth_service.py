"""
Admin Authentication Service
Handles admin user authentication and authorization
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant
import hashlib
import os


class AdminAuthService:
    """Service for admin authentication"""
    
    # Admin credentials (should be in environment variables in production)
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@pharmasight.com")
    ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")  # Will be set via script
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using SHA-256 (simple hashing for now)"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        return AdminAuthService.hash_password(password) == password_hash
    
    @staticmethod
    def is_admin_user(username: str) -> bool:
        """Check if username is admin user"""
        # Normalize input
        username_lower = username.lower().strip()
        
        # Admin username is simply "admin"
        return username_lower == "admin"
    
    @staticmethod
    def authenticate_admin(username: str, password: str) -> bool:
        """
        Authenticate admin user
        Returns True if credentials are valid
        
        Admin credentials:
        - Username: "admin"
        - Password: from environment variable ADMIN_PASSWORD (default: "33742377.jack")
        """
        if not AdminAuthService.is_admin_user(username):
            return False
        
        # Get admin password from environment variable
        # Default to the provided password for development
        admin_password = os.getenv("ADMIN_PASSWORD", "33742377.jack")
        
        # Check password
        return password == admin_password
    
    @staticmethod
    def get_admin_tenant_info() -> Optional[dict]:
        """Get admin tenant information (if admin is also a tenant)"""
        db = MasterSessionLocal()
        try:
            # Check if admin email matches any tenant
            tenant = db.query(Tenant).filter(
                Tenant.admin_email == AdminAuthService.ADMIN_EMAIL
            ).first()
            
            if tenant:
                return {
                    "is_tenant": True,
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name,
                    "subdomain": tenant.subdomain
                }
            
            return {
                "is_tenant": False
            }
        finally:
            db.close()


# Default admin credentials
DEFAULT_ADMIN_EMAIL = "admin@pharmasight.com"
DEFAULT_ADMIN_PASSWORD = "33742377.jack"
