"""Pending supplier returns reserve stock before approval/posting."""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, Optional
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.supplier_financial import SupplierReturn, SupplierReturnLine


class SupplierReturnReservationService:
    @staticmethod
    def reserved_qty_for_item(
        db: Session,
        *,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        exclude_return_id: Optional[UUID] = None,
    ) -> Decimal:
        q = (
            db.query(func.coalesce(func.sum(SupplierReturnLine.quantity), 0))
            .join(SupplierReturn, SupplierReturn.id == SupplierReturnLine.supplier_return_id)
            .filter(
                SupplierReturn.company_id == company_id,
                SupplierReturn.branch_id == branch_id,
                SupplierReturn.status == "pending",
                or_(SupplierReturn.posting_status.is_(None), SupplierReturn.posting_status != "posted"),
                SupplierReturnLine.item_id == item_id,
            )
        )
        if exclude_return_id is not None:
            q = q.filter(SupplierReturn.id != exclude_return_id)
        return Decimal(str(q.scalar() or 0))

    @staticmethod
    def reserved_qty_by_item(
        db: Session,
        *,
        company_id: UUID,
        branch_id: UUID,
        item_ids: Iterable[UUID],
        exclude_return_id: Optional[UUID] = None,
    ) -> Dict[UUID, Decimal]:
        ids = list({iid for iid in item_ids if iid})
        if not ids:
            return {}
        q = (
            db.query(SupplierReturnLine.item_id, func.coalesce(func.sum(SupplierReturnLine.quantity), 0))
            .join(SupplierReturn, SupplierReturn.id == SupplierReturnLine.supplier_return_id)
            .filter(
                SupplierReturn.company_id == company_id,
                SupplierReturn.branch_id == branch_id,
                SupplierReturn.status == "pending",
                or_(SupplierReturn.posting_status.is_(None), SupplierReturn.posting_status != "posted"),
                SupplierReturnLine.item_id.in_(ids),
            )
            .group_by(SupplierReturnLine.item_id)
        )
        if exclude_return_id is not None:
            q = q.filter(SupplierReturn.id != exclude_return_id)
        return {row[0]: Decimal(str(row[1] or 0)) for row in q.all()}
