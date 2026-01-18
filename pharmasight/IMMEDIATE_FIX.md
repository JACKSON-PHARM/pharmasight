# ⚡ IMMEDIATE FIX: Backend Timeout

## ✅ What I Just Fixed

1. ✅ Installed missing `email-validator` package
2. ✅ Backend is now running (health check works)
3. ✅ Added database connection timeout (10 seconds)
4. ✅ Added query timeout (30 seconds)
5. ✅ Improved error handling in startup endpoint

## 🚨 CRITICAL: Update Database Function FIRST

**Before trying setup, you MUST update the database function in Supabase:**

1. **Go to Supabase Dashboard** → SQL Editor
2. **Copy and paste this entire SQL** (from `IMPORTANT_UPDATE_DATABASE.md` or below)
3. **Run it**

```sql
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
```

**✅ This MUST be done before setup!**

## 🚀 Try Setup Now

### Step 1: Hard Refresh Browser
- Press `Ctrl + Shift + R` in browser

### Step 2: Complete Setup Form
1. **Company**: Fill all fields
2. **Admin User**: 
   - Generate UUID: Run `[guid]::NewGuid().ToString()` in PowerShell
   - Fill email, name, phone
3. **Branch**: 
   - **Leave Branch Code EMPTY** (will auto-generate as "BR001")
   - Fill name, address, phone

### Step 3: Click "Complete Setup"

## ✅ What Should Happen

- ✅ No timeout errors
- ✅ Success message
- ✅ Company, admin user, and branch created
- ✅ Branch code auto-generated as "BR001"
- ✅ Document sequences initialized (CS001, CN001, etc.)

## 🔍 If Still Timing Out

**Check backend PowerShell window** - it should show errors if database connection fails.

**Common issues:**
1. **Database function not updated** → Run SQL above
2. **Database connection failed** → Check `.env` file `DATABASE_URL`
3. **Tables don't exist** → Run `database/schema.sql` in Supabase

**Quick test - try this in PowerShell:**
```powershell
$uuid = [guid]::NewGuid().ToString()
$body = '{"company":{"name":"Test","currency":"KES","timezone":"Africa/Nairobi"},"admin_user":{"id":"' + $uuid + '","email":"test@test.com","full_name":"Test"},"branch":{"name":"Test Branch","code":null,"address":"Test"}}'
Invoke-RestMethod -Uri "http://localhost:8000/api/startup" -Method POST -ContentType "application/json" -Body $body -TimeoutSec 60
```

If this works, the backend is fine and the frontend should work too!

