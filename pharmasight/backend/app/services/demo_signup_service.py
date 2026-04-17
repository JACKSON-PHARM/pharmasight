"""
Demo signup service.

This service will be responsible for self‑service demo onboarding from the public
login page without going through the existing admin‑driven onboarding flow.

create_demo_tenant:
  - create a minimal master ``Tenant`` row (subdomain + routing metadata only; Option B)
  - create a ``Company`` with trial, limits, and ``subscription_plan='demo'`` (entitlement)
  - provision the shared app database using the existing migration pipeline
  - create HQ ``Branch``, admin ``User``, and issue authentication tokens
"""
from __future__ import annotations

from typing import Any, Dict
from datetime import datetime, timedelta, timezone
import secrets
import uuid
import threading

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant, TenantInvite
from app.models.company import Company, Branch
from app.models.user import User, UserRole, UserBranchRole
from app.services.tenant_provisioning import _sanitize_db_name
from app.services.migration_service import run_migrations_for_url
from app.services.email_service import EmailService
from app.utils.username_generator import generate_username_from_name
from app.utils.auth_internal import hash_password, create_access_token, create_refresh_token
from app.services.tenant_registry_service import create_and_commit_registry_tenant

# Demo signup uses the shared application DB. Running the full migrations pipeline per request is
# expensive and can be abused for resource exhaustion. We guard migrations so we only run them
# once per app process (per DATABASE_URL).
_shared_db_migrations_lock = threading.Lock()
_shared_db_migrations_ran: bool = False
_shared_db_migrations_database_url: str | None = None


def _ensure_shared_db_migrated_once(database_url: str) -> None:
    global _shared_db_migrations_ran, _shared_db_migrations_database_url
    database_url = (database_url or "").strip()
    if not database_url:
        return
    if _shared_db_migrations_ran and _shared_db_migrations_database_url == database_url:
        return
    with _shared_db_migrations_lock:
        if _shared_db_migrations_ran and _shared_db_migrations_database_url == database_url:
            return
        run_migrations_for_url(database_url)
        _shared_db_migrations_ran = True
        _shared_db_migrations_database_url = database_url


