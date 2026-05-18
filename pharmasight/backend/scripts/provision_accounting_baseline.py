"""
Provision chart of accounts + current fiscal period for existing companies.

  python -m scripts.provision_accounting_baseline [--company-id UUID]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.company import Company
from app.accounting.coa_service import provision_default_chart_of_accounts, company_has_coa
from app.accounting.company_settings import ensure_default_cash_gl_mapping
from app.accounting.fiscal_period_service import provision_current_open_period


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", default=None)
    args = parser.parse_args()
    db = SessionLocal()
    try:
        q = db.query(Company)
        if args.company_id:
            q = q.filter(Company.id == UUID(args.company_id))
        for company in q.all():
            had = company_has_coa(db, company.id)
            n = provision_default_chart_of_accounts(db, company.id)
            ensure_default_cash_gl_mapping(db, company.id)
            provision_current_open_period(db, company.id)
            print(f"{company.id} {company.name!r}: coa_created={n} had_coa={had}")
        db.commit()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
