"""
Create the first client: PHARMASIGHT MEDS LTD
This script creates the tenant record manually
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant, TenantSubscription, TenantModule, SubscriptionPlan
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
            print(f"  Status: {existing.status}")
            return existing
        
        # Create tenant
        print("Creating first client: PHARMASIGHT MEDS LTD...")
        
        # Generate subdomain
        subdomain = OnboardingService._generate_subdomain("PHARMASIGHT MEDS LTD", db)
        
        tenant = Tenant(
            name="PHARMASIGHT MEDS LTD",
            subdomain=subdomain,
            admin_email="pharmasightsolutions@gmail.com",
            status='active',  # Set to active since this is your own company
            trial_ends_at=None,  # No trial for your own company
            database_name="pharmasight_main",  # Your existing database
            database_url=os.getenv("DATABASE_URL", ""),  # Use existing connection
        )
        
        db.add(tenant)
        db.flush()
        
        # Create subscription (Professional plan)
        professional_plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == 'Professional'
        ).first()
        
        if professional_plan:
            subscription = TenantSubscription(
                tenant_id=tenant.id,
                plan_id=professional_plan.id,
                status='active',
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow() + timedelta(days=365)  # 1 year
            )
            db.add(subscription)
            
            # Enable all modules
            if professional_plan.included_modules:
                for module_name in professional_plan.included_modules:
                    module = TenantModule(
                        tenant_id=tenant.id,
                        module_name=module_name,
                        is_enabled=True
                    )
                    db.add(module)
        
        db.commit()
        
        print(f"✓ Tenant created successfully!")
        print(f"  Name: {tenant.name}")
        print(f"  Subdomain: {tenant.subdomain}")
        print(f"  Email: {tenant.admin_email}")
        print(f"  ID: {tenant.id}")
        print(f"  Status: {tenant.status}")
        
        return tenant
    
    except Exception as e:
        db.rollback()
        print(f"ERROR: Failed to create tenant: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    try:
        tenant = create_first_client()
        print("\n✓ First client setup complete!")
    except Exception as e:
        print(f"\n✗ Failed: {e}")
        sys.exit(1)
