-- =====================================================
-- FORCE REBUILD SCHEMA - Development Only
-- Nuclear option: Drops EVERYTHING in public schema
-- USE ONLY IN DEVELOPMENT - WILL DELETE ALL DATA
-- =====================================================

-- Drop all objects in public schema (except extensions)
DO $$
DECLARE
    r RECORD;
BEGIN
    -- Drop all triggers
    FOR r IN (SELECT trigger_name, event_object_table, event_object_schema 
              FROM information_schema.triggers 
              WHERE event_object_schema = 'public') 
    LOOP
        BEGIN
            EXECUTE 'DROP TRIGGER IF EXISTS ' || quote_ident(r.trigger_name) || 
                    ' ON ' || quote_ident(r.event_object_schema) || '.' || 
                    quote_ident(r.event_object_table) || ' CASCADE';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Could not drop trigger %: %', r.trigger_name, SQLERRM;
        END;
    END LOOP;

    -- Drop all functions (EXCLUDE extension functions)
    FOR r IN (
        SELECT proname, oidvectortypes(proargtypes) as args
        FROM pg_proc p
        INNER JOIN pg_namespace n ON p.pronamespace = n.oid
        LEFT JOIN pg_depend d ON d.objid = p.oid AND d.deptype = 'e'
        LEFT JOIN pg_extension e ON d.refobjid = e.oid
        WHERE n.nspname = 'public' 
        AND e.oid IS NULL  -- Exclude functions that belong to extensions
    ) 
    LOOP
        BEGIN
            EXECUTE 'DROP FUNCTION IF EXISTS ' || quote_ident(r.proname) || 
                    '(' || r.args || ') CASCADE';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Could not drop function %: %', r.proname, SQLERRM;
        END;
    END LOOP;

    -- Drop all tables (CASCADE handles everything)
    FOR r IN (SELECT tablename 
              FROM pg_tables 
              WHERE schemaname = 'public') 
    LOOP
        BEGIN
            EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Could not drop table %: %', r.tablename, SQLERRM;
        END;
    END LOOP;

    -- Drop all sequences (EXCLUDE extension sequences)
    FOR r IN (
        SELECT sequence_name 
        FROM information_schema.sequences s
        LEFT JOIN pg_depend d ON d.objid = (s.sequence_schema||'.'||s.sequence_name)::regclass 
            AND d.deptype = 'e'
        LEFT JOIN pg_extension e ON d.refobjid = e.oid
        WHERE s.sequence_schema = 'public'
        AND e.oid IS NULL  -- Exclude sequences that belong to extensions
    ) 
    LOOP
        BEGIN
            EXECUTE 'DROP SEQUENCE IF EXISTS ' || quote_ident(r.sequence_name) || ' CASCADE';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Could not drop sequence %: %', r.sequence_name, SQLERRM;
        END;
    END LOOP;

    -- Drop all views
    FOR r IN (SELECT table_name 
              FROM information_schema.views 
              WHERE table_schema = 'public') 
    LOOP
        BEGIN
            EXECUTE 'DROP VIEW IF EXISTS ' || quote_ident(r.table_name) || ' CASCADE';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Could not drop view %: %', r.table_name, SQLERRM;
        END;
    END LOOP;

    RAISE NOTICE 'All objects in public schema dropped successfully';
END $$;

-- =====================================================
-- NEXT STEP: Run schema.sql to recreate everything
-- =====================================================
-- After running this script, execute: pharmasight/database/schema.sql
