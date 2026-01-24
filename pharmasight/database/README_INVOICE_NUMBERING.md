# Supplier Invoice Numbering - Explanation

## What is the "Next Document Generator"?

The "Next Document Generator" you see in Supabase is **NOT a separate database**. It's a **PostgreSQL function** (stored procedure) that lives in your **same database**. 

Think of it like a helper function that generates sequential document numbers automatically.

## How It Works

1. **Function Name**: `get_next_document_number()`
2. **Location**: Stored in your PostgreSQL database (same database as your tables)
3. **Purpose**: Generates unique, sequential invoice numbers in format: `SPV{BRANCH_CODE}-{NUMBER}`

## Why Invoices Might Not Have Numbers

If invoices created before don't have invoice numbers, it's because:
- They were created before the numbering system was implemented
- The migration script hasn't been run yet
- The migration script failed

## How to Fix Existing Invoices

### Option 1: Simple Direct Update (Recommended)
Run: `pharmasight/database/fix_existing_invoices_simple.sql`

This script:
- Directly assigns numbers to invoices without using the sequence function
- Uses `ROW_NUMBER()` to assign sequential numbers per branch
- Updates the sequence table afterward to keep future numbers correct

### Option 2: Using the Sequence Function
Run: `pharmasight/database/update_existing_invoices_with_numbers.sql`

**IMPORTANT**: Run `update_supplier_invoice_numbering.sql` FIRST to update the function!

## Migration Order

1. **First**: Update the function
   ```sql
   -- Run: update_supplier_invoice_numbering.sql
   ```

2. **Then**: Fix existing invoices
   ```sql
   -- Run: fix_existing_invoices_simple.sql (recommended)
   -- OR: update_existing_invoices_with_numbers.sql
   ```

## Verification

After running the migration, verify with:
```sql
SELECT 
    id,
    invoice_number,
    status,
    created_at
FROM purchase_invoices
WHERE invoice_number IS NULL 
   OR invoice_number = '' 
   OR invoice_number NOT LIKE 'SPV%';
```

If this returns no rows, all invoices have been updated!

## Troubleshooting

**Q: Why are invoice numbers still empty after running the script?**
A: 
- Check if the script actually ran (check Supabase logs)
- Verify branch codes exist for all invoices
- Make sure you ran the scripts in the correct order

**Q: Will this affect new invoices?**
A: No, new invoices will automatically get numbers when created (the function handles this).

**Q: Can I delete invoices without numbers?**
A: Yes, but it's better to update them with numbers to maintain data integrity.
