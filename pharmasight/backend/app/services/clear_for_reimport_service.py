"""
Clear company-specific data so you can run an Excel import afresh.

Used by:
- API: POST /api/excel/clear-for-reimport (only when no live transactions)
- CLI: scripts/clear_company_for_reimport.py

Deletes (in FK-safe order): import jobs, inventory ledger, stock take data,
order book, GRNs, purchase invoices/orders, payments, credit notes, sales
invoices, quotations, items (and item_units, item_pricing), suppliers.

Does NOT delete: companies, branches, users, tenants, settings, document
sequences.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

# Deletion order: children before parents, respecting FKs.
# Use :company_id in SQL and pass params.
DELETIONS = [
    ("import_jobs", "company_id = :company_id"),
    ("invoice_payments", "invoice_id IN (SELECT id FROM sales_invoices WHERE company_id = :company_id)"),
    ("payments", "sales_invoice_id IN (SELECT id FROM sales_invoices WHERE company_id = :company_id)"),
    ("credit_note_items", "credit_note_id IN (SELECT id FROM credit_notes WHERE company_id = :company_id)"),
    ("credit_notes", "company_id = :company_id"),
    ("sales_invoice_items", "sales_invoice_id IN (SELECT id FROM sales_invoices WHERE company_id = :company_id)"),
    ("sales_invoices", "company_id = :company_id"),
    ("quotation_items", "quotation_id IN (SELECT id FROM quotations WHERE company_id = :company_id)"),
    ("quotations", "company_id = :company_id"),
    ("inventory_ledger", "company_id = :company_id"),
    ("stock_take_counts", "session_id IN (SELECT id FROM stock_take_sessions WHERE company_id = :company_id)"),
    ("stock_take_adjustments", "session_id IN (SELECT id FROM stock_take_sessions WHERE company_id = :company_id)"),
    ("stock_take_counter_locks", "session_id IN (SELECT id FROM stock_take_sessions WHERE company_id = :company_id)"),
    ("stock_take_sessions", "company_id = :company_id"),
    ("order_book_history", "company_id = :company_id"),
    ("daily_order_book", "company_id = :company_id"),
    ("grn_items", "grn_id IN (SELECT id FROM grns WHERE company_id = :company_id)"),
    ("grns", "company_id = :company_id"),
    ("purchase_invoice_items", "purchase_invoice_id IN (SELECT id FROM purchase_invoices WHERE company_id = :company_id)"),
    ("purchase_invoices", "company_id = :company_id"),
    ("purchase_order_items", "purchase_order_id IN (SELECT id FROM purchase_orders WHERE company_id = :company_id)"),
    ("purchase_orders", "company_id = :company_id"),
    ("item_units", "item_id IN (SELECT id FROM items WHERE company_id = :company_id)"),
    ("item_pricing", "item_id IN (SELECT id FROM items WHERE company_id = :company_id)"),
    ("items", "company_id = :company_id"),
    ("suppliers", "company_id = :company_id"),
]


def run_clear(company_id: UUID, *, dry_run: bool = False) -> tuple[bool, list[str]]:
    """
    Delete all company-specific transactional and master data (items, inventory, sales, purchases, etc.).

    Uses its own connection and commits. Safe to call from API or CLI.

    Returns:
        (success: bool, messages: list[str])
    """
    params = {"company_id": str(company_id)}
    messages: list[str] = []
    with engine.connect() as conn:
        for table, where in DELETIONS:
            sql = f'DELETE FROM "{table}" WHERE {where}'
            if dry_run:
                count_sql = f'SELECT COUNT(*) FROM "{table}" WHERE {where}'
                try:
                    row = conn.execute(text(count_sql), params).scalar()
                    messages.append(f"[dry-run] {table}: would delete {row} row(s)")
                except Exception as e:
                    messages.append(f"[dry-run] {table}: error {e}")
                continue
            try:
                result = conn.execute(text(sql), params)
                messages.append(f"{table}: deleted {result.rowcount} row(s)")
            except Exception as e:
                logger.exception("Clear for reimport failed at table %s", table)
                messages.append(f"{table}: FAILED - {e}")
                conn.rollback()
                return False, messages
        if not dry_run:
            conn.commit()
    return True, messages
