-- Migration: Update Supplier Invoice numbering to use SPV{BRANCH_CODE}-{NUMBER} format
-- Format: SPV001-000001, SPV001-000002, etc. (where 001 is branch code)

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
    
    -- Get branch code (required for supplier invoices)
    SELECT code INTO v_branch_code
    FROM branches
    WHERE id = p_branch_id;
    
    IF v_branch_code IS NULL OR v_branch_code = '' THEN
        RAISE EXCEPTION 'Branch code is required. Branch ID: %', p_branch_id;
    END IF;
    
    -- Determine prefix if not provided
    IF p_prefix IS NULL THEN
        CASE p_document_type
            WHEN 'SALES_INVOICE' THEN p_prefix := 'CS';  -- Cash Sale
            WHEN 'GRN' THEN p_prefix := 'GRN';
            WHEN 'CREDIT_NOTE' THEN p_prefix := 'CN';    -- Credit Note
            WHEN 'PAYMENT' THEN p_prefix := 'PAY';
            WHEN 'SUPPLIER_INVOICE' THEN 
                -- For supplier invoices, use SPV prefix with branch code
                -- Format will be: SPV{BRANCH_CODE}-{NUMBER}
                p_prefix := 'SPV' || v_branch_code;
            ELSE p_prefix := p_document_type;
        END CASE;
    END IF;
    
    -- Get or create sequence record (branch-specific)
    -- Check if sequence exists, if not create with 0, then increment
    SELECT current_number INTO v_current_number
    FROM document_sequences
    WHERE company_id = p_company_id 
      AND branch_id = p_branch_id 
      AND document_type = p_document_type 
      AND year = v_year;
    
    IF v_current_number IS NULL THEN
        -- First time: create sequence starting at 0, will use 1 for first document
        INSERT INTO document_sequences (company_id, branch_id, document_type, prefix, current_number, year)
        VALUES (p_company_id, p_branch_id, p_document_type, p_prefix, 0, v_year);
        v_next_number := 1;
        -- Update to 1 for next time
        UPDATE document_sequences 
        SET current_number = 1 
        WHERE company_id = p_company_id 
          AND branch_id = p_branch_id 
          AND document_type = p_document_type 
          AND year = v_year;
    ELSE
        -- Increment existing sequence
        UPDATE document_sequences 
        SET current_number = current_number + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE company_id = p_company_id 
          AND branch_id = p_branch_id 
          AND document_type = p_document_type 
          AND year = v_year
        RETURNING current_number INTO v_next_number;
    END IF;
    
    -- Format document number based on document type
    IF p_document_type = 'SUPPLIER_INVOICE' THEN
        -- Format: SPV{BRANCH_CODE}-{6-digit number} (e.g., SPV001-000001)
        v_document_no := p_prefix || '-' || LPAD(v_next_number::TEXT, 6, '0');
    ELSE
        -- Other document types: {PREFIX}{3-digit number} (e.g., CS001, CN001)
        v_document_no := p_prefix || LPAD(v_next_number::TEXT, 3, '0');
    END IF;
    
    RETURN v_document_no;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_next_document_number IS 'Generates document numbers. Supplier Invoices: SPV{BRANCH_CODE}-{NUMBER} (e.g., SPV001-000001). Other documents: {PREFIX}{NUMBER} (e.g., CS001, CN001). Branch-specific sequences.';
