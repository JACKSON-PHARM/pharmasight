# Fix Sales Invoices Missing Columns

## Problem
The `sales_invoices` table is missing the `sales_type` column (and possibly `customer_phone`), causing document listing pages to fail with:
```
(psycopg2.errors.UndefinedColumn) column sales_invoices.sales_type does not exist
```

## Solution

Run the migration script to add the missing columns:

### Option 1: Using psql (Recommended)
```bash
cd c:\PharmaSight\pharmasight\database
psql -U postgres -d pharmasight -f fix_sales_invoice_columns.sql
```

### Option 2: Using Supabase Dashboard
1. Go to your Supabase project SQL Editor
2. Copy and paste the contents of `database/fix_sales_invoice_columns.sql`
3. Run the query

### Option 3: Quick SQL Commands
If you prefer to run individual commands:

```sql
-- Add customer_phone
ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);

-- Add sales_type
ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS sales_type VARCHAR(20) DEFAULT 'RETAIL';

-- Update existing records
UPDATE sales_invoices 
SET sales_type = 'RETAIL' 
WHERE sales_type IS NULL;
```

## Verification

After running the migration, verify the columns exist:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns 
WHERE table_name = 'sales_invoices' 
AND column_name IN ('customer_phone', 'sales_type');
```

You should see both columns listed.

## After Migration

1. **Restart your backend server** (if running)
2. **Refresh the frontend** - Sales Invoices page should now load correctly
3. **Test other document pages** - Quotations, Purchase Invoices, etc.

## Files Modified

- ✅ Created: `database/fix_sales_invoice_columns.sql` - Migration script
- ✅ Updated: `backend/app/api/sales.py` - Added eager loading for items
- ✅ Updated: `backend/app/api/quotations.py` - Added eager loading for items
- ✅ Updated: `backend/app/api/purchases.py` - Added eager loading for items
