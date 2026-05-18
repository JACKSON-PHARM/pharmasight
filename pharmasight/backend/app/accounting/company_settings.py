"""Accounting-related company_settings helpers."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Dict
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.settings import CompanySetting

OPENING_CASH_KEY = "accounting_opening_cash_by_branch"
EXPENSE_CATEGORY_COA_KEY = "expense_category_gl_accounts"
CASH_GL_BY_PAYMENT_MODE_KEY = "accounting_cash_gl_by_payment_mode"
ACCOUNTING_POSTING_MODE_KEY = "accounting_posting_mode"


def _get_json_setting(db: Session, company_id: UUID, key: str) -> dict:
    row = (
        db.query(CompanySetting)
        .filter(CompanySetting.company_id == company_id, CompanySetting.setting_key == key)
        .first()
    )
    if not row or not row.setting_value:
        return {}
    try:
        val = row.setting_value
        if isinstance(val, dict):
            return val
        return json.loads(str(val))
    except (json.JSONDecodeError, TypeError):
        return {}


def opening_cash_for_branch(db: Session, company_id: UUID, branch_id: UUID) -> Decimal:
    data = _get_json_setting(db, company_id, OPENING_CASH_KEY)
    raw = data.get(str(branch_id)) or data.get(str(branch_id).replace("-", "")) or "0"
    return Decimal(str(raw or 0))


def expense_category_account_map(db: Session, company_id: UUID) -> Dict[str, str]:
    return _get_json_setting(db, company_id, EXPENSE_CATEGORY_COA_KEY)


def cash_gl_account_map(db: Session, company_id: UUID) -> Dict[str, str]:
    """payment_mode or cashbook_account_id (str) or 'default' → chart_of_accounts.id."""
    return _get_json_setting(db, company_id, CASH_GL_BY_PAYMENT_MODE_KEY)


def accounting_posting_mode(db: Session, company_id: UUID) -> str:
    """soft (default) | hard — hard mode raises on GL post failure."""
    row = (
        db.query(CompanySetting)
        .filter(
            CompanySetting.company_id == company_id,
            CompanySetting.setting_key == ACCOUNTING_POSTING_MODE_KEY,
        )
        .first()
    )
    if not row or not row.setting_value:
        return "soft"
    val = str(row.setting_value).strip().lower().strip('"')
    return "hard" if val == "hard" else "soft"


def accounting_posting_is_hard(db: Session, company_id: UUID) -> bool:
    return accounting_posting_mode(db, company_id) == "hard"


def set_json_setting(db: Session, company_id: UUID, key: str, value: dict) -> None:
    import json

    row = (
        db.query(CompanySetting)
        .filter(CompanySetting.company_id == company_id, CompanySetting.setting_key == key)
        .first()
    )
    payload = json.dumps(value)
    if row:
        row.setting_value = payload
    else:
        db.add(
            CompanySetting(
                company_id=company_id,
                setting_key=key,
                setting_value=payload,
            )
        )
    db.flush()


def ensure_default_cash_gl_mapping(db: Session, company_id: UUID) -> None:
    """Seed default cash GL map to control Cash when none configured (idempotent)."""
    if cash_gl_account_map(db, company_id):
        return
    from app.accounting.cash_gl_mapping import default_cash_gl_account_id

    cash_id = str(default_cash_gl_account_id(db, company_id))
    set_json_setting(
        db,
        company_id,
        CASH_GL_BY_PAYMENT_MODE_KEY,
        {"default": cash_id, "cash": cash_id, "mpesa": cash_id, "bank": cash_id, "card": cash_id},
    )
