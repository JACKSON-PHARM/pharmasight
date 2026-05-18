#!/usr/bin/env python3
"""
CLI: replay unresolved financial_event_emission_failures (E4).

Usage:
  python scripts/replay_financial_event_failures.py --company-id <uuid> [--limit 100]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.database import SessionLocal
from app.finance.events.replay import replay_unresolved_failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay financial event emission failures")
    parser.add_argument("--company-id", required=True, help="Company UUID")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    company_id = UUID(args.company_id)
    db = SessionLocal()
    try:
        outcomes = replay_unresolved_failures(db, company_id=company_id, limit=args.limit)
        for o in outcomes:
            print(f"{o.failure_id} -> {o.result.value} ({o.message}) event={o.financial_event_id}")
        print(f"Processed {len(outcomes)} failure(s)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
