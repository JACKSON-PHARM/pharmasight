"""
Document Numbering Service - KRA Compliant Sequential Numbering
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_, extract
from datetime import date
from uuid import UUID
from app.models import Company, Branch
from app.database import SessionLocal


class DocumentService:
    """Service for generating KRA-compliant document numbers"""

    @staticmethod
    def get_next_document_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        document_type: str,
        prefix: Optional[str] = None
    ) -> str:
        """
        Get next sequential document number (KRA compliant)
        
        Args:
            company_id: Company ID
            branch_id: Branch ID
            document_type: SALES_INVOICE, GRN, CREDIT_NOTE, PAYMENT
            prefix: Optional prefix (e.g., "INV", "GRN")
        
        Returns:
            str: Next document number (e.g., "INV-000001" or "000001")
        """
        current_year = date.today().year
        
        # Use raw SQL for atomic increment (better than ORM for this)
        from sqlalchemy import text
        
        # Insert or update sequence
        sql = text("""
            INSERT INTO document_sequences 
                (company_id, branch_id, document_type, prefix, current_number, year)
            VALUES 
                (:company_id, :branch_id, :document_type, :prefix, 0, :year)
            ON CONFLICT (company_id, branch_id, document_type, year)
            DO UPDATE SET 
                current_number = document_sequences.current_number + 1
            RETURNING current_number
        """)
        
        result = db.execute(
            sql,
            {
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "document_type": document_type,
                "prefix": prefix,
                "year": current_year
            }
        )
        
        next_number = result.scalar()
        
        # Format document number
        if prefix:
            return f"{prefix}-{str(next_number).zfill(6)}"
        else:
            return str(next_number).zfill(6)

    @staticmethod
    def get_sales_invoice_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """Get next sales invoice number"""
        # Get company/branch prefix if configured
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        prefix = branch.code if branch and branch.code else "INV"
        
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "SALES_INVOICE", prefix
        )

    @staticmethod
    def get_grn_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """Get next GRN number"""
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        prefix = "GRN"
        if branch and branch.code:
            prefix = f"{branch.code}-GRN"
        
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "GRN", prefix
        )

    @staticmethod
    def get_credit_note_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """Get next credit note number"""
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        prefix = "CN"
        if branch and branch.code:
            prefix = f"{branch.code}-CN"
        
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "CREDIT_NOTE", prefix
        )

    @staticmethod
    def get_payment_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """Get next payment number"""
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        prefix = "PAY"
        if branch and branch.code:
            prefix = f"{branch.code}-PAY"
        
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "PAYMENT", prefix
        )

