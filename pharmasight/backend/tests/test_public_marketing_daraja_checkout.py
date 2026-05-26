"""Daraja checkout copy and configuration helpers."""
from __future__ import annotations

import sys
import os
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ["DEBUG"] = "false"

from app.api.public_marketing import (  # noqa: E402
    SubscriptionCheckoutRequest,
    _daraja_transaction_type,
    public_daraja_checkout,
)


def test_daraja_transaction_type_uses_till_mode(monkeypatch):
    monkeypatch.delenv("DARAJA_TRANSACTION_TYPE", raising=False)
    monkeypatch.setenv("DARAJA_PAYMENT_MODE", "till")

    assert _daraja_transaction_type() == "CustomerBuyGoodsOnline"


def test_checkout_without_stk_enabled_returns_manual_feedback(monkeypatch):
    monkeypatch.delenv("DARAJA_ENABLE_STK_PUSH", raising=False)
    monkeypatch.setenv("DARAJA_PAYMENT_MODE", "till")
    monkeypatch.setenv("DARAJA_TILL_NUMBER", "123456")

    response = public_daraja_checkout.__wrapped__(
        None,
        SubscriptionCheckoutRequest(
            organization_name="Acme Pharmacy",
            full_name="Jane Doe",
            email="jane@example.com",
            phone="0700000000",
        ),
    )

    assert response.payment_initiated is False
    assert response.payment_method_label == "M-PESA Till"
    assert "STK push was not sent" in response.message
    assert "123456" in response.manual_payment_instructions
