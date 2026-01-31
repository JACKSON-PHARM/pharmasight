"""
Onboarding Service - Automates tenant database provisioning
"""
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy.orm import Session
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import subprocess
import sys

from app.database_master import get_master_db, MasterSessionLocal
from app.models.tenant import Tenant, TenantInvite, TenantSubscription, TenantModule, SubscriptionPlan
from app.config import settings

# Note: For Supabase Management API, you'll need to install:
# pip install supabase
# And get your Supabase access token from: https://supabase.com/dashboard/account/tokens


class OnboardingService:
    """Service for automating tenant onboarding"""
    
    @staticmethod
    def create_tenant_from_signup(
        email: str,
        company_name: str,
        db: Session
    ) -> Dict:
        """
        Create a new tenant from signup form
        Returns tenant info and invite token
        """
        # Generate subdomain
        subdomain = OnboardingService._generate_subdomain(company_name, db)
        
        # Check if email already exists
        existing = db.query(Tenant).filter(Tenant.admin_email == email).first()
        if existing:
            raise ValueError(f"Tenant with email {email} already exists")
        
        # Create tenant record
        tenant = Tenant(
            name=company_name,
            subdomain=subdomain,
            admin_email=email,
            status='trial',
            trial_ends_at=datetime.utcnow() + timedelta(days=14)
        )
        
        db.add(tenant)
        db.flush()  # Get tenant.id
        
        # Create Supabase database (or use existing connection for now)
        # TODO: Implement Supabase Management API integration
        # For now, we'll use the same database but different schema approach
        # or manual Supabase project creation
        
        database_info = OnboardingService._provision_database(tenant, db)
        
        # Update tenant with database info
        tenant.database_name = database_info.get('database_name')
        tenant.database_url = database_info.get('database_url')
        tenant.supabase_project_id = database_info.get('project_id')
        tenant.supabase_project_ref = database_info.get('project_ref')
        
        # Run migrations on new database
        OnboardingService._run_migrations(database_info.get('database_url'))
        
        # Create admin user in tenant database
        admin_user_id = OnboardingService._create_admin_user(
            database_info.get('database_url'),
            email
        )
        
        tenant.admin_user_id = admin_user_id
        
        # Create trial subscription
        starter_plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.name == 'Starter'
        ).first()
        
        if starter_plan:
            subscription = TenantSubscription(
                tenant_id=tenant.id,
                plan_id=starter_plan.id,
                status='trial',
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow() + timedelta(days=14)
            )
            db.add(subscription)
            
            # Enable modules from plan
            if starter_plan.included_modules:
                for module_name in starter_plan.included_modules:
                    module = TenantModule(
                        tenant_id=tenant.id,
                        module_name=module_name,
                        is_enabled=True
                    )
                    db.add(module)
        
        # Generate invite token
        invite = OnboardingService._create_invite(tenant.id, db)
        
        db.commit()
        
        return {
            'tenant': tenant,
            'invite_token': invite.token,
            'subdomain': subdomain,
            'database_url': database_info.get('database_url')
        }
    
    @staticmethod
    def _generate_subdomain(company_name: str, db: Session) -> str:
        """Generate unique subdomain from company name"""
        base = company_name.lower()
        base = ''.join(c if c.isalnum() or c in ('-', '_') else '-' for c in base)
        base = '-'.join(base.split())
        base = base.strip('-')
        
        if len(base) > 50:
            base = base[:50]
        
        subdomain = base
        counter = 1
        while db.query(Tenant).filter(Tenant.subdomain == subdomain).first():
            subdomain = f"{base}{counter}"
            counter += 1
        
        return subdomain
    
    @staticmethod
    def _provision_database(tenant: Tenant, db: Session) -> Dict:
        """
        Provision a new Supabase database for tenant
        Uses Supabase Management API if available, otherwise falls back to same database
        """
        supabase_token = os.getenv("SUPABASE_ACCESS_TOKEN")
        organization_id = os.getenv("SUPABASE_ORGANIZATION_ID")
        
        # Try to use Supabase Management API
        if supabase_token and organization_id:
            try:
                from app.services.supabase_provisioning import SupabaseProvisioningService
                
                provisioning = SupabaseProvisioningService()
                
                # Generate project name
                project_name = f"pharmasight-{tenant.subdomain}"
                
                # Create project
                project = provisioning.create_project(
                    project_name=project_name,
                    organization_id=organization_id,
                    region=os.getenv("SUPABASE_REGION", "us-east-1"),
                    plan=os.getenv("SUPABASE_PLAN", "free")
                )
                
                return {
                    'database_name': project_name,
                    'database_url': project.get('database_url'),  # You'll need to get password separately
                    'project_id': project.get('id'),
                    'project_ref': project.get('ref')
                }
            
            except Exception as e:
                print(f"Warning: Failed to create Supabase project via API: {e}")
                print("Falling back to same database approach")
                # Fall through to fallback
        
        # Fallback: Use same database (development mode)
        # In production, you should always use separate databases
        database_name = f"pharmasight_{tenant.subdomain}"
        
        return {
            'database_name': database_name,
            'database_url': settings.database_connection_string,  # Same DB for now
            'project_id': None,
            'project_ref': None
        }
    
    @staticmethod
    def _run_migrations(database_url: str):
        """
        Run database migrations on tenant database
        """
        # TODO: Implement migration runner
        # This should run all migrations from database/schema.sql
        # or use Alembic migrations
        
        # For now, we'll assume migrations are run manually or via script
        # In production, use Alembic or similar
        pass
    
    @staticmethod
    def _create_admin_user(database_url: str, email: str) -> uuid.UUID:
        """
        Create admin user in tenant database
        Returns user_id (UUID)
        
        Note: For now, this is a placeholder. In production, you'll need to:
        1. Create user in Supabase Auth first
        2. Then create user record in tenant database
        3. Link them together
        """
        try:
            # Connect to tenant database
            conn = psycopg2.connect(database_url)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            
            # Generate user ID
            user_id = uuid.uuid4()
            
            # Create user in tenant database
            # Note: This assumes the tenant database has the users table
            # In production, you should create the user in Supabase Auth first,
            # then use that user_id here
            cursor.execute("""
                INSERT INTO users (id, email, full_name, is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                SET id = EXCLUDED.id
                RETURNING id
            """, (
                str(user_id),
                email,
                'Admin User',
                True,
                datetime.utcnow(),
                datetime.utcnow()
            ))
            
            result = cursor.fetchone()
            if result:
                user_id = uuid.UUID(result[0])
            
            cursor.close()
            conn.close()
            
            return user_id
        except Exception as e:
            # If database doesn't exist yet or table doesn't exist, return a UUID anyway
            # The actual user creation will happen during setup wizard
            print(f"Warning: Could not create admin user in database: {e}")
            return uuid.uuid4()
    
    @staticmethod
    def _create_invite(tenant_id: uuid.UUID, db: Session, expires_days: int = 7) -> TenantInvite:
        """Create invite token for tenant setup"""
        import secrets
        import string
        
        # Generate secure token
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(32))
        
        invite = TenantInvite(
            tenant_id=tenant_id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(days=expires_days)
        )
        
        db.add(invite)
        return invite
    
    @staticmethod
    def validate_invite_token(token: str, db: Session) -> Optional[Tenant]:
        """Validate invite token and return tenant"""
        invite = db.query(TenantInvite).filter(
            TenantInvite.token == token,
            TenantInvite.used_at.is_(None),
            TenantInvite.expires_at > datetime.utcnow()
        ).first()
        
        if not invite:
            return None
        
        tenant = db.query(Tenant).filter(Tenant.id == invite.tenant_id).first()
        return tenant
    
    @staticmethod
    def mark_invite_used(token: str, user_id: uuid.UUID, db: Session):
        """Mark invite as used"""
        invite = db.query(TenantInvite).filter(TenantInvite.token == token).first()
        if invite:
            invite.used_at = datetime.utcnow()
            invite.user_id = user_id
            db.commit()
