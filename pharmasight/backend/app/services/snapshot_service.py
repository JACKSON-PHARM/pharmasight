"""
Snapshot service: maintains inventory_balances and item_branch_purchase_snapshot
in sync with inventory_ledger. Called from every write point in the same transaction.
"""
from decimal import Decimal
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text


class SnapshotService:
    """Update snapshot tables in same transaction as ledger writes."""

    @staticmethod
    def upsert_inventory_balance(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        quantity_delta: Decimal,
    ) -> None:
        """Increment/decrement current_stock. Call after every ledger INSERT."""
        qty = float(quantity_delta)
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

    @staticmethod
    def upsert_inventory_balance_delta(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
        old_qty: Decimal,
        new_qty: Decimal,
    ) -> None:
        """For opening balance UPDATE: apply delta = new - old."""
        delta = Decimal(str(new_qty)) - Decimal(str(old_qty))
        SnapshotService.upsert_inventory_balance(db, company_id, branch_id, item_id, delta)

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