def create_demo_tenant(
    organization_name: str,
    full_name: str,
    email: str,
    phone: str | None,
    password: str,
) -> Dict[str, Any]:
    """
    Placeholder for future self‑service demo signup logic.

    Behaviour:
      - Validate basic input (non-empty organization name, full name, email, password).
      - Create a minimal master ``Tenant`` row (infra) and a ``Company`` row (entitlement + limits).
      - Provision the shared application database (using existing migration pipeline).
      - In the tenant database, create:
          * a Company representing the organization,
          * a single HQ Branch marked as HQ,
          * an initial admin User associated with that branch and with a hashed password.
      - Issue authentication tokens so the caller can log the user in immediately.
    """
    organization_name = (organization_name or "").strip()
    full_name = (full_name or "").strip()
    email = (email or "").strip().lower()
    phone = (phone or "").strip() if phone else None
    password = (password or "").strip()

    if not organization_name:
        raise ValueError("Organization name is required.")
    if not full_name:
        raise ValueError("Your full name is required.")
    if not email:
        raise ValueError("Email is required.")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    demo_duration_days = getattr(settings, "DEMO_DURATION_DAYS", 7) or 7
    demo_product_limit = getattr(settings, "DEMO_PRODUCT_LIMIT", 100) or 100
    demo_user_limit = getattr(settings, "DEMO_USER_LIMIT", 1) or 1

    master_db: Session = MasterSessionLocal()
    try:
        org_norm = organization_name.strip()
        org_norm_lc = org_norm.lower()
        # Recovery mode: sometimes we may already have the Company/User in the shared app DB
        # (because an earlier attempt partially succeeded), but the master DB `tenants` row is
        # missing—recovery below recreates the master row and setup invite.
        recover_existing_app_user = False
        recover_company_id: uuid.UUID | None = None
        recover_admin_user_id: uuid.UUID | None = None
        recover_admin_username: str | None = None

        def _create_setup_invite_and_send(tenant: Tenant, to_email: str, username: str | None) -> None:
            """Best-effort: create a TenantInvite and send setup email."""
            now = datetime.now(timezone.utc)
            token_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            invite_token = "".join(secrets.choice(token_chars) for _ in range(32))

            invite = TenantInvite(
                tenant_id=tenant.id,
                token=invite_token,
                expires_at=now + timedelta(days=7),
            )
            master_db.add(invite)
            master_db.commit()

            base_url = (getattr(settings, "APP_PUBLIC_URL", None) or "").strip().rstrip("/")
            if not base_url:
                base_url = "http://localhost:3000"
            setup_url = f"{base_url}/setup?token={invite_token}"

            # Email sending should never block tenant creation flow.
            try:
                EmailService.send_tenant_invite(
                    to_email=to_email,
                    tenant_name=tenant.name,
                    setup_url=setup_url,
                    username=username,
                )
            except Exception:
                # Log-only; invite token still exists in master DB.
                pass

        # Ensure organization name is unique in master (tenants table)
        existing_tenant_by_org = (
            master_db.query(Tenant)
            .filter(func.lower(func.trim(Tenant.name)) == org_norm_lc)
            .first()
        )
        if existing_tenant_by_org:
            # If the same email is already tied to this organization, resend invite.
            if (existing_tenant_by_org.admin_email or "").strip().lower() == email:
                app_db: Session = SessionLocal()
                try:
                    existing_admin_user = (
                        app_db.query(User)
                        .filter(func.lower(func.trim(User.email)) == email, User.deleted_at.is_(None))
                        .first()
                    )
                    username = existing_admin_user.username if existing_admin_user else None
                finally:
                    app_db.close()

                _create_setup_invite_and_send(existing_tenant_by_org, to_email=email, username=username)
                raise ValueError(
                    "That email is already registered for this organization. We re-sent your setup email (check your inbox and spam). Sign in with your email, or use a different email to create a new account."
                )

            raise ValueError(
                "An organization with this name already exists. Sign in with that organization, or use a different organization name."
            )

        # Ensure email is not already used as a tenant admin
        existing_tenant = (
            master_db.query(Tenant)
            .filter(func.lower(func.trim(Tenant.admin_email)) == email)
            .first()
        )
        if existing_tenant:
            # Invite/link may not have been delivered earlier; resend best-effort.
            app_db: Session = SessionLocal()
            try:
                existing_admin_user = (
                    app_db.query(User)
                    .filter(func.lower(func.trim(User.email)) == email, User.deleted_at.is_(None))
                    .first()
                )
                username = existing_admin_user.username if existing_admin_user else None
                if not username:
                    try:
                        username = generate_username_from_name(existing_tenant.admin_full_name or "", db_session=app_db)
                    except Exception:
                        username = None
            finally:
                app_db.close()

            _create_setup_invite_and_send(existing_tenant, to_email=email, username=username)
            raise ValueError(
                "An account is already registered with this email. We re-sent your setup email (check your inbox and spam). Sign in with that email, or use a different email to create a new account."
            )

        # Shared app DB: block if this email already exists as a user (e.g. another org)
        app_db: Session = SessionLocal()
        try:
            dup_user = (
                app_db.query(User)
                .filter(func.lower(func.trim(User.email)) == email, User.deleted_at.is_(None))
                .first()
            )
            if dup_user:
                # If the master tenant row is missing but the user/company already exist in the app DB,
                # recover by creating the missing master `tenants` entry and issuing the setup invite.
                dup_company = (
                    app_db.query(Company)
                    .filter(func.lower(func.trim(Company.name)) == org_norm_lc)
                    .first()
                )
                if dup_company:
                    recover_existing_app_user = True
                    recover_company_id = dup_company.id
                    recover_admin_user_id = dup_user.id
                    recover_admin_username = dup_user.username

                    # Update the password to match what the user just submitted.
                    dup_user.password_hash = hash_password(password)
                    dup_user.password_set = True
                    dup_user.must_change_password = True
                    app_db.commit()
                else:
                    # Email exists, but not for this organization name—block this attempt.
                    raise ValueError(
                        "An account is already registered with this email. We re-sent your setup email (check your inbox and spam). Sign in with that email, or use a different email to create a new account."
                    )
            else:
                dup_company = (
                    app_db.query(Company)
                    .filter(func.lower(func.trim(Company.name)) == org_norm_lc)
                    .first()
                )
                if dup_company:
                    raise ValueError(
                        "An organization with this name already exists. Sign in with that organization, or use a different organization name."
                    )
        finally:
            app_db.close()

        # Global throttle: avoid demo signup storms chocking the master DB / shared DB.
        # IP-based rate limiting can be bypassed; this protects you when many IPs attempt abuse.
        max_demo_signups_per_hour = getattr(settings, "DEMO_SIGNUP_MAX_PER_HOUR", None)
        if max_demo_signups_per_hour:
            try:
                max_demo_signups_per_hour = int(max_demo_signups_per_hour)
            except Exception:
                max_demo_signups_per_hour = None
        if max_demo_signups_per_hour and max_demo_signups_per_hour > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            app_db_count: Session = SessionLocal()
            try:
                recent_demo_count = (
                    app_db_count.query(Company)
                    .filter(func.lower(func.trim(Company.subscription_plan)) == "demo")
                    .filter(Company.created_at >= cutoff)
                    .count()
                )
            finally:
                app_db_count.close()
            if recent_demo_count >= max_demo_signups_per_hour:
                raise ValueError("Too many demo signups. Please try again later.")

        # Generate a simple subdomain from organization name
        base = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in org_norm.lower()).strip("-")
        if len(base) > 50:
            base = base[:50]
        subdomain = base or "demo"
        counter = 1
        while master_db.query(Tenant).filter(Tenant.subdomain == subdomain).first():
            subdomain = f"{base or 'demo'}{counter}"
            counter += 1

        now = datetime.now(timezone.utc)
        demo_expires_at = now + timedelta(days=demo_duration_days)

        # For demo tenants, we reuse the main application database URL and run migrations once if needed.
        database_url = settings.database_connection_string
        if not database_url:
            raise RuntimeError("DATABASE_URL is not configured for demo provisioning.")

        # Run migrations (idempotent for shared DB). Do not call initialize_tenant_database() here:
        # that helper only allows an empty database; demo uses the shared app DB which is already initialized.
        _ensure_shared_db_migrated_once(database_url)

        # Now create Company, HQ Branch, and Admin User inside the tenant/app DB (company_id before master Tenant).
        tenant_db: Session = SessionLocal()
        company_id: uuid.UUID | None = None
        admin_user_id: uuid.UUID | None = None
        admin_username: str | None = None
        try:
            if recover_existing_app_user:
                company = (
                    tenant_db.query(Company)
                    .filter(Company.id == recover_company_id)
                    .first()
                )
                if not company:
                    raise RuntimeError("Demo signup recovery failed: company not found.")

                admin_user_id = recover_admin_user_id
                if not admin_user_id:
                    raise RuntimeError("Demo signup recovery failed: admin_user_id missing.")

                admin_user = (
                    tenant_db.query(User)
                    .filter(User.id == admin_user_id)
                    .first()
                )
                if not admin_user:
                    raise RuntimeError("Demo signup recovery failed: user not found.")

                # Keep tenant fields aligned with current request.
                company_id = company.id
                admin_username = recover_admin_username or admin_user.username
                admin_user.full_name = full_name
                admin_user.phone = phone

                # Ensure HQ branch and admin role mapping exist.
                hq_branch = (
                    tenant_db.query(Branch)
                    .filter(
                        Branch.company_id == company.id,
                        Branch.code == "HQ",
                        Branch.is_hq.is_(True),
                    )
                    .first()
                )
                if not hq_branch:
                    hq_branch = Branch(
                        company_id=company.id,
                        name="Main Branch",
                        code="HQ",
                        is_hq=True,
                        phone=phone,
                        is_active=True,
                    )
                    tenant_db.add(hq_branch)
                    tenant_db.flush()

                admin_role = (
                    tenant_db.query(UserRole)
                    .filter(UserRole.role_name == "admin")
                    .first()
                )
                if not admin_role:
                    admin_role = UserRole(role_name="admin", description="Demo admin")
                    tenant_db.add(admin_role)
                    tenant_db.flush()

                existing_mapping = (
                    tenant_db.query(UserBranchRole)
                    .filter(
                        UserBranchRole.user_id == admin_user.id,
                        UserBranchRole.branch_id == hq_branch.id,
                    )
                    .first()
                )
                if not existing_mapping:
                    tenant_db.add(
                        UserBranchRole(
                            user_id=admin_user.id,
                            branch_id=hq_branch.id,
                            role_id=admin_role.id,
                        )
                    )

                if company.trial_expires_at is None or company.trial_expires_at < demo_expires_at:
                    company.trial_expires_at = demo_expires_at
                if not (company.subscription_plan or "").strip():
                    company.subscription_plan = "demo"
                company.subscription_status = None
                company.product_limit = demo_product_limit
                company.branch_limit = 1
                company.user_limit = demo_user_limit
                tenant_db.commit()
            else:
                company = Company(
                    name=org_norm,
                    phone=phone,
                    trial_expires_at=demo_expires_at,
                    subscription_plan="demo",
                    subscription_status=None,
                    is_active=True,
                    product_limit=demo_product_limit,
                    branch_limit=1,
                    user_limit=demo_user_limit,
                )
                tenant_db.add(company)
                tenant_db.flush()
                company_id = company.id  # capture before commit/session close

                hq_branch = Branch(
                    company_id=company.id,
                    name="Main Branch",
                    code="HQ",
                    is_hq=True,
                    phone=phone,
                    is_active=True,
                )
                tenant_db.add(hq_branch)
                tenant_db.flush()

                # Create admin user with hashed password
                username = generate_username_from_name(full_name, db_session=tenant_db)
                password_hash = hash_password(password)

                # users.id has no server/default generator, so we must assign it.
                admin_user_id = uuid.uuid4()
                # Store username in a plain variable: after `tenant_db.close()` the SQLAlchemy instance
                # is detached and accessing attributes can raise DetachedInstanceError.
                admin_username = username.lower()
                admin_user = User(
                    id=admin_user_id,
                    email=email,
                    username=admin_username,
                    full_name=full_name,
                    phone=phone,
                    is_active=True,
                    is_pending=False,
                    password_set=True,
                    password_hash=password_hash,
                )
                tenant_db.add(admin_user)
                tenant_db.flush()

                # Ensure an admin role exists and assign it to HQ branch
                admin_role = (
                    tenant_db.query(UserRole)
                    .filter(UserRole.role_name == "admin")
                    .first()
                )
                if not admin_role:
                    admin_role = UserRole(role_name="admin", description="Demo admin")
                    tenant_db.add(admin_role)
                    tenant_db.flush()

                tenant_db.add(
                    UserBranchRole(
                        user_id=admin_user.id,
                        branch_id=hq_branch.id,
                        role_id=admin_role.id,
                    )
                )

                tenant_db.commit()
        except Exception:
            tenant_db.rollback()
            raise
        finally:
            tenant_db.close()

        if company_id is None:
            raise RuntimeError("Demo signup: company_id was not captured before creating tenant registry row.")

        now_prov = datetime.now(timezone.utc)
        dbname = f"pharmasight_{_sanitize_db_name(subdomain)}"
        if not admin_user_id:
            raise RuntimeError("Demo signup: admin_user_id was not set.")
        if not admin_username:
            raise RuntimeError("Demo signup: admin_username was not set.")
        tenant = create_and_commit_registry_tenant(
            master_db,
            company_id=company_id,
            company_name=org_norm,
            admin_email=email,
            subdomain=subdomain,
            database_url=database_url,
            database_name=dbname,
            admin_full_name=full_name,
            phone=phone,
            admin_user_id=admin_user_id,
            is_provisioned=True,
            provisioned_at=now_prov,
        )

        # Send setup invite email so the user has a clear "complete setup" direction
        # and so the invite can be re-sent later from the tenant admin page.
        _create_setup_invite_and_send(tenant, to_email=email, username=admin_username)

        # Issue authentication tokens (demo tenants use the app DB, so company_id from company we just created)
        company_id_str = str(company_id)
        access_token = create_access_token(str(admin_user_id), email, tenant_subdomain=subdomain, company_id=company_id_str)
        refresh_token = create_refresh_token(str(admin_user_id), email, tenant_subdomain=subdomain, company_id=company_id_str)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "tenant_id": str(tenant.id),
            "tenant_subdomain": tenant.subdomain,
            "username": admin_username,
            "user_id": str(admin_user_id),
            "email": email,
        }
    except Exception:
        master_db.rollback()
        raise
    finally:
        master_db.close()


__all__ = ["create_demo_tenant"]

