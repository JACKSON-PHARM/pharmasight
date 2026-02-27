"""
Company Startup/Initialization Service

Handles the complete company setup flow (single-DB multi-company):
- If no company exists: create first company, branch, assign user.
- If companies exist and user already has a branch role (e.g. from invite): complete setup for that company/branch.
- If companies exist and user has no branch role: create a new company and assign user (multi-company).
"""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID, uuid4
from decimal import Decimal
from datetime import date

from app.models import (
    Company, Branch, User, UserRole, UserBranchRole,
    CompanyPricingDefault, DocumentSequence
)


class StartupService:
    """Service for company initialization (supports multi-company)."""

    @staticmethod
    def check_company_exists(db: Session) -> bool:
        """Check if any company exists in the database."""
        count = db.query(func.count(Company.id)).scalar()
        return count > 0

    @staticmethod
    def _ensure_sequences_and_pricing(db: Session, company_id: UUID, branch_id: UUID) -> None:
        """Ensure document sequences and company pricing default exist for a company/branch."""
        current_year = date.today().year
        # Pricing default (one per company)
        has_pricing = db.query(CompanyPricingDefault).filter(
            CompanyPricingDefault.company_id == company_id
        ).first()
        if not has_pricing:
            db.add(CompanyPricingDefault(
                company_id=company_id,
                default_markup_percent=Decimal('30.00'),
                rounding_rule='nearest_1',
                min_margin_percent=Decimal('15.00')
            ))
            db.flush()
        # Document sequences for branch
        doc_types = [
            ('SALES_INVOICE', 'CS'), ('GRN', 'GRN'), ('CREDIT_NOTE', 'CN'), ('PAYMENT', 'PAY')
        ]
        for doc_type, prefix in doc_types:
            exists = db.query(DocumentSequence).filter(
                DocumentSequence.company_id == company_id,
                DocumentSequence.branch_id == branch_id,
                DocumentSequence.document_type == doc_type,
                DocumentSequence.year == current_year,
            ).first()
            if not exists:
                db.add(DocumentSequence(
                    company_id=company_id,
                    branch_id=branch_id,
                    document_type=doc_type,
                    prefix=prefix,
                    current_number=0,
                    year=current_year
                ))
        db.flush()

    @staticmethod
    def initialize_company(
        db: Session,
        company_data: dict,
        admin_user_data: dict,
        branch_data: dict
    ) -> dict:
        """
        Complete company initialization flow (multi-company safe).
        - No company in DB: create first company, branch, assign user.
        - User already has company/branch (e.g. from invite): ensure sequences/pricing, return existing.
        - Companies exist but user has none: create new company and branch for this user.
        """
        admin_user_id = admin_user_data.get('id')
        if not admin_user_id:
            raise ValueError(
                "Admin user ID is required (must match Supabase Auth user_id). "
                "User must be created via Supabase Auth first (use InviteService)."
            )

        # Resolve or create user record
        existing_user = db.query(User).filter(User.id == admin_user_id).first()
        if existing_user:
            existing_user.email = admin_user_data.get('email', existing_user.email)
            existing_user.full_name = admin_user_data.get('full_name') or existing_user.full_name
            existing_user.phone = admin_user_data.get('phone') or existing_user.phone
            existing_user.is_active = True
            admin_user = existing_user
            db.flush()
        else:
            raise ValueError(
                f"User with ID {admin_user_id} does not exist in the app database. "
                "Complete the invite setup first, then return to this page."
            )

        # If user already has a branch role (e.g. from invite completion), complete setup for that company/branch
        existing_ubr = db.query(UserBranchRole).filter(UserBranchRole.user_id == admin_user_id).first()
        if existing_ubr:
            branch = db.query(Branch).filter(Branch.id == existing_ubr.branch_id).first()
            company = db.query(Company).filter(Company.id == branch.company_id).first() if branch else None
            if company and branch:
                # Optionally update branch details from form
                if branch_data.get('name'):
                    branch.name = branch_data['name']
                if branch_data.get('address') is not None:
                    branch.address = branch_data.get('address')
                if branch_data.get('phone') is not None:
                    branch.phone = branch_data.get('phone')
                db.flush()
                StartupService._ensure_sequences_and_pricing(db, company.id, branch.id)
                db.commit()
                db.refresh(company)
                db.refresh(branch)
                return {
                    'company_id': str(company.id),
                    'user_id': str(admin_user.id),
                    'branch_id': str(branch.id),
                    'message': 'Company setup completed (you were already assigned to this company).'
                }

        # If at least one company exists but this user has no branch role, create a new company (multi-company)
        if StartupService.check_company_exists(db):
            # Create new company for this user
            company = Company(**company_data)
            db.add(company)
            db.flush()
            admin_role = db.query(UserRole).filter(UserRole.role_name == 'admin').first()
            if not admin_role:
                admin_role = UserRole(role_name='admin', description='Full system access')
                db.add(admin_role)
                db.flush()
            branch_code = (branch_data.get('code') or '').strip() or 'BR001'
            branch = Branch(
                company_id=company.id,
                name=branch_data.get('name') or company.name,
                code=branch_code.upper(),
                address=branch_data.get('address'),
                phone=branch_data.get('phone'),
                is_active=True,
                is_hq=True,
            )
            db.add(branch)
            db.flush()
            db.add(UserBranchRole(
                user_id=admin_user.id,
                branch_id=branch.id,
                role_id=admin_role.id
            ))
            db.add(CompanyPricingDefault(
                company_id=company.id,
                default_markup_percent=Decimal('30.00'),
                rounding_rule='nearest_1',
                min_margin_percent=Decimal('15.00')
            ))
            db.flush()
            current_year = date.today().year
            for doc_type, prefix in [('SALES_INVOICE', 'CS'), ('GRN', 'GRN'), ('CREDIT_NOTE', 'CN'), ('PAYMENT', 'PAY')]:
                db.add(DocumentSequence(
                    company_id=company.id,
                    branch_id=branch.id,
                    document_type=doc_type,
                    prefix=prefix,
                    current_number=0,
                    year=current_year
                ))
            db.commit()
            db.refresh(company)
            db.refresh(branch)
            return {
                'company_id': str(company.id),
                'user_id': str(admin_user.id),
                'branch_id': str(branch.id),
                'message': 'Company initialization completed successfully'
            }

        # No company exists: create first company, branch, and assign user
        # (admin_user already resolved above)
        # Step 3: Create company
        company = Company(**company_data)
        db.add(company)
        db.flush()  # Get company.id

        # Step 4: Get or create admin role
        admin_role = db.query(UserRole).filter(UserRole.role_name == 'admin').first()
        if not admin_role:
            # Auto-create admin role if missing (for development)
            admin_role = UserRole(
                role_name='admin',
                description='Full system access'
            )
            db.add(admin_role)
            db.flush()
            # Also create other common roles if they don't exist
            for role_name, description in [
                ('pharmacist', 'Can sell, purchase, view reports'),
                ('cashier', 'Can sell only'),
                ('procurement', 'Can purchase and view inventory'),
                ('viewer', 'Read-only access')
            ]:
                existing = db.query(UserRole).filter(UserRole.role_name == role_name).first()
                if not existing:
                    db.add(UserRole(role_name=role_name, description=description))
            db.flush()

        # Step 5: Create first branch (Auto-generate code if first branch)
        # Check if this is the first branch for this company
        branch_count = db.query(func.count(Branch.id)).filter(Branch.company_id == company.id).scalar()
        
        if not branch_data.get('code') or branch_data.get('code', '').strip() == '':
            # Auto-generate branch code: BR001 for first branch, BR002 for second, etc.
            # Since we just created the company, this should be the first branch
            branch_code = "BR001"
            
            # Double-check: if somehow branches exist, find next available number
            if branch_count > 0:
                # Get existing branch codes with BR prefix
                from sqlalchemy import func as sql_func
                existing_branches = db.query(Branch.code).filter(
                    Branch.company_id == company.id,
                    Branch.code.like('BR%')
                ).all()
                
                # Find highest number
                max_num = 0
                for (code,) in existing_branches:
                    if code and len(code) > 2 and code[:2].upper() == 'BR':
                        try:
                            num_str = code[2:].lstrip('0') or '0'  # Remove leading zeros
                            num = int(num_str)
                            max_num = max(max_num, num)
                        except ValueError:
                            pass
                
                branch_code = f"BR{str(max_num + 1).zfill(3)}"
        else:
            branch_code = branch_data['code'].strip().upper()
        
        branch = Branch(
            company_id=company.id,
            name=branch_data['name'],
            code=branch_code,
            address=branch_data.get('address'),
            phone=branch_data.get('phone'),
            is_active=True
        )
        db.add(branch)
        db.flush()

        # Step 6: Assign admin role to branch
        user_branch_role = UserBranchRole(
            user_id=admin_user.id,
            branch_id=branch.id,
            role_id=admin_role.id
        )
        db.add(user_branch_role)

        # Step 7: Initialize pricing defaults (recommended markup 30%, minimum margin 15%)
        pricing_defaults = CompanyPricingDefault(
            company_id=company.id,
            default_markup_percent=Decimal('30.00'),
            rounding_rule='nearest_1',
            min_margin_percent=Decimal('15.00')
        )
        db.add(pricing_defaults)

        # Step 8: Initialize document sequences for the branch
        current_year = date.today().year
        
        document_types = ['SALES_INVOICE', 'GRN', 'CREDIT_NOTE', 'PAYMENT']
        for doc_type in document_types:
            # Simplified prefix based on document type initials
            # Format: CS001 (Cash Sale), CN001 (Credit Note), etc.
            if doc_type == 'SALES_INVOICE':
                prefix = "CS"  # Cash Sale
            elif doc_type == 'GRN':
                prefix = "GRN"
            elif doc_type == 'CREDIT_NOTE':
                prefix = "CN"  # Credit Note
            elif doc_type == 'PAYMENT':
                prefix = "PAY"
            else:
                prefix = doc_type

            sequence = DocumentSequence(
                company_id=company.id,
                branch_id=branch.id,
                document_type=doc_type,
                prefix=prefix,
                current_number=0,
                year=current_year
            )
            db.add(sequence)

        # Commit everything
        try:
            db.commit()
            db.refresh(company)
            db.refresh(admin_user)
            db.refresh(branch)
            
            return {
                'company_id': str(company.id),
                'user_id': str(admin_user.id),
                'branch_id': str(branch.id),
                'message': 'Company initialization completed successfully'
            }
        except Exception as e:
            db.rollback()
            raise ValueError(f"Error during company initialization: {str(e)}")

    @staticmethod
    def get_company_id(db: Session) -> Optional[UUID]:
        """Get the single company ID (helper for ONE COMPANY architecture)"""
        company = db.query(Company).first()
        return company.id if company else None

