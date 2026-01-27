-- =====================================================
-- VERIFY SESSION CODE COLUMN FIX
-- =====================================================
-- Run this to verify the migration was applied correctly
-- =====================================================

-- Check column length
SELECT 
    column_name, 
    data_type, 
    character_maximum_length 
FROM information_schema.columns 
WHERE table_name = 'stock_take_sessions' 
  AND column_name = 'session_code';

-- Expected result:
-- data_type: character varying
-- character_maximum_length: 20

-- Check if function exists and returns correct type
SELECT 
    p.proname as function_name,
    pg_catalog.pg_get_function_result(p.oid) as return_type
FROM pg_catalog.pg_proc p
LEFT JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE p.proname = 'generate_stock_take_session_code';

-- Test the function (should return a code like "ST-JAN25A")
SELECT generate_stock_take_session_code() as test_code, 
       LENGTH(generate_stock_take_session_code()) as code_length;

-- Expected: code_length should be 8 (for ST-JAN25A format) or less
