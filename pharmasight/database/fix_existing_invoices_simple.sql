-- Simple script to update existing invoices without invoice numbers
-- This directly assigns numbers without using the sequence function
-- Format: SPV{BRANCH_CODE}-{NUMBER}

-- Step 1: Check current state
SELECT 
    COUNT(*) as total_invoices,
    COUNT(CASE WHEN invoice_number IS NULL OR invoice_number = '' OR invoice_number NOT LIKE 'SPV%' THEN 1 END) as invalid_invoices
FROM purchase_invoices;

-- Step 2: Update invoices by branch, assigning sequential numbers
-- This uses a window function to assign numbers per branch
-- First, let's see what we're working with
SELECT 
    pi.id,
    pi.invoice_number as current_number,
    b.code as branch_code,
    pi.created_at
FROM purchase_invoices pi
JOIN branches b ON b.id = pi.branch_id
WHERE 
    (pi.invoice_number IS NULL 
     OR pi.invoice_number = '' 
     OR pi.invoice_number NOT LIKE 'SPV%'
     OR LENGTH(pi.invoice_number) < 10)
    AND b.code IS NOT NULL 
    AND b.code != ''
ORDER BY pi.branch_id, pi.created_at ASC;

-- Now update them
WITH numbered_invoices AS (
    SELECT 
        pi.id,
        pi.company_id,
        pi.branch_id,
        b.code as branch_code,
        pi.invoice_number,
        ROW_NUMBER() OVER (PARTITION BY pi.branch_id ORDER BY pi.created_at ASC) as row_num
    FROM purchase_invoices pi
    JOIN branches b ON b.id = pi.branch_id
    WHERE 
        (pi.invoice_number IS NULL 
         OR pi.invoice_number = '' 
         OR pi.invoice_number NOT LIKE 'SPV%'
         OR LENGTH(pi.invoice_number) < 10)
        AND b.code IS NOT NULL 
        AND b.code != ''
)
UPDATE purchase_invoices pi
SET invoice_number = 'SPV' || ni.branch_code || '-' || LPAD(ni.row_num::TEXT, 6, '0')
FROM numbered_invoices ni
WHERE pi.id = ni.id
RETURNING 
    pi.id,
    pi.invoice_number as new_invoice_number,
    ni.branch_code;

-- Step 3: Update the document_sequences table to reflect the highest number used
-- This ensures future invoices continue from the correct number
DO $$
DECLARE
    v_branch RECORD;
    v_max_number INTEGER;
    v_year INTEGER;
BEGIN
    v_year := EXTRACT(YEAR FROM CURRENT_DATE);
    
    -- For each branch, find the max invoice number and update sequence
    FOR v_branch IN 
        SELECT DISTINCT 
            pi.branch_id,
            pi.company_id,
            b.code as branch_code
        FROM purchase_invoices pi
        JOIN branches b ON b.id = pi.branch_id
        WHERE pi.invoice_number LIKE 'SPV%'
    LOOP
        -- Extract the highest number from existing invoices for this branch
        -- Pattern: SPV{BRANCH_CODE}-{NUMBER}
        -- Remove prefix 'SPV{BRANCH_CODE}-' and convert remainder to integer
        SELECT COALESCE(MAX(
            CAST(REPLACE(invoice_number, 'SPV' || v_branch.branch_code || '-', '') AS INTEGER)
        ), 0)
        INTO v_max_number
        FROM purchase_invoices
        WHERE branch_id = v_branch.branch_id
          AND invoice_number LIKE 'SPV' || v_branch.branch_code || '-%'
          AND REPLACE(invoice_number, 'SPV' || v_branch.branch_code || '-', '') ~ '^[0-9]+$';
        
        -- Update or insert sequence record
        INSERT INTO document_sequences (
            company_id, 
            branch_id, 
            document_type, 
            prefix, 
            current_number, 
            year
        )
        VALUES (
            v_branch.company_id,
            v_branch.branch_id,
            'SUPPLIER_INVOICE',
            'SPV' || v_branch.branch_code,
            v_max_number,
            v_year
        )
        ON CONFLICT (company_id, branch_id, document_type, year)
        DO UPDATE SET 
            current_number = GREATEST(document_sequences.current_number, v_max_number),
            updated_at = CURRENT_TIMESTAMP;
    END LOOP;
END $$;

-- Step 4: Verify all invoices now have proper numbers
SELECT 
    pi.id,
    pi.invoice_number,
    pi.status,
    b.code as branch_code,
    pi.created_at
FROM purchase_invoices pi
JOIN branches b ON b.id = pi.branch_id
WHERE 
    pi.invoice_number IS NULL 
    OR pi.invoice_number = '' 
    OR pi.invoice_number NOT LIKE 'SPV%'
    OR LENGTH(pi.invoice_number) < 10;

-- If the above query returns no rows, all invoices have been updated successfully!
