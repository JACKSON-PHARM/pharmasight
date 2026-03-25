"""
Expenses API (OPEX only).

Rules:
- Expenses are always operational (OPEX); no stock or supplier linkage.
- Approval workflow: if amount > threshold => pending else approved.
- Only approved expenses affect reports.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, List, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db, _user_has_permission, get_effective_company_id_for_user
from app.models import Expense, ExpenseCategory
from app.models.settings import CompanySetting
from app.schemas.expense import (
    ExpenseCategoryCreate,
    ExpenseCategoryUpdate,
    ExpenseCategoryResponse,
    ExpenseCreate,
    ExpenseUpdate,
    ExpenseResponse,
    ExpenseSummaryResponse,
    ExpenseDailyRow,
)

router = APIRouter()


def _effective_company_id(request: Request, db: Session, user) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


def _expense_threshold(db: Session, company_id: UUID) -> Decimal:
    row = (
        db.query(CompanySetting)
        .filter(CompanySetting.company_id == company_id, CompanySetting.setting_key == "expense_approval_threshold")
        .first()
    )
    if not row or not (row.setting_value or "").strip():
        return Decimal("500")
    try:
        return Decimal(str(row.setting_value).strip())
    except Exception:
        return Decimal("500")


def _normalize_payment_mode(v: str) -> str:
    m = (v or "").strip().lower()
    if m not in ("cash", "mpesa", "bank"):
        raise HTTPException(status_code=400, detail="payment_mode must be one of: cash, mpesa, bank")
    return m


# ---------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------
@router.get("/categories", response_model=List[ExpenseCategoryResponse])
def list_categories(
    request: Request,
    include_inactive: bool = Query(False),
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.view"):
        raise HTTPException(status_code=403, detail="Permission expenses.view required")
    company_id = _effective_company_id(request, db, user)
    q = db.query(ExpenseCategory).filter(ExpenseCategory.company_id == company_id)
    if not include_inactive:
        q = q.filter(ExpenseCategory.is_active.is_(True))
    return q.order_by(func.lower(func.trim(ExpenseCategory.name)).asc()).all()


@router.post("/categories", response_model=ExpenseCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    request: Request,
    body: ExpenseCategoryCreate,
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.create"):
        raise HTTPException(status_code=403, detail="Permission expenses.create required")
    company_id = _effective_company_id(request, db, user)
    if str(body.company_id) != str(company_id):
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    name_key = (body.name or "").strip()
    if not name_key:
        raise HTTPException(status_code=400, detail="Category name required")
    dup = (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.company_id == company_id, func.lower(func.trim(ExpenseCategory.name)) == name_key.lower())
        .first()
    )
    if dup:
        raise HTTPException(status_code=409, detail=f"Category '{dup.name}' already exists")

    cat = ExpenseCategory(
        company_id=company_id,
        name=name_key,
        description=body.description,
        is_active=bool(body.is_active) if body.is_active is not None else True,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.put("/categories/{category_id}", response_model=ExpenseCategoryResponse)
def update_category(
    request: Request,
    category_id: UUID,
    body: ExpenseCategoryUpdate,
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.edit"):
        raise HTTPException(status_code=403, detail="Permission expenses.edit required")
    company_id = _effective_company_id(request, db, user)

    cat = db.query(ExpenseCategory).filter(ExpenseCategory.id == category_id).first()
    if not cat or str(cat.company_id) != str(company_id):
        raise HTTPException(status_code=404, detail="Category not found")

    if body.name is not None:
        name_key = body.name.strip()
        if not name_key:
            raise HTTPException(status_code=400, detail="Category name required")
        dup = (
            db.query(ExpenseCategory)
            .filter(
                ExpenseCategory.company_id == company_id,
                func.lower(func.trim(ExpenseCategory.name)) == name_key.lower(),
                ExpenseCategory.id != category_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail=f"Category '{dup.name}' already exists")
        cat.name = name_key
    if body.description is not None:
        cat.description = body.description
    if body.is_active is not None:
        cat.is_active = bool(body.is_active)

    db.commit()
    db.refresh(cat)
    return cat


# ---------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------
@router.get("", response_model=List[ExpenseResponse])
def list_expenses(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.view"):
        raise HTTPException(status_code=403, detail="Permission expenses.view required")
    company_id = _effective_company_id(request, db, user)

    q = db.query(Expense).filter(Expense.company_id == company_id)
    if branch_id:
        q = q.filter(Expense.branch_id == branch_id)
    if date_from:
        q = q.filter(Expense.expense_date >= date_from)
    if date_to:
        q = q.filter(Expense.expense_date <= date_to)
    if status_filter:
        q = q.filter(Expense.status == status_filter)

    rows = (
        q.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Attach category_name in response for UI
    cat_ids = list({r.category_id for r in rows if r.category_id})
    cats = (
        db.query(ExpenseCategory.id, ExpenseCategory.name)
        .filter(ExpenseCategory.id.in_(cat_ids))
        .all()
        if cat_ids
        else []
    )
    cat_map = {c.id: c.name for c in cats}

    out: List[ExpenseResponse] = []
    for r in rows:
        d = ExpenseResponse.model_validate(r)
        d.category_name = cat_map.get(r.category_id)
        out.append(d)
    return out


@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(
    request: Request,
    body: ExpenseCreate,
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.create"):
        raise HTTPException(status_code=403, detail="Permission expenses.create required")
    company_id = _effective_company_id(request, db, user)
    if str(body.company_id) != str(company_id):
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    if not body.branch_id:
        raise HTTPException(status_code=400, detail="branch_id required")

    # Category must exist + active
    cat = (
        db.query(ExpenseCategory)
        .filter(ExpenseCategory.id == body.category_id, ExpenseCategory.company_id == company_id)
        .first()
    )
    if not cat:
        raise HTTPException(status_code=404, detail="Expense category not found")
    if getattr(cat, "is_active", True) is False:
        raise HTTPException(status_code=400, detail="Expense category is inactive")

    payment_mode = _normalize_payment_mode(body.payment_mode)
    amount = Decimal(str(body.amount))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    threshold = _expense_threshold(db, company_id)
    status_val = "pending" if amount > threshold else "approved"
    now = datetime.now(timezone.utc)

    exp = Expense(
        company_id=company_id,
        branch_id=body.branch_id,
        category_id=body.category_id,
        description=(body.description or "").strip(),
        amount=amount,
        expense_date=body.expense_date,
        payment_mode=payment_mode,
        reference_number=(body.reference_number or None),
        attachment_url=(body.attachment_url or None),
        status=status_val,
        created_by=user.id,
        approved_by=(user.id if status_val == "approved" else None),
        approved_at=(now if status_val == "approved" else None),
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)

    out = ExpenseResponse.model_validate(exp)
    out.category_name = cat.name
    return out


@router.put("/{expense_id}", response_model=ExpenseResponse)
def update_expense(
    request: Request,
    expense_id: UUID,
    body: ExpenseUpdate,
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.edit"):
        raise HTTPException(status_code=403, detail="Permission expenses.edit required")
    company_id = _effective_company_id(request, db, user)

    exp = db.query(Expense).filter(Expense.id == expense_id).first()
    if not exp or str(exp.company_id) != str(company_id):
        raise HTTPException(status_code=404, detail="Expense not found")
    if exp.status == "approved":
        raise HTTPException(status_code=400, detail="Approved expenses cannot be edited")

    if body.category_id is not None:
        cat = (
            db.query(ExpenseCategory)
            .filter(ExpenseCategory.id == body.category_id, ExpenseCategory.company_id == company_id)
            .first()
        )
        if not cat:
            raise HTTPException(status_code=404, detail="Expense category not found")
        if getattr(cat, "is_active", True) is False:
            raise HTTPException(status_code=400, detail="Expense category is inactive")
        exp.category_id = body.category_id

    if body.description is not None:
        exp.description = body.description.strip()
    if body.amount is not None:
        amt = Decimal(str(body.amount))
        if amt <= 0:
            raise HTTPException(status_code=400, detail="Amount must be > 0")
        exp.amount = amt
    if body.expense_date is not None:
        exp.expense_date = body.expense_date
    if body.payment_mode is not None:
        exp.payment_mode = _normalize_payment_mode(body.payment_mode)
    if body.reference_number is not None:
        exp.reference_number = body.reference_number or None
    if body.attachment_url is not None:
        exp.attachment_url = body.attachment_url or None

    db.commit()
    db.refresh(exp)

    cat_name = (
        db.query(ExpenseCategory.name)
        .filter(ExpenseCategory.id == exp.category_id)
        .scalar()
    )
    out = ExpenseResponse.model_validate(exp)
    out.category_name = cat_name
    return out


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    request: Request,
    expense_id: UUID,
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.delete"):
        raise HTTPException(status_code=403, detail="Permission expenses.delete required")
    company_id = _effective_company_id(request, db, user)
    exp = db.query(Expense).filter(Expense.id == expense_id).first()
    if not exp or str(exp.company_id) != str(company_id):
        raise HTTPException(status_code=404, detail="Expense not found")
    if exp.status == "approved":
        raise HTTPException(status_code=400, detail="Approved expenses cannot be deleted")
    db.delete(exp)
    db.commit()
    return None


@router.patch("/{expense_id}/approve", response_model=ExpenseResponse)
def approve_expense(
    request: Request,
    expense_id: UUID,
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "expenses.edit"):
        raise HTTPException(status_code=403, detail="Permission expenses.edit required")
    company_id = _effective_company_id(request, db, user)
    exp = db.query(Expense).filter(Expense.id == expense_id).first()
    if not exp or str(exp.company_id) != str(company_id):
        raise HTTPException(status_code=404, detail="Expense not found")
    if exp.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending expenses can be approved")

    exp.status = "approved"
    exp.approved_by = user.id
    exp.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exp)

    cat_name = (
        db.query(ExpenseCategory.name)
        .filter(ExpenseCategory.id == exp.category_id)
        .scalar()
    )
    out = ExpenseResponse.model_validate(exp)
    out.category_name = cat_name
    return out


# ---------------------------------------------------------------------
# Reports (approved only)
# ---------------------------------------------------------------------
@router.get("/summary", response_model=ExpenseSummaryResponse)
def get_expense_summary(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    start_date: date = Query(...),
    end_date: date = Query(...),
    include_breakdown: bool = Query(True),
    user_db: Tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = user_db
    if not _user_has_permission(db, user.id, "reports.view"):
        raise HTTPException(status_code=403, detail="Permission reports.view required")
    company_id = _effective_company_id(request, db, user)
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be <= end_date")

    q = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
        Expense.company_id == company_id,
        Expense.status == "approved",
        Expense.expense_date >= start_date,
        Expense.expense_date <= end_date,
    )
    if branch_id:
        q = q.filter(Expense.branch_id == branch_id)
    total = q.scalar() or Decimal("0")

    breakdown: List[ExpenseDailyRow] = []
    if include_breakdown:
        qb = db.query(
            Expense.expense_date.label("d"),
            func.coalesce(func.sum(Expense.amount), 0).label("total"),
        ).filter(
            Expense.company_id == company_id,
            Expense.status == "approved",
            Expense.expense_date >= start_date,
            Expense.expense_date <= end_date,
        )
        if branch_id:
            qb = qb.filter(Expense.branch_id == branch_id)
        rows = qb.group_by(Expense.expense_date).order_by(Expense.expense_date.asc()).all()
        breakdown = [ExpenseDailyRow(date=r.d, total_expenses=r.total) for r in rows]

    return ExpenseSummaryResponse(
        branch_id=branch_id,
        start_date=start_date,
        end_date=end_date,
        total_expenses=total,
        breakdown=breakdown,
    )

