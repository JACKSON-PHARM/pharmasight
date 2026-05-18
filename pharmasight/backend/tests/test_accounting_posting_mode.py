"""Accounting posting mode helper (no DB)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.company_settings import accounting_posting_is_hard, accounting_posting_mode


def test_posting_mode_defaults_soft():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    company_id = uuid4()
    assert accounting_posting_mode(db, company_id) == "soft"
    assert accounting_posting_is_hard(db, company_id) is False


def test_posting_mode_hard():
    db = MagicMock()
    row = MagicMock()
    row.setting_value = "hard"
    db.query.return_value.filter.return_value.first.return_value = row
    company_id = uuid4()
    assert accounting_posting_mode(db, company_id) == "hard"
    assert accounting_posting_is_hard(db, company_id) is True
