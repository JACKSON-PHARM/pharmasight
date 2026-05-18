"""M1 accounting core — unit tests (no DB)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.posting.engine import _validate_balanced, build_idempotency_key
from app.accounting.posting.types import PostingLineSpec
from app.accounting.posting.sales import _build_revenue_lines, _revenue_uses_cash
from app.accounting.constants import (
    CONTROL_AR,
    CONTROL_CASH,
    CONTROL_REVENUE,
    CONTROL_VAT_OUTPUT,
)


class _Acct:
    def __init__(self, role, aid=None):
        self.id = aid or uuid4()
        self.control_role = role


class _Inv:
    def __init__(self, **kw):
        self.total_exclusive = kw.get("total_exclusive", Decimal("100"))
        self.vat_amount = kw.get("vat_amount", Decimal("16"))
        self.total_inclusive = kw.get("total_inclusive", Decimal("116"))
        self.invoice_no = kw.get("invoice_no", "INV-1")
        self.customer_id = kw.get("customer_id", uuid4())
        self.payment_status = kw.get("payment_status", "UNPAID")
        self.payment_mode = kw.get("payment_mode", "credit")
        self.balance = kw.get("balance", Decimal("116"))


def test_idempotency_key_stable():
    sid = uuid4()
    assert build_idempotency_key("sales_invoice", sid, "sale_revenue") == build_idempotency_key(
        "sales_invoice", sid, "sale_revenue"
    )


def test_validate_balanced_rejects_imbalance():
    aid = uuid4()
    with pytest.raises(ValueError, match="Unbalanced"):
        _validate_balanced(
            [
                PostingLineSpec(account_id=aid, debit=Decimal("100")),
                PostingLineSpec(account_id=aid, credit=Decimal("50")),
            ]
        )


def test_validate_balanced_accepts_pair():
    a, b = uuid4(), uuid4()
    _validate_balanced(
        [
            PostingLineSpec(account_id=a, debit=Decimal("116")),
            PostingLineSpec(account_id=b, credit=Decimal("100")),
            PostingLineSpec(account_id=b, credit=Decimal("16")),
        ]
    )


def test_revenue_lines_credit_sale_dr_ar():
    accounts = {
        CONTROL_AR: _Acct(CONTROL_AR),
        CONTROL_CASH: _Acct(CONTROL_CASH),
        CONTROL_REVENUE: _Acct(CONTROL_REVENUE),
        CONTROL_VAT_OUTPUT: _Acct(CONTROL_VAT_OUTPUT),
    }
    inv = _Inv(payment_status="UNPAID", balance=Decimal("116"))
    assert not _revenue_uses_cash(inv)
    lines = _build_revenue_lines(accounts, inv)
    assert sum(l.debit for l in lines) == Decimal("116")
    assert sum(l.credit for l in lines) == Decimal("116")


def test_revenue_lines_cash_sale_dr_cash():
    accounts = {
        CONTROL_AR: _Acct(CONTROL_AR),
        CONTROL_CASH: _Acct(CONTROL_CASH),
        CONTROL_REVENUE: _Acct(CONTROL_REVENUE),
        CONTROL_VAT_OUTPUT: _Acct(CONTROL_VAT_OUTPUT),
    }
    inv = _Inv(
        customer_id=None,
        payment_status="PAID",
        payment_mode="cash",
        balance=Decimal("0"),
    )
    assert _revenue_uses_cash(inv)
    lines = _build_revenue_lines(accounts, inv)
    assert lines[0].debit == Decimal("116")
    assert lines[0].account_id == accounts[CONTROL_CASH].id
