"""
Unified document number generation for the Transaction Engine.
Format: {DOC_TYPE}-{BRANCH_CODE}-{SEQUENCE}
Example: INV-01-000245, CN-01-000014, GRN-02-000099
Uses document_sequences with row-level locking (SELECT ... FOR UPDATE).
"""
from __future__ import annotations

from uuid import UUID
from sqlalchemy.orm import Session

from app.models import Branch, DocumentSequence


# Doc types for the unified format (used in document_sequences.document_type)
DOC_TYPE_INV = "INV"
DOC_TYPE_CN = "CN"
DOC_TYPE_GRN = "GRN"
DOC_TYPE_PR = "PR"
DOC_TYPE_TRF = "TRF"
DOC_TYPE_ADJ = "ADJ"
DOC_TYPE_OPEN = "OPEN"


def _branch_code_two_digit(branch: Branch) -> str:
    """Normalize branch code to two characters for document number (e.g. 01, 02)."""
    code = (branch.code or "").strip()
    if not code:
        return "01"
    if len(code) >= 2:
        return code[:2]
    if code.isdigit():
        return code.zfill(2)
    return code.ljust(2, "0")[:2]


class DocumentNumberService:
    """
    Generates standardized document numbers: {DOC_TYPE}-{BRANCH_CODE}-{SEQUENCE}.
    Uses document_sequences; row is locked with FOR UPDATE to avoid duplicates.
    """

    @staticmethod
    def get_next(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        doc_type: str,
    ) -> str:
        """
        Get next document number for (branch_id, doc_type).
        Locks the sequence row, increments, and returns formatted number.
        """
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise ValueError(f"Branch {branch_id} not found")
        branch_code = _branch_code_two_digit(branch)

        # Find or create sequence row (document_type = INV, CN, GRN, etc.; year NULL = unified format)
        seq = (
            db.query(DocumentSequence)
            .filter(
                DocumentSequence.company_id == company_id,
                DocumentSequence.branch_id == branch_id,
                DocumentSequence.document_type == doc_type,
                DocumentSequence.year.is_(None),
            )
            .with_for_update()
            .first()
        )
        if not seq:
            seq = DocumentSequence(
                company_id=company_id,
                branch_id=branch_id,
                document_type=doc_type,
                current_number=0,
                year=None,
            )
            db.add(seq)
            db.flush()
            # Reload with lock (same transaction)
            seq = (
                db.query(DocumentSequence)
                .filter(
                    DocumentSequence.company_id == company_id,
                    DocumentSequence.branch_id == branch_id,
                    DocumentSequence.document_type == doc_type,
                    DocumentSequence.year.is_(None),
                )
                .with_for_update()
                .first()
            )
            if not seq:
                raise ValueError(f"Failed to create sequence for {doc_type} at branch {branch_id}")

        seq.current_number = (seq.current_number or 0) + 1
        next_num = seq.current_number
        db.flush()

        return f"{doc_type}-{branch_code}-{next_num:06d}"
