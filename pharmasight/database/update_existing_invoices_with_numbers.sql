-- Migration: Update existing supplier invoices without invoice numbers
-- This script assigns invoice numbers to invoices that were created before the numbering system was implemented
-- Format: SPV{BRANCH_CODE}-{NUMBER} (e.g., SPV001-000001)

-- First, ensure the get_next_document_number function is updated (run update_supplier_invoice_numbering.sql first)

-- Function to update invoices without invoice numbers
CREATE OR REPLACE FUNCTION update_invoices_without_numbers()
RETURNS TABLE(
    invoice_id UUID,
    old_invoice_number VARCHAR,
    new_invoice_number VARCHAR,
    branch_code VARCHAR
) AS $$
DECLARE
    v_invoice RECORD;
    v_new_number VARCHAR;
    v_branch_code VARCHAR;
    v_company_id UUID;
    v_branch_id UUID;
BEGIN
    -- Loop through all invoices that have NULL, empty, or invalid invoice numbers
    FOR v_invoice IN 
        SELECT 
            pi.id,
            pi.invoice_number,
            pi.company_id,
            pi.branch_id,
            pi.status,
            b.code as branch_code
        FROM purchase_invoices pi
        JOIN branches b ON b.id = pi.branch_id
        WHERE 
            pi.invoice_number IS NULL 
            OR pi.invoice_number = ''
            OR pi.invoice_number NOT LIKE 'SPV%'
            OR LENGTH(pi.invoice_number) < 10  -- Invalid format
        ORDER BY pi.created_at ASC  -- Process oldest first
    LOOP
        -- Skip if branch code is missing
        IF v_invoice.branch_code IS NULL OR v_invoice.branch_code = '' THEN
            RAISE WARNING 'Skipping invoice % - branch code is missing', v_invoice.id;
            CONTINUE;
        END IF;
        
        -- Generate new invoice number using the document service function
        -- Note: This will increment the sequence, so we need to be careful
        SELECT get_next_document_number(
            v_invoice.company_id,
            v_invoice.branch_id,
            'SUPPLIER_INVOICE',
            NULL
        ) INTO v_new_number;
        
        -- Update the invoice with the new number
        UPDATE purchase_invoices
        SET invoice_number = v_new_number
        WHERE id = v_invoice.id;
        
        -- Return the update information
        invoice_id := v_invoice.id;
        old_invoice_number := COALESCE(v_invoice.invoice_number, 'NULL');
        new_invoice_number := v_new_number;
        branch_code := v_invoice.branch_code;
        
        RETURN NEXT;
    END LOOP;
    
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- Run the update function and show results
DO $$
DECLARE
    v_result RECORD;
    v_count INTEGER := 0;
BEGIN
    RAISE NOTICE 'Starting update of invoices without invoice numbers...';
    
    FOR v_result IN SELECT * FROM update_invoices_without_numbers() LOOP
        v_count := v_count + 1;
        RAISE NOTICE 'Updated invoice %: % -> % (Branch: %)', 
            v_result.invoice_id, 
            v_result.old_invoice_number, 
            v_result.new_invoice_number,
            v_result.branch_code;
    END LOOP;
    
    RAISE NOTICE 'Update complete. Total invoices updated: %', v_count;
END $$;

-- Drop the temporary function
DROP FUNCTION IF EXISTS update_invoices_without_numbers();

-- Verify: Show any remaining invoices without proper invoice numbers
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

COMMENT ON TABLE purchase_invoices IS 'All supplier invoices must have invoice numbers in format SPV{BRANCH_CODE}-{NUMBER}';
