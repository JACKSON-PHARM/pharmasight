-- Widen session_code to allow generated codes (e.g. ST-35DB8EE2 or ST-MAR25A).
-- Run this on tenant DBs where stock_take_sessions.session_code is still VARCHAR(10).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'stock_take_sessions'
          AND column_name = 'session_code'
    ) THEN
        ALTER TABLE stock_take_sessions
            ALTER COLUMN session_code TYPE VARCHAR(20);
    END IF;
END $$;
