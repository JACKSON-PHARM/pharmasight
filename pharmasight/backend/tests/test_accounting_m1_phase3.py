"""M1 Phase 3–5 — supplier posting lines, reconciliation status (no DB)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.constants import (
    CONTROL_AP,
    CONTROL_EXPENSE,
    CONTROL_INVENTORY,
    CONTROL_VAT_INPUT,
)
from app.accounting.posting.engine import _validate_balanced
from app.accounting.posting.types import PostingLineSpec
RECON_TOLERANCE = Decimal("0.05")


def _status_for_delta(delta: Decimal, warnings: list) -> str:
    if abs(delta) <= RECON_TOLERANCE:
        return "PASS" if not warnings else "PASS_WITH_WARNINGS"
    return "FAIL"


class _Acct:
    def __init__(self, role):
        self.id = uuid4()
        self.control_role = role


class _Invoice:
    def __init__(self, **kw):
        self.company_id = kw.get("company_id", uuid4())
        self.branch_id = kw.get("branch_id", uuid4())
        self.id = kw.get("id", uuid4())
        self.invoice_date = kw.get("invoice_date")
        self.invoice_number = kw.get("invoice_number", "SPV-001")
        self.internal_reference = kw.get("internal_reference", "")
        self.reference = kw.get("reference", "")
        self.total_exclusive = kw.get("total_exclusive", Decimal("1000"))
        self.vat_amount = kw.get("vat_amount", Decimal("160"))
        self.total_inclusive = kw.get("total_inclusive", Decimal("1160"))


def _build_supplier_invoice_lines(invoice: _Invoice, accounts: dict) -> list:
    """Mirror supplier.py line construction for unit test."""
    exclusive = Decimal(str(invoice.total_exclusive or 0))
    vat = Decimal(str(invoice.vat_amount or 0))
    inclusive = Decimal(str(invoice.total_inclusive or 0))
    ref = (invoice.internal_reference or invoice.reference or "").upper()
    uses_expense = "SERVICE" in ref or "OPEX" in ref
    debit_account = accounts[CONTROL_EXPENSE] if uses_expense else accounts[CONTROL_INVENTORY]
    lines = [
        PostingLineSpec(account_id=debit_account.id, debit=exclusive, description="Purchase"),
    ]
    if vat > 0:
        lines.append(
            PostingLineSpec(account_id=accounts[CONTROL_VAT_INPUT].id, debit=vat, description="VAT")
        )
    lines.append(
        PostingLineSpec(account_id=accounts[CONTROL_AP].id, credit=inclusive, description="AP")
    )
    return lines


def test_supplier_invoice_gl_lines_balance_inventory():
    accounts = {
        CONTROL_INVENTORY: _Acct(CONTROL_INVENTORY),
        CONTROL_VAT_INPUT: _Acct(CONTROL_VAT_INPUT),
        CONTROL_AP: _Acct(CONTROL_AP),
        CONTROL_EXPENSE: _Acct(CONTROL_EXPENSE),
    }
    inv = _Invoice()
    lines = _build_supplier_invoice_lines(inv, accounts)
    _validate_balanced(lines)
    assert sum(l.debit for l in lines) == Decimal("1160")
    assert sum(l.credit for l in lines) == Decimal("1160")


def test_supplier_invoice_service_uses_expense_account():
    accounts = {
        CONTROL_INVENTORY: _Acct(CONTROL_INVENTORY),
        CONTROL_VAT_INPUT: _Acct(CONTROL_VAT_INPUT),
        CONTROL_AP: _Acct(CONTROL_AP),
        CONTROL_EXPENSE: _Acct(CONTROL_EXPENSE),
    }
    inv = _Invoice(internal_reference="SERVICE-INV")
    lines = _build_supplier_invoice_lines(inv, accounts)
    assert lines[0].account_id == accounts[CONTROL_EXPENSE].id
    _validate_balanced(lines)


def test_reconciliation_status_pass_within_tolerance():
    assert _status_for_delta(Decimal("0.03"), []) == "PASS"
    assert _status_for_delta(Decimal("0.05"), []) == "PASS"


def test_reconciliation_status_fail_outside_tolerance():
    assert _status_for_delta(Decimal("0.06"), []) == "FAIL"
    assert _status_for_delta(Decimal("-0.10"), []) == "FAIL"


def test_recon_tolerance_constant():
    assert RECON_TOLERANCE == Decimal("0.05")
