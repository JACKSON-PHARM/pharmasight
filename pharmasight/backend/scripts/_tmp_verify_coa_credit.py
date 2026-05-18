"""Verify CREDIT can be inserted into chart_of_accounts after migration 144."""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text

from app.database import SessionLocal
from app.models.company import Company


def main() -> int:
    db = SessionLocal()
    try:
        width = db.execute(
            text(
                """
                SELECT character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'chart_of_accounts'
                  AND column_name = 'normal_balance'
                """
            )
        ).scalar()
        print("normal_balance max length:", width)

        c = db.query(Company).first()
        if not c:
            print("no company")
            return 1
        db.execute(
            text(
                """
                INSERT INTO chart_of_accounts
                  (company_id, code, name, category, control_role, is_control_account, normal_balance, is_active)
                VALUES
                  (:cid, '2998', 'Credit probe', 'LIABILITY', 'PROBE_CREDIT', true, 'CREDIT', true)
                ON CONFLICT (company_id, code) DO NOTHING
                """
            ),
            {"cid": str(c.id)},
        )
        db.commit()
        print("CREDIT insert: OK")
        return 0
    except Exception as exc:
        db.rollback()
        print("FAIL:", exc)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
