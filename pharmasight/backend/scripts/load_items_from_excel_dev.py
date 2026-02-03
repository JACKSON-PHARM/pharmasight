"""
Load items from an Excel file directly into the database (development only).

Bypasses the app (no HTTP, no auth). Uses the same conversion rules as the app:
- Wholesale = default/base unit
- Retail = wholesale × pack_size
- Supplier = wholesale ÷ wholesale_units_per_supplier

Sets items.default_cost_per_base and items.default_supplier_id from Excel.
Creates opening balances when "Current stock quantity" > 0.

Usage (from repo root):
  python -m pharmasight.backend.scripts.load_items_from_excel_dev --file path/to.xlsx --company-id UUID --branch-id UUID --user-id UUID

Or from backend/:
  python scripts/load_items_from_excel_dev.py --file path/to.xlsx --company-id UUID --branch-id UUID --user-id UUID

Optional:
  --db-url URL   Override database URL (default: from DATABASE_URL / Supabase env)
  --dry-run      Parse file and print row count only; do not write to DB

Requires: pandas, openpyxl. Get company_id, branch_id, user_id from the app or DB.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

import pandas as pd

# Add backend to path when run as script
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import settings
from app.database import SessionLocal
from app.services.excel_import_service import ExcelImportService


def _valid_uuid(s: str) -> UUID:
    try:
        return UUID(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid UUID: {s}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load items from Excel into DB (development only). Same conversion rules as app.",
        epilog="Example: python scripts/load_items_from_excel_dev.py --file C:/Users/.../pharmacy_enhanced_template.xlsx --company-id <uuid> --branch-id <uuid> --user-id <uuid>",
    )
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        required=True,
        help="Path to Excel file (.xlsx)",
    )
    parser.add_argument("--company-id", type=_valid_uuid, required=True, help="Company UUID")
    parser.add_argument("--branch-id", type=_valid_uuid, required=True, help="Branch UUID")
    parser.add_argument("--user-id", type=_valid_uuid, required=True, help="User UUID (created_by for ledger)")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: from DATABASE_URL / Supabase env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only parse file and print row count; do not write to DB",
    )
    args = parser.parse_args()

    path = args.file
    if not path.is_file():
        print(f"ERROR: File not found: {path}")
        return 1

    # Parse Excel — coerce NaN to None (same as API)
    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception as e:
        print(f"ERROR: Failed to read Excel: {e}")
        return 1

    raw = df.to_dict("records")
    excel_data = [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in raw]

    print(f"Parsed {len(excel_data)} rows from {path.name}")

    if args.dry_run:
        print("Dry-run: not writing to DB.")
        return 0

    # Use default DB from settings unless --db-url provided
    if args.db_url:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        engine = create_engine(args.db_url)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = session_factory()
    else:
        if not settings.database_connection_string:
            print("ERROR: DATABASE_URL (or Supabase DB env) not set. Use --db-url or set env.")
            return 1
        db = SessionLocal()

    try:
        result = ExcelImportService.import_excel_data(
            db=db,
            company_id=args.company_id,
            branch_id=args.branch_id,
            user_id=args.user_id,
            excel_data=excel_data,
            force_mode="AUTHORITATIVE",
            column_mapping=None,
        )
        db.commit()
        success = result.get("success", False)
        stats = result.get("stats", {})
        print(f"Import {'succeeded' if success else 'failed'}.")
        print(f"  Items created: {stats.get('items_created', 0)}")
        print(f"  Items updated: {stats.get('items_updated', 0)}")
        print(f"  Opening balances: {stats.get('opening_balances_created', 0)}")
        print(f"  Suppliers created: {stats.get('suppliers_created', 0)}")
        if stats.get("errors"):
            for err in stats["errors"][:10]:
                print(f"  Error: {err}")
            if len(stats["errors"]) > 10:
                print(f"  ... and {len(stats['errors']) - 10} more errors")
        if not success and result.get("error"):
            print(f"  Error: {result['error']}")
        return 0 if success else 1
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
