-- Sales invoice numbers: format SD{BRANCH_CODE}-{NUMBER} to match PO style (PO{BRANCH_CODE}-{NUMBER})
-- Example: SD-MAIN-000001, SD-001-000002

CREATE OR REPLACE FUNCTION get_next_document_number(
    p_company_id UUID,
    p_branch_id UUID,
    p_document_type VARCHAR,
    p_prefix VARCHAR DEFAULT NULL
) RETURNS VARCHAR AS $$
DECLARE
    v_year INTEGER;
    v_next_number INTEGER;
    v_document_no VARCHAR;
    v_branch_code VARCHAR;
BEGIN
    v_year := EXTRACT(YEAR FROM CURRENT_DATE);
    SELECT TRIM(code) INTO v_branch_code FROM branches WHERE id = p_branch_id;
    IF v_branch_code IS NULL OR v_branch_code = '' THEN
        RAISE EXCEPTION 'Branch code is required. Branch ID: %', p_branch_id;
    END IF;
    IF p_prefix IS NULL THEN
        CASE p_document_type
            WHEN 'SALES_INVOICE' THEN p_prefix := 'CS';  -- used only for sequence key; output format overridden below
            WHEN 'GRN' THEN p_prefix := 'GRN';
            WHEN 'CREDIT_NOTE' THEN p_prefix := 'CN';
            WHEN 'PAYMENT' THEN p_prefix := 'PAY';
            WHEN 'SUPPLIER_INVOICE' THEN p_prefix := 'SUP-INV';
            ELSE p_prefix := p_document_type;
        END CASE;
    END IF;
    INSERT INTO document_sequences (company_id, branch_id, document_type, prefix, current_number, year)
    VALUES (p_company_id, p_branch_id, p_document_type, p_prefix, 0, v_year)
    ON CONFLICT (company_id, branch_id, document_type, year)
    DO UPDATE SET current_number = document_sequences.current_number + 1
    RETURNING current_number INTO v_next_number;

    IF p_document_type = 'SALES_INVOICE' THEN
        v_document_no := 'SD-' || v_branch_code || '-' || LPAD(v_next_number::TEXT, 6, '0');
    ELSE
        v_document_no := p_prefix || LPAD(v_next_number::TEXT, 3, '0');
    END IF;
    RETURN v_document_no;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_next_document_number IS 'Sales invoices: SD{BRANCH_CODE}-{NUMBER} (e.g. SD-MAIN-000001). Other types: {PREFIX}{NUMBER}. Branch-specific sequences.';
