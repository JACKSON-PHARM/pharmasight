"""Customer payment GL posting — balanced lines (no DB)."""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.constants import CONTROL_AR, CONTROL_CASH
from app.accounting.posting.engine import _validate_balanced, build_idempotency_key
from app.accounting.posting.types import PostingLineSpec

SOURCE = "customer_payment"
KIND = "customer_payment"


class _Acct:
    def __init__(self, role):
        self.id = uuid4()
        self.control_role = role


def _build_customer_payment_lines(amount: Decimal, accounts: dict) -> list:
    """Mirror customer_payment.py line construction."""
    return [
        PostingLineSpec(
            account_id=accounts[CONTROL_CASH].id,
            debit=amount,
            description="Customer receipt",
        ),
        PostingLineSpec(
            account_id=accounts[CONTROL_AR].id,
            credit=amount,
            description="AR settlement",
        ),
    ]


def test_customer_payment_lines_balance():
    accounts = {CONTROL_CASH: _Acct(CONTROL_CASH), CONTROL_AR: _Acct(CONTROL_AR)}
    amount = Decimal("5000.00")
    lines = _build_customer_payment_lines(amount, accounts)
    _validate_balanced(lines)
    assert sum(l.debit for l in lines) == amount
    assert sum(l.credit for l in lines) == amount


def test_customer_payment_idempotency_key():
    pid = uuid4()
    key = build_idempotency_key(SOURCE, pid, KIND)
    assert key == f"customer_payment:{pid}:customer_payment"


def test_customer_payment_dr_cash_cr_ar():
    accounts = {CONTROL_CASH: _Acct(CONTROL_CASH), CONTROL_AR: _Acct(CONTROL_AR)}
    lines = _build_customer_payment_lines(Decimal("116.00"), accounts)
    cash_line = next(l for l in lines if l.debit > 0)
    ar_line = next(l for l in lines if l.credit > 0)
    assert cash_line.account_id == accounts[CONTROL_CASH].id
    assert ar_line.account_id == accounts[CONTROL_AR].id
