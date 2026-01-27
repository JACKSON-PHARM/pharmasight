-- =====================================================
-- FIX STOCK TAKE SESSION CODE COLUMN LENGTH
-- =====================================================
-- The session_code column was created as VARCHAR(6) but needs to be VARCHAR(10)
-- to accommodate codes like "ST-MAR25A" (8-9 characters)
-- =====================================================

-- Alter the column to allow longer codes (VARCHAR(20) for safety margin)
ALTER TABLE stock_take_sessions 
    ALTER COLUMN session_code TYPE VARCHAR(20);

-- Update the function to ensure codes never exceed 20 characters
CREATE OR REPLACE FUNCTION generate_stock_take_session_code()
RETURNS VARCHAR(20) AS $$
DECLARE
    v_date_prefix VARCHAR(6);
    v_suffix CHAR(1);
    v_code VARCHAR(20);
    v_exists BOOLEAN;
    v_suffix_num INTEGER := 0;
BEGIN
    -- Format: ST-{MON}{DAY}{SUFFIX}
    -- e.g., ST-MAR25A, ST-MAR25B, etc.
    -- MON = 3 chars, DD = 2 chars, so "ST-MAR25" = 7 chars, + suffix = 8 chars total
    v_date_prefix := 'ST-' || UPPER(TO_CHAR(CURRENT_DATE, 'MON')) || TO_CHAR(CURRENT_DATE, 'DD');
    
    -- Try A, B, C, etc. until we find a unique code
    LOOP
        v_suffix := CHR(65 + (v_suffix_num % 26)); -- A-Z
        v_code := v_date_prefix || v_suffix;
        
        -- Ensure code doesn't exceed 20 characters (should be 8, but safety check)
        IF LENGTH(v_code) > 20 THEN
            v_code := LEFT(v_code, 20);
        END IF;
        
        -- Check if code exists
        SELECT EXISTS(SELECT 1 FROM stock_take_sessions WHERE session_code = v_code) INTO v_exists;
        
        IF NOT v_exists THEN
            RETURN v_code;
        END IF;
        
        v_suffix_num := v_suffix_num + 1;
        
        -- Safety: prevent infinite loop (max 26 codes per day)
        IF v_suffix_num >= 26 THEN
            -- Fallback: use shorter timestamp format (ST-012522 = 8 chars)
            v_code := 'ST-' || TO_CHAR(CURRENT_TIMESTAMP, 'MMDDHH');
            -- Ensure it's max 20 chars
            IF LENGTH(v_code) > 20 THEN
                v_code := LEFT(v_code, 20);
            END IF;
            RETURN v_code;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION generate_stock_take_session_code() IS 'Generates unique stock take session codes in format ST-MAR25A (max 20 characters)';
