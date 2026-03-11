"""
Branch settings: ensure default row exists so every branch has explicit settings.
Called when a branch is created so branch_settings is populated without requiring
the user to open Settings → Branches → Branch inventory first.
"""
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.company import BranchSetting


def ensure_default_branch_settings(db: Session, branch_id: UUID) -> None:
    """
    Create a default branch_settings row for the branch if one does not exist.
    Idempotent: safe to call on every branch creation; no-op if row already exists.
    """
    if db.query(BranchSetting).filter(BranchSetting.branch_id == branch_id).first():
        return
    db.add(
        BranchSetting(
            branch_id=branch_id,
            allow_manual_transfer=True,
            allow_manual_receipt=True,
            allow_adjust_cost=True,
            cost_outlier_threshold_pct=None,
            min_margin_retail_pct_override=None,
        )
    )
