# URGENT: Run Database Migration

## Problem
The application is trying to access database columns that don't exist yet, causing a 500 error.

## Solution
**You MUST run the migration script immediately:**

```bash
# Option 1: Using psql command line
psql -U your_username -d your_database_name -f database/add_sales_invoice_status_and_payments.sql

# Option 2: Using psql interactive
psql -U your_username -d your_database_name
\i database/add_sales_invoice_status_and_payments.sql
```

## What the Migration Adds
1. `status` column (DRAFT, BATCHED, PAID, CANCELLED)
2. `batched`, `batched_by`, `batched_at` columns
3. `cashier_approved`, `approved_by`, `approved_at` columns
4. `item_name` and `item_code` in `sales_invoice_items`
5. `customer_phone` column in `sales_invoices`
6. `invoice_payments` table for split payments

## After Running Migration
1. Restart your backend server
2. Refresh the frontend
3. The sales invoices page should work correctly

## If Migration Fails
Check the error message and ensure:
- You have proper database permissions
- The database connection is correct
- No other processes are locking the tables
