"""GL backfill counters (no DB)."""
from __future__ import annotations

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.backfill_gl import BackfillCounters
from app.accounting.posting.types import PostingResult


def test_backfill_counters_posted():
    c = BackfillCounters()
    c.record(PostingResult(True, None, "posted"))
    assert c.posted == 1
    assert c.failed == 0


def test_backfill_counters_duplicate():
    c = BackfillCounters()
    c.record(PostingResult(False, None, "duplicate", skipped_duplicate=True))
    assert c.skipped_duplicate == 1
    assert c.posted == 0


def test_backfill_counters_failed():
    c = BackfillCounters()
    c.record(PostingResult(False, None, "cash_gl_mapping_missing"))
    assert c.failed == 1
