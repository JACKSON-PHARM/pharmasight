-- =====================================================
-- ROLLBACK: Daily Order Book
-- Run only if you need to revert the Order Book feature.
-- =====================================================

-- Drop database function first (depends on tables)
DROP FUNCTION IF EXISTS auto_generate_order_book_entries(UUID, UUID);

-- Drop tables (order matters due to FKs)
DROP TABLE IF EXISTS order_book_history;
DROP TABLE IF EXISTS daily_order_book;

-- Verify
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_order_book') THEN
        RAISE NOTICE 'WARNING: daily_order_book still exists';
    ELSE
        RAISE NOTICE 'daily_order_book dropped';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'order_book_history') THEN
        RAISE NOTICE 'WARNING: order_book_history still exists';
    ELSE
        RAISE NOTICE 'order_book_history dropped';
    END IF;
END $$;
