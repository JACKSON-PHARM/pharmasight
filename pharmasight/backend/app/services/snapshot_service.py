"""
Snapshot service: maintains inventory_balances and item_branch_purchase_snapshot
in sync with inventory_ledger. Called from every write point in the same transaction.

Stock math: current_stock = current_stock + quantity_delta only. Movement type is not used;
SALE (negative), SALE_RETURN (positive), PURCHASE (positive), PURCHASE_RETURN (negative),
TRANSFER_OUT (negative), TRANSFER_IN (positive), ADJUSTMENT (+/-), OPENING_BALANCE (positive)
all apply the same way. Ledger is immutable history; snapshot is current balance per (item_id, branch_id).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Tuple, Any, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SnapshotService:
    """Update snapshot tables in same transaction as ledger writes. Never commits."""

    @staticmethod
    def upsert_inventory_balance(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        quantity_delta: Decimal,
        document_number: Optional[str] = None,
    ) -> None:
        """
        Apply quantity_delta to current_stock for (item_id, branch_id).
        Call after every ledger INSERT, in the same transaction.
        Movement type is irrelevant; only quantity_delta sign matters (positive = add, negative = remove).
        Raises if applying delta would make stock negative (insufficient stock for movement).
        Pass document_number for traceability and debug logging; if None/empty, raises to ensure every movement is traceable.
        """
        if document_number is None or (isinstance(document_number, str) and str(document_number).strip() == ""):
            raise ValueError("Ledger entry missing document_number: every stock movement must be traceable.")
        qty = float(quantity_delta)
        # Lock the snapshot row if it exists so concurrent updates cannot race (read-modify-write).
        # FOR UPDATE ensures we see consistent state and block other transactions until we commit/rollback.
        row = db.execute(
            text("""
                SELECT current_stock FROM inventory_balances
                WHERE item_id = :item_id AND branch_id = :branch_id
                FOR UPDATE
            """),
            {"item_id": str(item_id), "branch_id": str(branch_id)},
        ).first()
        current = float(row[0]) if row and row[0] is not None else 0.0
        new_balance = current + qty
        if new_balance < 0:
            raise ValueError(
                f"Insufficient stock for movement: item_id={item_id} branch_id={branch_id} "
                f"current_stock={current} quantity_delta={qty} would give new_stock={new_balance}"
            )
        db.execute(
            text("""
                INSERT INTO inventory_balances (company_id, branch_id, item_id, current_stock, updated_at)
                VALUES (:company_id, :branch_id, :item_id, :qty, NOW())
                ON CONFLICT (item_id, branch_id) DO UPDATE SET
                    current_stock = inventory_balances.current_stock + EXCLUDED.current_stock,
                    updated_at = NOW()
            """),
            {"company_id": str(company_id), "branch_id": str(branch_id), "item_id": str(item_id), "qty": qty},
        )
        logger.debug(
            "Snapshot update: item_id=%s branch_id=%s delta=%s new_balance=%s document_number=%s",
            item_id, branch_id, qty, new_balance, document_number,
        )

    @staticmethod
    def upsert_inventory_balance_bulk(
        db: Session,
        rows: List[Tuple[UUID, UUID, UUID, Any]],
    ) -> None:
        """
        Bulk upsert inventory_balances. rows = [(company_id, branch_id, item_id, quantity_delta), ...].
        Single round-trip for Excel import / bulk opening balance. Uses same transaction as caller.
        Does not perform per-row negative-stock check (used for opening balance where deltas are positive).
        """
        if not rows:
            return
        value_parts = []
        params = {}
        for i, (company_id, branch_id, item_id, qty) in enumerate(rows):
            q = float(qty)
            value_parts.append(
                f"(:c{i}, :b{i}, :i{i}, :q{i}, NOW())"
            )
            params[f"c{i}"] = str(company_id)
            params[f"b{i}"] = str(branch_id)
            params[f"i{i}"] = str(item_id)
            params[f"q{i}"] = q
        sql = f"""
            INSERT INTO inventory_balances (company_id, branch_id, item_id, current_stock, updated_at)
            VALUES {", ".join(value_parts)}
            ON CONFLICT (item_id, branch_id) DO UPDATE SET
                current_stock = inventory_balances.current_stock + EXCLUDED.current_stock,
                updated_at = NOW()
        """
        db.execute(text(sql), params)

    @staticmethod
    def upsert_inventory_balance_delta(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        old_qty: Decimal,
        new_qty: Decimal,
        document_number: Optional[str] = "OPENING",
    ) -> None:
        """For opening balance UPDATE: apply delta = new - old."""
        delta = Decimal(str(new_qty)) - Decimal(str(old_qty))
        SnapshotService.upsert_inventory_balance(
            db, company_id, branch_id, item_id, delta,
            document_number=document_number or "OPENING",
        )

    @staticmethod
    def upsert_purchase_snapshot(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        last_purchase_price: Decimal | None,
        last_purchase_date,
        last_supplier_id: UUID | None,
    ) -> None:
        """Set last purchase for (item_id, branch_id). Call after PURCHASE ledger write."""
        price = float(last_purchase_price) if last_purchase_price is not None else None
        supplier_str = str(last_supplier_id) if last_supplier_id else None
        db.execute(
            text("""
                INSERT INTO item_branch_purchase_snapshot
                    (company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, updated_at)
                VALUES (:company_id, :branch_id, :item_id, :price, :dt, :supplier_id, NOW())
                ON CONFLICT (item_id, branch_id) DO UPDATE SET
                    last_purchase_price = EXCLUDED.last_purchase_price,
                    last_purchase_date = EXCLUDED.last_purchase_date,
                    last_supplier_id = EXCLUDED.last_supplier_id,
                    updated_at = NOW()
            """),
            {
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "item_id": str(item_id),
                "price": price,
                "dt": last_purchase_date,
                "supplier_id": supplier_str,
            },
        )

    @staticmethod
    def upsert_purchase_snapshot_bulk(
        db: Session,
        rows: List[Tuple[UUID, UUID, UUID, Any, Any, Any]],
    ) -> None:
        """
        Bulk upsert item_branch_purchase_snapshot.
        rows = [(company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id), ...].
        """
        if not rows:
            return
        value_parts = []
        params = {}
        for i, (company_id, branch_id, item_id, price, dt, supplier_id) in enumerate(rows):
            p = float(price) if price is not None else None
            sup = str(supplier_id) if supplier_id is not None else None
            value_parts.append(
                f"(:c{i}, :b{i}, :i{i}, :p{i}, :dt{i}, :s{i}, NOW())"
            )
            params[f"c{i}"] = str(company_id)
            params[f"b{i}"] = str(branch_id)
            params[f"i{i}"] = str(item_id)
            params[f"p{i}"] = p
            params[f"dt{i}"] = dt
            params[f"s{i}"] = sup
        sql = f"""
            INSERT INTO item_branch_purchase_snapshot
                (company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, updated_at)
            VALUES {", ".join(value_parts)}
            ON CONFLICT (item_id, branch_id) DO UPDATE SET
                last_purchase_price = EXCLUDED.last_purchase_price,
                last_purchase_date = EXCLUDED.last_purchase_date,
                last_supplier_id = EXCLUDED.last_supplier_id,
                updated_at = NOW()
        """
        db.execute(text(sql), params)

    @staticmethod
    def upsert_search_snapshot_last_order(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        order_date,
    ) -> None:
        """Update last_order_date in item_branch_search_snapshot. Call when PO created."""
        db.execute(
            text("""
                INSERT INTO item_branch_search_snapshot (company_id, branch_id, item_id, last_order_date, updated_at)
                VALUES (:company_id, :branch_id, :item_id, :order_date, NOW())
                ON CONFLICT (item_id, branch_id) DO UPDATE SET
                    last_order_date = CASE
                        WHEN item_branch_search_snapshot.last_order_date IS NULL OR (EXCLUDED.last_order_date IS NOT NULL AND EXCLUDED.last_order_date >= item_branch_search_snapshot.last_order_date)
                        THEN EXCLUDED.last_order_date
                        ELSE item_branch_search_snapshot.last_order_date
                    END,
                    updated_at = NOW()
            """),
            {
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "item_id": str(item_id),
                "order_date": order_date,
            },
        )

    @staticmethod
    def upsert_search_snapshot_last_sale(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        sale_date,
    ) -> None:
        """Update last_sale_date in item_branch_search_snapshot. Call when sales invoice batched."""
        db.execute(
            text("""
                INSERT INTO item_branch_search_snapshot (company_id, branch_id, item_id, last_sale_date, updated_at)
                VALUES (:company_id, :branch_id, :item_id, :sale_date, NOW())
                ON CONFLICT (item_id, branch_id) DO UPDATE SET
                    last_sale_date = CASE
                        WHEN item_branch_search_snapshot.last_sale_date IS NULL OR (EXCLUDED.last_sale_date IS NOT NULL AND EXCLUDED.last_sale_date >= item_branch_search_snapshot.last_sale_date)
                        THEN EXCLUDED.last_sale_date
                        ELSE item_branch_search_snapshot.last_sale_date
                    END,
                    updated_at = NOW()
            """),
            {
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "item_id": str(item_id),
                "sale_date": sale_date,
            },
        )

    @staticmethod
    def upsert_search_snapshot_last_order_book(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        created_at,
    ) -> None:
        """Update last_order_book_date in item_branch_search_snapshot. Call when order book entry added."""
        db.execute(
            text("""
                INSERT INTO item_branch_search_snapshot (company_id, branch_id, item_id, last_order_book_date, updated_at)
                VALUES (:company_id, :branch_id, :item_id, :created_at, NOW())
                ON CONFLICT (item_id, branch_id) DO UPDATE SET
                    last_order_book_date = CASE
                        WHEN item_branch_search_snapshot.last_order_book_date IS NULL OR (EXCLUDED.last_order_book_date IS NOT NULL AND EXCLUDED.last_order_book_date >= item_branch_search_snapshot.last_order_book_date)
                        THEN EXCLUDED.last_order_book_date
                        ELSE item_branch_search_snapshot.last_order_book_date
                    END,
                    updated_at = NOW()
            """),
            {
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "item_id": str(item_id),
                "created_at": created_at,
            },
        )
