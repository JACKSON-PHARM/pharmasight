"""
Batch processor: submit sales invoices with submission_status=pending to KRA OSCU.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import BranchEtimsCredentials
from app.models.sale import SalesInvoice
from app.services.etims.etims_invoice_submitter import EtimsSubmissionSkipped, submit_sales_invoice

logger = logging.getLogger(__name__)


def list_pending_etims_invoice_ids(db: Session, *, limit: int = 25) -> List[UUID]:
    q = (
        db.query(SalesInvoice.id)
        .join(BranchEtimsCredentials, BranchEtimsCredentials.branch_id == SalesInvoice.branch_id)
        .filter(
            SalesInvoice.submission_status == "pending",
            SalesInvoice.status.in_(("BATCHED", "PAID")),
            BranchEtimsCredentials.enabled.is_(True),
            BranchEtimsCredentials.connection_status == "verified",
        )
        .order_by(SalesInvoice.created_at.asc())
        .limit(limit)
    )
    return [row[0] for row in q.all()]


def process_pending_etims_submissions(db: Session, *, limit: int = 25) -> Dict[str, Any]:
    """
    Attempt each pending invoice (enabled branch credentials). Each submit_sales_invoice commits internally.
    """
    ids = list_pending_etims_invoice_ids(db, limit=limit)
    out: Dict[str, Any] = {
        "candidates": len(ids),
        "submitted_ok": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }
    for iid in ids:
        try:
            res = submit_sales_invoice(db, iid)
            if res.get("ok"):
                out["submitted_ok"] += 1
            else:
                out["failed"] += 1
        except EtimsSubmissionSkipped as e:
            db.rollback()
            out["skipped"] += 1
            logger.info("eTIMS skip %s: %s", iid, e)
        except Exception as e:
            db.rollback()
            out["errors"].append(f"{iid}: {e}")
            logger.exception("eTIMS submit error for %s", iid)
    return out
