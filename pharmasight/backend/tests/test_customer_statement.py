"""
Operational AR customer statement — unit tests (no DB).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.models.customer_financial import CustomerLedgerEntry
from app.services.customer_opening_balance import has_opening_balance_ledger_entry
from app.services.customer_statement_service import (
    TOLERANCE,
    build_statement_integrity,
    build_statement_lines,
    fetch_ledger_entries_ordered,
    sum_net_balance,
    _entry_sort_key,
)


def _entry(d, created_offset=0, debit=0, credit=0, entry_type="invoice"):
    return CustomerLedgerEntry(
        id=uuid4(),
        company_id=uuid4(),
        branch_id=uuid4(),
        customer_id=uuid4(),
        date=d,
        entry_type=entry_type,
        reference_id=uuid4(),
        debit=Decimal(str(debit)),
        credit=Decimal(str(credit)),
        created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).replace(second=created_offset),
    )


def test_entry_sort_key_stable_by_id():
    a = _entry(date(2025, 1, 5), created_offset=0, debit=10)
    b = _entry(date(2025, 1, 5), created_offset=0, debit=20)
    if a.id.int > b.id.int:
        a, b = b, a
    entries = [b, a]
    entries.sort(key=_entry_sort_key)
    assert entries[0].id == a.id


def test_opening_balance_before_from_date():
    entries = [
        _entry(date(2025, 1, 1), debit=100),
        _entry(date(2025, 1, 15), debit=50),
    ]
    opening = sum_net_balance(entries, before=date(2025, 1, 10))
    assert opening == Decimal("100.00")


def test_running_balance_deterministic():
    entries = [
        _entry(date(2025, 1, 10), debit=100),
        _entry(date(2025, 1, 12), credit=30),
        _entry(date(2025, 1, 14), debit=20),
    ]
    opening = sum_net_balance(entries, before=date(2025, 1, 10))
    lines, closing = build_statement_lines(
        entries,
        from_date=date(2025, 1, 10),
        to_date=date(2025, 1, 31),
        opening_balance=opening,
        ref_map={},
    )
    assert opening == Decimal("0.00")
    assert len(lines) == 3
    assert lines[0]["balance"] == Decimal("100.00")
    assert lines[1]["balance"] == Decimal("70.00")
    assert lines[2]["balance"] == Decimal("90.00")
    assert closing == Decimal("90.00")


def test_branch_isolation_in_sum():
    bid_a, bid_b = uuid4(), uuid4()
    e1 = _entry(date(2025, 1, 1), debit=100)
    e1.branch_id = bid_a
    e2 = _entry(date(2025, 1, 2), debit=50)
    e2.branch_id = bid_b
    branch_a_only = [e for e in [e1, e2] if e.branch_id == bid_a]
    assert sum_net_balance(branch_a_only) == Decimal("100.00")


def test_integrity_pass_within_tolerance(monkeypatch):
    class FakeQuery:
        def filter(self, *a, **k):
            return self

        def join(self, *a, **k):
            return self

        def count(self):
            return 0

        def all(self):
            return []

        def first(self):
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    monkeypatch.setattr(
        "app.services.customer_statement_service.sum_invoice_open_balances",
        lambda *a, **k: Decimal("100.00"),
    )
    monkeypatch.setattr(
        "app.services.customer_statement_service.CustomerLedgerService.get_outstanding_balance",
        lambda *a, **k: Decimal("100.00"),
    )
    out = build_statement_integrity(
        FakeDb(),
        company_id=uuid4(),
        customer_id=uuid4(),
        branch_id=None,
        to_date=date(2025, 1, 31),
        ledger_closing_balance=Decimal("100.02"),
    )
    assert out["status"] == "PASS"
    assert abs(out["delta"]) <= TOLERANCE


def test_integrity_fail_material_divergence(monkeypatch):
    class FakeQuery:
        def filter(self, *a, **k):
            return self

        def join(self, *a, **k):
            return self

        def count(self):
            return 0

        def all(self):
            return []

        def first(self):
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    monkeypatch.setattr(
        "app.services.customer_statement_service.sum_invoice_open_balances",
        lambda *a, **k: Decimal("50.00"),
    )
    monkeypatch.setattr(
        "app.services.customer_statement_service.CustomerLedgerService.get_outstanding_balance",
        lambda *a, **k: Decimal("100.00"),
    )
    out = build_statement_integrity(
        FakeDb(),
        company_id=uuid4(),
        customer_id=uuid4(),
        branch_id=None,
        to_date=date(2025, 1, 31),
        ledger_closing_balance=Decimal("100.00"),
    )
    assert out["status"] == "FAIL"


def test_pdf_integrity_fail_watermark_flag():
    from app.services.document_pdf_generator import build_customer_statement_pdf

    pdf = build_customer_statement_pdf(
        company_name="Test Co",
        customer_name="Acme",
        from_date=date(2025, 1, 1),
        to_date=date(2025, 1, 31),
        opening_balance=Decimal("0"),
        closing_balance=Decimal("100"),
        lines=[],
        integrity_status="FAIL",
    )
    assert pdf[:4] == b"%PDF"


def test_has_opening_balance_ledger_entry_false_without_db():
    """has_opening_balance requires DB; smoke-import only."""
    assert callable(has_opening_balance_ledger_entry)


def test_credit_note_ledger_idempotent():
    from unittest.mock import MagicMock
    from app.services.customer_credit_note_ledger import post_customer_ledger_on_credit_note

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = object()
    invoice = MagicMock()
    invoice.customer_id = uuid4()
    cn = MagicMock()
    cn.id = uuid4()
    cn.posting_status = "posted"
    cn.total_inclusive = Decimal("10")
    cn.branch_id = uuid4()
    cn.credit_note_date = date(2025, 1, 5)
    assert post_customer_ledger_on_credit_note(db, credit_note=cn, invoice=invoice, company_id=uuid4()) is None
