from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.invoice_payment_status import apply_payment_status_from_settled, outstanding_balance
from app.utils.money import money_amount


def test_money_amount_rounds_fractional_cent_totals():
    assert money_amount(Decimal("99.999")) == Decimal("100.00")
    assert money_amount(Decimal("99.994")) == Decimal("99.99")


def test_invoice_settlement_uses_currency_rounded_total():
    invoice = SimpleNamespace(
        total_inclusive=Decimal("99.999"),
        payment_status="UNPAID",
        status="BATCHED",
        cashier_approved=False,
        approved_by=None,
        approved_at=None,
    )

    assert outstanding_balance(invoice, Decimal("100.00")) == Decimal("0")
    assert apply_payment_status_from_settled(invoice, Decimal("100.00")) == "PAID"
    assert invoice.status == "PAID"
