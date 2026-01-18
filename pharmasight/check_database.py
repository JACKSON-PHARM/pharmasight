#!/usr/bin/env python3
"""
Quick script to check if database tables exist
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from sqlalchemy import text
from app.database import engine

try:
    conn = engine.connect()
    result = conn.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('companies', 'branches', 'users', 'user_roles', 'user_branch_roles', 'items', 'inventory_ledger', 'document_sequences')
        ORDER BY table_name
    """))
    
    tables = [row[0] for row in result.fetchall()]
    
    # Check for trigger function
    trigger_check = conn.execute(text("""
        SELECT routine_name 
        FROM information_schema.routines 
        WHERE routine_schema = 'public' 
        AND routine_name = 'enforce_single_company'
    """))
    has_trigger = len(trigger_check.fetchall()) > 0
    
    conn.close()
    
    print(f"Found {len(tables)} core tables: {', '.join(tables) if tables else 'NONE'}")
    
    # Required tables for ONE COMPANY architecture
    required_tables = ['companies', 'branches', 'users', 'user_roles', 'user_branch_roles', 'document_sequences']
    missing = [t for t in required_tables if t not in tables]
    
    if missing:
        print(f"\n[ERROR] MISSING REQUIRED TABLES: {', '.join(missing)}")
        print("\n[WARNING] You need to run the updated database schema in Supabase!")
        print("   The schema has been updated to ONE COMPANY = ONE DATABASE architecture.")
        print("   Go to: Supabase SQL Editor")
        print("   Copy and run the SQL from: database/schema.sql")
        print("\n[NOTE] If you have an existing database, you may need to migrate data first.")
        sys.exit(1)
    else:
        print("\n[SUCCESS] All required tables exist!")
        if has_trigger:
            print("[SUCCESS] ONE COMPANY enforcement trigger is installed")
        else:
            print("[WARNING] ONE COMPANY enforcement trigger is missing (but tables exist)")
        sys.exit(0)
        
except Exception as e:
    print(f"[ERROR] Error checking database: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

