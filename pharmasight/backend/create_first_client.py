"""
Create the first client: PHARMASIGHT MEDS LTD
This script creates the tenant record manually
"""
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant
from app.services.company_provisioning_service import create_company_with_hq_branch_and_registry
from app.services.onboarding_service import OnboardingService


def create_first_client():
    """Create PHARMASIGHT MEDS LTD as the first tenant"""
    db = MasterSessionLocal()

    try:
        # Check if tenant already exists
        existing = db.query(Tenant).filter(
            Tenant.admin_email == "pharmasightsolutions@gmail.com"
        ).first()

        if existing:
            print(f"✓ Tenant already exists: {existing.name} ({existing.subdomain})")
            print(f"  ID: {existing.id}")
            return existing

        # Create tenant
        print("Creating first client: PHARMASIGHT MEDS LTD...")

        # Generate subdomain
        subdomain = OnboardingService._generate_subdomain("PHARMASIGHT MEDS LTD", db)

        app_db = SessionLocal()
        try:
            _company, _branch, tenant = create_company_with_hq_branch_and_registry(
                app_db,
                db,
                company_kwargs={
                    "name": "PHARMASIGHT MEDS LTD",
                    "currency": "KES",
                    "timezone": "Africa/Nairobi",
                    "is_active": True,
                },
                admin_email="pharmasightsolutions@gmail.com",
                tenant_subdomain=subdomain,
                tenant_status="active",
            )
        except Exception:
            app_db.rollback()
            raise
        finally:
            app_db.close()

        print("✓ Tenant created successfully!")
        print(f"  Name: {tenant.name}")
        print(f"  Subdomain: {tenant.subdomain}")
        print(f"  Email: {tenant.admin_email}")
        print(f"  ID: {tenant.id}")
        return tenant

    except Exception as e:
        db.rollback()
        print(f"ERROR: Failed to create tenant: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_first_client()
