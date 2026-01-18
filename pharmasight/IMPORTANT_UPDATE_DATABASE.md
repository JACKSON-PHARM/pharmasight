# ⚠️ IMPORTANT: Update Database Function

## What Changed

I've updated the code to:
1. **Auto-generate branch code** as "BR001" if first branch (you can leave it empty)
2. **Simplified document numbering**:
   - Cash Sale: **CS001**, CS002, CS003...
   - Credit Note: **CN001**, CN002, CN003...
   - GRN: GRN001, GRN002...

## ⚠️ YOU MUST UPDATE YOUR DATABASE

The database function `get_next_document_number()` needs to be updated in your Supabase database.

### Step 1: Go to Supabase SQL Editor

### Step 2: Run This SQL

```sql
-- Update document numbering function (SIMPLIFIED FORMAT)
CREATE OR REPLACE FUNCTION get_next_document_number(
    p_company_id UUID,
    p_branch_id UUID,
    p_document_type VARCHAR,
    p_prefix VARCHAR DEFAULT NULL
) RETURNS VARCHAR AS $$
DECLARE
    v_year INTEGER;
    v_current_number INTEGER;
    v_next_number INTEGER;
    v_document_no VARCHAR;
    v_branch_code VARCHAR;
BEGIN
    v_year := EXTRACT(YEAR FROM CURRENT_DATE);
    
    -- Get branch code (for validation only)
    SELECT code INTO v_branch_code
    FROM branches
    WHERE id = p_branch_id;
    
    IF v_branch_code IS NULL OR v_branch_code = '' THEN
        RAISE EXCEPTION 'Branch code is required. Branch ID: %', p_branch_id;
    END IF;
    
    -- Determine prefix if not provided (simplified format)
    IF p_prefix IS NULL THEN
        CASE p_document_type
            WHEN 'SALES_INVOICE' THEN p_prefix := 'CS';  -- Cash Sale
            WHEN 'GRN' THEN p_prefix := 'GRN';
            WHEN 'CREDIT_NOTE' THEN p_prefix := 'CN';    -- Credit Note
            WHEN 'PAYMENT' THEN p_prefix := 'PAY';
            ELSE p_prefix := p_document_type;
        END CASE;
    END IF;
    
    -- Get or create sequence record (branch-specific but simple format)
    INSERT INTO document_sequences (company_id, branch_id, document_type, prefix, current_number, year)
    VALUES (p_company_id, p_branch_id, p_document_type, p_prefix, 0, v_year)
    ON CONFLICT (company_id, branch_id, document_type, year)
    DO UPDATE SET current_number = document_sequences.current_number + 1
    RETURNING current_number INTO v_next_number;
    
    -- Format document number: {PREFIX}{NUMBER} (e.g., CS001, CN001, CS002, etc.)
    v_document_no := p_prefix || LPAD(v_next_number::TEXT, 3, '0');
    
    RETURN v_document_no;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_next_document_number IS 'Generates simplified document numbers. Format: CS001 (Cash Sale), CN001 (Credit Note), etc. Branch-specific sequences.';
```

### Step 3: Restart Backend

After updating the database function, restart your backend:

```powershell
# Stop backend
Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like "*pharmasight*"} | Stop-Process -Force

# Start backend
cd C:\PharmaSight\pharmasight
.\start.bat
```

## What's Fixed

✅ **Branch Code Auto-Generation**: 
   - If you leave branch code empty in setup wizard, it will auto-generate as "BR001"
   - Subsequent branches: BR002, BR003, etc.

✅ **Simplified Document Numbers**:
   - Cash Sale: CS001, CS002, CS003...
   - Credit Note: CN001, CN002, CN003...
   - GRN: GRN001, GRN002...

✅ **Branch Code Optional**: 
   - You can leave it empty in the setup form
   - It will auto-generate

## Test After Update

1. **Clear browser cache** (Ctrl + Shift + R)
2. **Go to setup wizard**: `http://localhost:3000/#setup`
3. **Fill form**:
   - Company details
   - Admin user (generate UUID)
   - **Branch**: Leave "Branch Code" empty (will auto-generate as BR001)
4. **Click "Complete Setup"**

If it still times out, check the backend PowerShell window for errors!

