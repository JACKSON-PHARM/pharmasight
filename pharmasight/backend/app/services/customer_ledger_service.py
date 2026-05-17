"""Customer AR ledger: debit = customer owes us, credit = payment/credit note."""
from decimal import Decimal
from uuid import UUID
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.customer_financial import CustomerLedgerEntry


class CustomerLedgerService:
    @staticmethod
    def create_entry(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        customer_id: UUID,
        entry_date: date,
        entry_type: str,
        reference_id: UUID | None,
        debit: Decimal = Decimal("0"),
        credit: Decimal = Decimal("0"),
    ) -> CustomerLedgerEntry:
        entry = CustomerLedgerEntry(
            company_id=company_id,
            branch_id=branch_id,
            customer_id=customer_id,
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
        customer_id: UUID,
        company_id: UUID,
        branch_id: UUID | None = None,
        as_of_date: date | None = None,
    ) -> Decimal:
        q = db.query(
            func.coalesce(func.sum(CustomerLedgerEntry.debit), 0)
            - func.coalesce(func.sum(CustomerLedgerEntry.credit), 0)
        ).filter(
            CustomerLedgerEntry.customer_id == customer_id,
            CustomerLedgerEntry.company_id == company_id,
        )
        if branch_id is not None:
            q = q.filter(CustomerLedgerEntry.branch_id == branch_id)
        if as_of_date is not None:
            q = q.filter(CustomerLedgerEntry.date <= as_of_date)
        result = q.scalar()
        return Decimal(str(result)) if result is not None else Decimal("0")
