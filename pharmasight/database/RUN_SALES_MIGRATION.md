# Sales Invoice Status Migration

## Issue
If you're seeing a 500 error when loading sales invoices, it's because the database migration hasn't been run yet.

## Solution

Run the migration script to add the new columns:

```sql
-- Run this SQL script on your database
\i database/add_sales_invoice_status_and_payments.sql
```

Or if using psql directly:

```bash
psql -U your_username -d your_database -f database/add_sales_invoice_status_and_payments.sql
```

## What the Migration Does

1. Adds `status` column to `sales_invoices` (DRAFT, BATCHED, PAID, CANCELLED)
2. Adds batching tracking fields (`batched`, `batched_by`, `batched_at`)
3. Adds cashier approval fields (`cashier_approved`, `approved_by`, `approved_at`)
4. Adds `item_name` and `item_code` to `sales_invoice_items`
5. Creates `invoice_payments` table for split payments
6. Updates existing invoices to have appropriate status based on their current state

## After Migration

The sales invoices page should work correctly, and you'll be able to:
- See status badges (DRAFT, BATCHED, PAID)
- Batch invoices to reduce stock
- Collect split payments
- View item names and codes properly
