"""
Document Numbering Service - KRA Compliant Sequential Numbering
"""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, extract
from datetime import date
from uuid import UUID
from app.models import Company, Branch, DocumentSequence
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
        
        Uses database function that ENFORCES branch code in invoice numbers.
        Format: {BRANCH_CODE}-{TYPE}-YYYY-000001
        
        Args:
            company_id: Company ID
            branch_id: Branch ID (must have a code)
            document_type: SALES_INVOICE, GRN, CREDIT_NOTE, PAYMENT, SUPPLIER_INVOICE
            prefix: Optional prefix (will be ignored - branch code is required)
        
        Returns:
            str: Next document number with branch code (e.g., "MAIN-INV-2026-000001")
        
        Raises:
            ValueError: If branch code is missing
        """
        from sqlalchemy import text
        
        # Use database function that enforces branch code
        # Note: Use CAST() instead of ::UUID to avoid SQLAlchemy parameter parsing issues
        sql = text("""
            SELECT get_next_document_number(
                CAST(:company_id AS UUID),
                CAST(:branch_id AS UUID),
                :document_type,
                :prefix
            )
        """)
        
        result = db.execute(
            sql,
            {
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "document_type": document_type,
                "prefix": prefix
            }
        )
        
        document_number = result.scalar()
        
        if not document_number:
            raise ValueError(f"Failed to generate document number. Ensure branch has a code.")
        
        return document_number

    @staticmethod
    def get_sales_invoice_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get next sales invoice number
        
        Format: CS001 (Cash Sale), CS002, etc.
        Branch-specific sequence.
        """
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "SALES_INVOICE", None
        )

    @staticmethod
    def get_grn_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get next GRN number
        
        Format: GRN001, GRN002, etc.
        Branch-specific sequence.
        """
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "GRN", None
        )
    
    @staticmethod
    def get_purchase_order_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get next Purchase Order number
        
        Format: PO{BRANCH_CODE}-000001, PO{BRANCH_CODE}-000002, etc.
        Branch-specific sequence.
        """
        # Get branch code
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch or not branch.code:
            raise ValueError("Branch code is required for purchase order numbering")
        
        # Get next sequence number for this branch
        from app.models import DocumentSequence
        from sqlalchemy import func
        
        # Find or create sequence for this branch and document type
        sequence = db.query(DocumentSequence).filter(
            DocumentSequence.company_id == company_id,
            DocumentSequence.branch_id == branch_id,
            DocumentSequence.document_type == "PURCHASE_ORDER"
        ).first()
        
        if not sequence:
            sequence = DocumentSequence(
                company_id=company_id,
                branch_id=branch_id,
                document_type="PURCHASE_ORDER",
                current_number=0
            )
            db.add(sequence)
            db.flush()
        
        # Increment and return
        sequence.current_number += 1
        db.commit()
        
        return f"PO{branch.code}-{sequence.current_number:06d}"
    
    @staticmethod
    def get_supplier_invoice_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get next Supplier Invoice number
        
        Format: SUP-INV001, SUP-INV002, etc.
        Branch-specific sequence.
        """
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "SUPPLIER_INVOICE", None
        )

    @staticmethod
    def get_credit_note_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get next credit note number
        
        Format: CN001 (Credit Note), CN002, etc.
        Branch-specific sequence.
        """
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "CREDIT_NOTE", None
        )

    @staticmethod
    def get_payment_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get next payment number
        
        Format: {BRANCH_CODE}-PAY-YYYY-000001
        Branch code is REQUIRED and enforced by database function.
        """
        return DocumentService.get_next_document_number(
            db, company_id, branch_id, "PAYMENT", None
        )
    
    @staticmethod
    def get_quotation_number(
        db: Session,
        company_id: UUID,
        branch_id: UUID
    ) -> str:
        """
        Get next quotation number
        
        Format: QT001 (Quotation), QT002, etc.
        Branch-specific sequence.
        """
        # Get branch code
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch or not branch.code:
            raise ValueError("Branch code is required for quotation numbering")
        
        # Get next sequence number for this branch
        from app.models import DocumentSequence
        
        # Find or create sequence for this branch and document type
        sequence = db.query(DocumentSequence).filter(
            DocumentSequence.company_id == company_id,
            DocumentSequence.branch_id == branch_id,
            DocumentSequence.document_type == "QUOTATION"
        ).first()
        
        if not sequence:
            sequence = DocumentSequence(
                company_id=company_id,
                branch_id=branch_id,
                document_type="QUOTATION",
                current_number=0
            )
            db.add(sequence)
            db.flush()
        
        # Increment and get next number
        sequence.current_number += 1
        db.commit()
        
        # Format: QT{BRANCH_CODE}-{6-digit number}
        return f"QT{branch.code}-{sequence.current_number:06d}"

