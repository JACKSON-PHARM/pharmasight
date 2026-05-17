"""
Repair branch access + item search snapshots for an existing branch.

Usage (from pharmasight/backend):
  python scripts/repair_branch_provisioning.py <branch_id>
"""
import sys
from uuid import UUID

from app.database import SessionLocal
from app.models.company import Branch
from app.models.user import UserBranchRole
from app.services.branch_provisioning_service import provision_new_branch


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/repair_branch_provisioning.py <branch_id>")
        sys.exit(1)
    branch_id = UUID(sys.argv[1])
    db = SessionLocal()
    try:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            print(f"Branch not found: {branch_id}")
            sys.exit(1)
        creator = (
            db.query(UserBranchRole.user_id)
            .filter(UserBranchRole.branch_id != branch_id)
            .join(Branch, UserBranchRole.branch_id == Branch.id)
            .filter(Branch.company_id == branch.company_id)
            .first()
        )
        if not creator:
            print("No user with another branch role in this company; cannot infer creator.")
            sys.exit(1)
        provision_new_branch(
            db,
            company_id=branch.company_id,
            branch_id=branch.id,
            created_by_user_id=creator[0],
        )
        db.commit()
        print(f"Repaired branch {branch.code} ({branch.id})")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
