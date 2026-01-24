-- Migration: Add SUPPLIER_INVOICE support to get_next_document_number function

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
            WHEN 'SUPPLIER_INVOICE' THEN p_prefix := 'SUP-INV';  -- Supplier Invoice
            ELSE p_prefix := p_document_type;
        END CASE;
    END IF;
    
    -- Get or create sequence record (branch-specific but simple format)
    INSERT INTO document_sequences (company_id, branch_id, document_type, prefix, current_number, year)
    VALUES (p_company_id, p_branch_id, p_document_type, p_prefix, 0, v_year)
    ON CONFLICT (company_id, branch_id, document_type, year)
    DO UPDATE SET current_number = document_sequences.current_number + 1
    RETURNING current_number INTO v_next_number;
    
    -- Format document number: {PREFIX}{NUMBER} (e.g., CS001, CN001, CS002, SUP-INV001, etc.)
    v_document_no := p_prefix || LPAD(v_next_number::TEXT, 3, '0');
    
    RETURN v_document_no;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_next_document_number IS 'Generates simplified document numbers. Format: CS001 (Cash Sale), CN001 (Credit Note), SUP-INV001 (Supplier Invoice), etc. Branch-specific sequences.';
