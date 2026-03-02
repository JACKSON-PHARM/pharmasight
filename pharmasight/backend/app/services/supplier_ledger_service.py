"""
Supplier ledger service: single source of truth for supplier financial tracking.
All mutations must run inside the caller's transaction.
Debit = we owe supplier (invoice). Credit = we paid or credited (payment, return).
"""
from decimal import Decimal
from uuid import UUID
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import SupplierLedgerEntry


class SupplierLedgerService:
    @staticmethod
    def create_entry(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        supplier_id: UUID,
        entry_date: date,
        entry_type: str,  # invoice, payment, return, adjustment, opening_balance
        reference_id: UUID | None,
        debit: Decimal = Decimal("0"),
        credit: Decimal = Decimal("0"),
    ) -> SupplierLedgerEntry:
        """Append a ledger entry. Caller must be in a transaction."""
        entry = SupplierLedgerEntry(
            company_id=company_id,
            branch_id=branch_id,
            supplier_id=supplier_id,
            date=entry_date,
            entry_type=entry_type,
            reference_id=reference_id,
            debit=debit,
            credit=credit,
        )
        db.add(entry)
        db.flush()
        return entry

    @staticmethod
    def get_outstanding_balance(
        db: Session,
        supplier_id: UUID,
        company_id: UUID,
        branch_id: UUID | None = None,
        as_of_date: date | None = None,
    ) -> Decimal:
        """Sum of debits minus credits (positive = we owe). Optional branch and as_of_date filter."""
        q = db.query(
            func.coalesce(func.sum(SupplierLedgerEntry.debit), 0) - func.coalesce(func.sum(SupplierLedgerEntry.credit), 0)
        ).filter(
            SupplierLedgerEntry.supplier_id == supplier_id,
            SupplierLedgerEntry.company_id == company_id,
        )
        if branch_id is not None:
            q = q.filter(SupplierLedgerEntry.branch_id == branch_id)
        if as_of_date is not None:
            q = q.filter(SupplierLedgerEntry.date <= as_of_date)
        result = q.scalar()
        return Decimal(str(result)) if result is not None else Decimal("0")
