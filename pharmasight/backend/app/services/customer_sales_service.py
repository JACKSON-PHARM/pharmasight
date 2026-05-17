"""Apply wholesale customer to sales documents and enforce credit on batch."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.sale import SalesInvoice
from app.services.customer_ledger_service import CustomerLedgerService


def apply_customer_to_invoice(db: Session, invoice: SalesInvoice, customer_id: UUID | None, company_id: UUID) -> None:
    if not customer_id:
        return
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.company_id == company_id, Customer.is_active == True)
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    invoice.customer_id = customer.id
    invoice.customer_name = customer.name
    invoice.customer_pin = customer.pin
    invoice.customer_phone = customer.phone
    if customer.default_sales_type:
        invoice.sales_type = customer.default_sales_type


def set_due_date_from_customer(invoice: SalesInvoice, customer: Customer | None) -> None:
    if invoice.due_date:
        return
    days = 0
    if customer and customer.default_payment_terms_days is not None:
        days = int(customer.default_payment_terms_days)
    if days > 0 and invoice.invoice_date:
        invoice.due_date = invoice.invoice_date + timedelta(days=days)


def assert_customer_credit_for_batch(
    db: Session,
    invoice: SalesInvoice,
    customer: Customer,
    company_id: UUID,
    branch_id: UUID,
) -> None:
    if not customer.credit_enabled:
        return
    limit = customer.credit_limit
    if limit is None:
        return
    outstanding = CustomerLedgerService.get_outstanding_balance(
        db, customer.id, company_id, branch_id=branch_id
    )
    new_total = Decimal(str(invoice.total_inclusive or 0))
    projected = outstanding + new_total
    if projected > Decimal(str(limit)) and not (customer.allow_over_credit or False):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Credit limit exceeded for {customer.name}. "
                f"Outstanding {outstanding}, invoice {new_total}, limit {limit}."
            ),
        )


def post_customer_ledger_on_batch(
    db: Session,
    invoice: SalesInvoice,
    customer: Customer,
    company_id: UUID,
) -> None:
    """Debit AR when batched invoice has customer and unsettled balance."""
    total = Decimal(str(invoice.total_inclusive or 0))
    if total <= 0:
        return
    from app.services.customer_invoice_payment_service import total_settled_on_invoice

    settled = total_settled_on_invoice(db, invoice)
    balance = total - settled
    if balance <= 0:
        return
    CustomerLedgerService.create_entry(
        db,
        company_id=company_id,
        branch_id=invoice.branch_id,
        customer_id=customer.id,
        entry_date=invoice.invoice_date,
        entry_type="invoice",
        reference_id=invoice.id,
        debit=balance,
        credit=Decimal("0"),
    )
