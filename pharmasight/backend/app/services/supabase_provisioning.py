"""
Supabase Database Provisioning Service
Automates creation of new Supabase projects for tenants
"""
import os
import time
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from app.config import settings


class SupabaseProvisioningService:
    """Service for provisioning Supabase databases via Management API"""
    
    # Supabase Management API base URL
    API_BASE_URL = "https://api.supabase.com/v1"
    
    def __init__(self):
        self.access_token = os.getenv("SUPABASE_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("SUPABASE_ACCESS_TOKEN environment variable not set")
    
    def create_project(
        self,
        project_name: str,
        organization_id: str,
        region: str = "us-east-1",
        plan: str = "free"
    ) -> Dict:
        """
        Create a new Supabase project
        
        Args:
            project_name: Name for the project (e.g., "pharmasight-acmepharmacy")
            organization_id: Your Supabase organization ID
            region: AWS region (us-east-1, eu-west-1, etc.)
            plan: Project plan (free, pro, team, enterprise)
        
        Returns:
            Dict with project details including:
            - id: Project ID
            - ref: Project reference (used in connection strings)
            - database_url: Connection string
            - anon_key: Anon key for frontend
            - service_role_key: Service role key for backend
        """
        url = f"{self.API_BASE_URL}/projects"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "name": project_name,
            "organization_id": organization_id,
            "region": region,
            "plan": plan,
            "kps_enabled": False  # Disable KPS (optional)
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            project_data = response.json()
            
            # Wait for project to be ready
            project_id = project_data.get("id")
            if project_id:
                self._wait_for_project_ready(project_id)
                
                # Get project details including connection info
                project_details = self.get_project(project_id)
                
                return {
                    "id": project_id,
                    "ref": project_details.get("ref"),
                    "name": project_name,
                    "database_url": self._build_database_url(project_details),
                    "status": "active"
                }
            
            raise Exception("Project creation failed: No project ID returned")
        
        except requests.exceptions.HTTPError as e:
            error_msg = f"Failed to create Supabase project: {e.response.text}"
            raise Exception(error_msg)
        except Exception as e:
            raise Exception(f"Error creating Supabase project: {str(e)}")
    
    def get_project(self, project_id: str) -> Dict:
        """Get project details"""
        url = f"{self.API_BASE_URL}/projects/{project_id}"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        return response.json()
    
    def _wait_for_project_ready(self, project_id: str, max_wait: int = 300):
        """
        Wait for project to be ready
        Projects can take 1-5 minutes to provision
        """
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            project = self.get_project(project_id)
            status = project.get("status", "").lower()
            
            if status == "active":
                return True
            
            if status in ["failed", "deleted"]:
                raise Exception(f"Project creation failed with status: {status}")
            
            # Wait 10 seconds before checking again
            time.sleep(10)
        
        raise Exception(f"Project not ready after {max_wait} seconds")
    
    def _build_database_url(self, project_details: Dict) -> str:
        """Build PostgreSQL connection URL from project details"""
        # Extract connection details from project
        # Note: Actual implementation depends on Supabase API response structure
        # This is a placeholder - adjust based on actual API response
        
        db_host = project_details.get("db_host") or f"{project_details.get('ref')}.supabase.co"
        db_port = project_details.get("db_port", 5432)
        db_name = project_details.get("db_name", "postgres")
        db_user = project_details.get("db_user", "postgres")
        db_password = project_details.get("db_password")  # You'll need to get this separately
        
        if not db_password:
            # For security, Supabase doesn't return password in API
            # You'll need to generate/reset password via API or use service role
            raise Exception("Database password not available. Use Supabase dashboard to set password.")
        
        return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    def delete_project(self, project_id: str):
        """Delete a Supabase project (use with caution!)"""
        url = f"{self.API_BASE_URL}/projects/{project_id}"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        response = requests.delete(url, headers=headers)
        response.raise_for_status()
        
        return True
    
    def list_projects(self, organization_id: str) -> list:
        """List all projects in organization"""
        url = f"{self.API_BASE_URL}/projects"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        params = {
            "organization_id": organization_id
        }
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        return response.json()


# Alternative: Using Supabase Python Client (if available)
class SupabaseProvisioningServiceV2:
    """
    Alternative implementation using Supabase Python client
    Note: This requires the supabase-py library with Management API support
    """
    
    def __init__(self):
        try:
            from supabase import create_client, Client
            self.client: Optional[Client] = None
            # Note: Management API might not be in standard supabase-py
            # You may need to use requests directly (as in V1)
        except ImportError:
            raise ImportError("supabase library not installed. Run: pip install supabase")
    
    def create_project_via_client(self, project_name: str, organization_id: str) -> Dict:
        """
        Create project using Supabase client
        Note: This is a placeholder - actual implementation depends on
        whether supabase-py supports Management API
        """
        # For now, use the requests-based implementation
        service = SupabaseProvisioningService()
        return service.create_project(project_name, organization_id)


# Helper function for getting database password
def get_database_password(project_ref: str, access_token: str) -> str:
    """
    Get or reset database password for a project
    Note: This requires additional API calls or using Supabase dashboard
    """
    # Option 1: Use Supabase dashboard to set password manually
    # Option 2: Use Supabase API to reset password (if available)
    # Option 3: Store password securely when project is created
    
    # For now, return placeholder
    # In production, implement proper password management
    raise NotImplementedError("Database password retrieval not implemented. Set password via Supabase dashboard.")


# Usage example:
"""
# Initialize service
provisioning = SupabaseProvisioningService()

# Create new project for tenant
project = provisioning.create_project(
    project_name="pharmasight-acmepharmacy",
    organization_id="your-org-id",
    region="us-east-1",
    plan="free"  # or "pro" for paid tier
)

# Get connection details
database_url = project["database_url"]
project_ref = project["ref"]

# Store in tenant record
tenant.database_url = database_url
tenant.supabase_project_id = project["id"]
tenant.supabase_project_ref = project_ref
"""
