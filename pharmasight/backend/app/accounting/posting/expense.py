"""GL posting for approved expenses."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.company_settings import expense_category_account_map
from app.accounting.constants import CONTROL_AP, CONTROL_CASH, CONTROL_EXPENSE
from app.accounting.coa_service import control_account_map, resolve_control_account
from app.accounting.posting.cash_account import resolve_cash_line_account
from app.accounting.posting.engine import post_journal_for_operation
from app.accounting.posting.types import PostingLineSpec, PostingResult
from app.models.accounting import ChartOfAccount
from app.models.expense import Expense

SOURCE_EXPENSE = "expense"
KIND_EXPENSE = "expense"


def _money(v) -> Decimal:
    return Decimal(str(v or 0))


def _resolve_expense_account_id(db: Session, company_id: UUID, category_id: UUID) -> UUID:
    mapping = expense_category_account_map(db, company_id)
    mapped = mapping.get(str(category_id))
    if mapped:
        row = (
            db.query(ChartOfAccount)
            .filter(
                ChartOfAccount.id == UUID(str(mapped)),
                ChartOfAccount.company_id == company_id,
                ChartOfAccount.is_active.is_(True),
            )
            .first()
        )
        if row:
            return row.id
    return resolve_control_account(db, company_id, CONTROL_EXPENSE).id


def _credit_is_ap(expense: Expense) -> bool:
    pm = (expense.payment_mode or "").strip().lower()
    return pm in ("credit", "on_credit", "ap")


def post_gl_for_expense_approved(
    db: Session,
    expense: Expense,
    *,
    posted_by: Optional[UUID],
) -> PostingResult:
    amount = _money(expense.amount)
    if amount <= 0:
        return PostingResult(False, None, "zero_amount")
    accounts = control_account_map(db, expense.company_id)
    expense_acct_id = _resolve_expense_account_id(db, expense.company_id, expense.category_id)
    if _credit_is_ap(expense):
        credit_acct_id = accounts[CONTROL_AP].id
    else:
        credit_acct_id, map_err = resolve_cash_line_account(
            db,
            company_id=expense.company_id,
            branch_id=expense.branch_id,
            source_type=SOURCE_EXPENSE,
            source_id=expense.id,
            posting_kind=KIND_EXPENSE,
            payment_method=expense.payment_mode,
        )
        if credit_acct_id is None:
            return PostingResult(False, None, map_err or "cash_gl_mapping_missing")
    return post_journal_for_operation(
        db,
        company_id=expense.company_id,
        branch_id=expense.branch_id,
        posting_date=expense.expense_date,
        source_type=SOURCE_EXPENSE,
        source_id=expense.id,
        posting_kind=KIND_EXPENSE,
        lines=[
            PostingLineSpec(
                account_id=expense_acct_id,
                debit=amount,
                description=expense.description[:200] if expense.description else "Expense",
            ),
            PostingLineSpec(
                account_id=credit_acct_id,
                credit=amount,
                description="Cash/AP out",
            ),
        ],
        posted_by=posted_by,
        description=f"Expense {expense.id}",
        metadata={"category_id": str(expense.category_id), "payment_mode": expense.payment_mode},
    )
