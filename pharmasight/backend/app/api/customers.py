"""
Wholesale customers API (B2B master data)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List
from uuid import UUID

from app.dependencies import get_tenant_db, get_current_user
from app.module_enforcement import require_module
from app.utils.wholesale_branch_context import require_wholesale_distribution_branch
from app.models import (
    Customer,
    SalesInvoice,
    CustomerPayment,
    CustomerLedgerEntry,
    Quotation,
    CustomerActivity,
    CustomerUser,
)
from app.schemas.customer import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerMergeRequest,
)

router = APIRouter(
    dependencies=[
        Depends(require_module("wholesale")),
        Depends(require_wholesale_distribution_branch()),
    ]
)


@router.get("/search")
def search_customers(
    q: str = Query(..., min_length=2),
    company_id: UUID = Query(...),
    limit: int = Query(10, ge=1, le=20),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    search_term = f"%{q.lower()}%"
    rows = (
        db.query(Customer.id, Customer.name)
        .filter(
            Customer.company_id == company_id,
            Customer.is_active == True,
            or_(
                func.lower(Customer.name).like(search_term),
                func.lower(Customer.contact_person).like(search_term),
                func.lower(Customer.phone).like(search_term),
            ),
        )
        .order_by(Customer.name.asc())
        .limit(limit)
        .all()
    )
    return [{"id": str(r.id), "name": r.name} for r in rows]


@router.get("/company/{company_id}", response_model=List[CustomerResponse])
def list_customers(
    company_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    return (
        db.query(Customer)
        .filter(Customer.company_id == company_id, Customer.is_active == True)
        .order_by(Customer.name)
        .all()
    )


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    customer: CustomerCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    name_key = (customer.name or "").strip().lower()
    if name_key:
        dup = (
            db.query(Customer)
            .filter(
                Customer.company_id == customer.company_id,
                func.lower(func.trim(Customer.name)) == name_key,
            )
            .first()
        )
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A customer named '{dup.name}' already exists for this company.",
            )

    db_customer = Customer(
        company_id=customer.company_id,
        name=customer.name,
        pin=customer.pin,
        contact_person=customer.contact_person,
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        city=customer.city,
        county=customer.county,
        customer_type=customer.customer_type or "PHARMACY",
        default_payment_terms_days=customer.default_payment_terms_days,
        credit_limit=customer.credit_limit,
        allow_over_credit=customer.allow_over_credit or False,
        credit_enabled=customer.credit_enabled if customer.credit_enabled is not None else True,
        default_sales_type=customer.default_sales_type or "WHOLESALE",
        opening_balance=customer.opening_balance or 0,
        notes=customer.notes,
        portal_enabled=bool(customer.portal_enabled),
    )
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


@router.get("/{customer_id}/portal-users")
def list_customer_portal_users(
    customer_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Phase 5 foundation: list B2B portal identities for a customer.
  Full invite/login flows are not implemented yet.
    """
    effective = getattr(request.state, "effective_company_id", None)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if effective is not None and customer.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    rows = (
        db.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer_id, CustomerUser.company_id == customer.company_id)
        .order_by(CustomerUser.email.asc())
        .all()
    )
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "is_active": u.is_active,
            "portal_enabled": customer.portal_enabled,
            "invited_at": u.invited_at.isoformat() if u.invited_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "auth_user_id": str(u.auth_user_id) if u.auth_user_id else None,
        }
        for u in rows
    ]


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.put("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: UUID,
    customer: CustomerUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    db_customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not db_customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    data = customer.model_dump(exclude_unset=True)
    for key, value in data.items():
        if hasattr(db_customer, key):
            setattr(db_customer, key, value)
    db.commit()
    db.refresh(db_customer)
    return db_customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    effective = getattr(request.state, "effective_company_id", None)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if effective is not None and customer.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    inv_c = db.query(SalesInvoice).filter(SalesInvoice.customer_id == customer_id).count()
    pay_c = db.query(CustomerPayment).filter(CustomerPayment.customer_id == customer_id).count()
    led_c = db.query(CustomerLedgerEntry).filter(CustomerLedgerEntry.customer_id == customer_id).count()
    quo_c = db.query(Quotation).filter(Quotation.customer_id == customer_id).count()
    act_c = db.query(CustomerActivity).filter(CustomerActivity.customer_id == customer_id).count()

    if inv_c or pay_c or led_c or quo_c or act_c:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This customer has related documents.",
                "counts": {
                    "invoices": inv_c,
                    "payments": pay_c,
                    "ledger_entries": led_c,
                    "quotations": quo_c,
                    "activities": act_c,
                },
            },
        )

    db.delete(customer)
    db.commit()
    return None


@router.post("/merge")
def merge_customers(
    request: Request,
    merge: CustomerMergeRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    effective = getattr(request.state, "effective_company_id", None)
    from_id = merge.from_customer_id
    to_id = merge.to_customer_id
    if str(from_id) == str(to_id):
        raise HTTPException(status_code=400, detail="Cannot merge a customer into itself")

    from_c = db.query(Customer).filter(Customer.id == from_id).first()
    to_c = db.query(Customer).filter(Customer.id == to_id).first()
    if not from_c or not to_c:
        raise HTTPException(status_code=404, detail="Customer not found")
    if from_c.company_id != to_c.company_id:
        raise HTTPException(status_code=400, detail="Customers must belong to the same company")
    if effective is not None and from_c.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    try:
        db.query(SalesInvoice).filter(SalesInvoice.customer_id == from_id).update(
            {SalesInvoice.customer_id: to_id}, synchronize_session=False
        )
        db.query(Quotation).filter(Quotation.customer_id == from_id).update(
            {Quotation.customer_id: to_id}, synchronize_session=False
        )
        db.query(CustomerPayment).filter(CustomerPayment.customer_id == from_id).update(
            {CustomerPayment.customer_id: to_id}, synchronize_session=False
        )
        db.query(CustomerLedgerEntry).filter(CustomerLedgerEntry.customer_id == from_id).update(
            {CustomerLedgerEntry.customer_id: to_id, CustomerLedgerEntry.running_balance: None},
            synchronize_session=False,
        )
        db.query(CustomerActivity).filter(CustomerActivity.customer_id == from_id).update(
            {CustomerActivity.customer_id: to_id}, synchronize_session=False
        )
        db.delete(from_c)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "company_id": str(from_c.company_id),
        "from_customer_id": str(from_id),
        "to_customer_id": str(to_id),
        "deleted_source": True,
    }
