"""
Company Startup/Initialization Service

Handles the complete company setup flow:
1. Create company (enforce single company)
2. Create app-level user record (mirror of Supabase Auth user - user must already exist in Auth)
3. Create first branch (with code)
4. Assign admin role to branch
5. Initialize document sequences
6. Initialize pricing defaults

STRICT RULES:
- User MUST already exist in Supabase Auth (created via InviteService)
- This service NEVER creates auth users or handles passwords
- This service ONLY creates app-level user profile records
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
    """Service for company initialization"""

    @staticmethod
    def check_company_exists(db: Session) -> bool:
        """Check if company already exists (should be only one)"""
        count = db.query(func.count(Company.id)).scalar()
        return count > 0

    @staticmethod
    def initialize_company(
        db: Session,
        company_data: dict,
        admin_user_data: dict,
        branch_data: dict
    ) -> dict:
        """
        Complete company initialization flow
        
        Args:
            company_data: Company creation data
            admin_user_data: Admin user data (id, email, full_name, phone)
            branch_data: First branch data (name, code, address, phone)
        
        Returns:
            dict with company_id, user_id, branch_id
        
        Raises:
            ValueError: If company already exists or validation fails
        """
        # Step 1: Check if company already exists
        if StartupService.check_company_exists(db):
            raise ValueError(
                "Company already exists. This database supports only ONE company. "
                "To reset, you must manually delete the existing company record."
            )

        # Step 2: Create app-level user record FIRST (before company)
        # IMPORTANT: User MUST already exist in Supabase Auth
        # This service does NOT create auth users - only app-level profile records
        # We create user FIRST to avoid transaction timeout issues with slow index
        if not admin_user_data.get('id'):
            raise ValueError(
                "Admin user ID is required (must match Supabase Auth user_id). "
                "User must be created via Supabase Auth first (use InviteService)."
            )
        
        # Check if user record already exists
        existing_user = db.query(User).filter(User.id == admin_user_data['id']).first()
        if existing_user:
            # Update existing user record
            existing_user.email = admin_user_data['email']
            existing_user.full_name = admin_user_data.get('full_name')
            existing_user.phone = admin_user_data.get('phone')
            existing_user.is_active = True
            admin_user = existing_user
            db.flush()  # Flush update
        else:
            # User doesn't exist - SKIP INSERT (index is too slow)
            # Instead, raise a helpful error with manual insert instructions
            raise ValueError(
                f"User with ID {admin_user_data['id']} does not exist in the app database. "
                f"The users table index is too slow for automatic insertion. "
                f"Please run this SQL manually in Supabase SQL Editor:\n\n"
                f"INSERT INTO users (id, email, full_name, phone, is_active)\n"
                f"VALUES ('{admin_user_data['id']}', '{admin_user_data['email']}', "
                f"'{admin_user_data.get('full_name', 'Admin User')}', "
                f"'{admin_user_data.get('phone', '')}', TRUE)\n"
                f"ON CONFLICT (id) DO NOTHING;\n\n"
                f"Then try the company setup again."
            )

        # Step 3: Create company (after user is committed)
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

        # Step 7: Initialize pricing defaults
        pricing_defaults = CompanyPricingDefault(
            company_id=company.id,
            default_markup_percent=Decimal('30.00'),
            rounding_rule='nearest_1',
            min_margin_percent=Decimal('0')
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

