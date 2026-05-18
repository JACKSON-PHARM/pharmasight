"""Cash GL mapping helpers (no DB)."""
from __future__ import annotations

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.cash_gl_mapping import normalize_payment_mode
from app.accounting.company_settings import ACCOUNTING_POSTING_MODE_KEY, CASH_GL_BY_PAYMENT_MODE_KEY


def test_normalize_payment_mode_mpesa():
    assert normalize_payment_mode("M-Pesa") == "mpesa"
    assert normalize_payment_mode("MPESA") == "mpesa"


def test_normalize_payment_mode_bank():
    assert normalize_payment_mode("bank_transfer") == "bank"


def test_normalize_payment_mode_default_cash():
    assert normalize_payment_mode("") == "cash"
    assert normalize_payment_mode(None) == "cash"


def test_setting_keys_defined():
    assert CASH_GL_BY_PAYMENT_MODE_KEY == "accounting_cash_gl_by_payment_mode"
    assert ACCOUNTING_POSTING_MODE_KEY == "accounting_posting_mode"
