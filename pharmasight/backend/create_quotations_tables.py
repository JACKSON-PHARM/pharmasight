"""
Script to create quotations tables in the database
Run this script to add the quotations and quotation_items tables
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine
from sqlalchemy import text

def create_quotations_tables():
    """Create quotations tables"""
    sql_file = os.path.join(os.path.dirname(__file__), '..', 'database', 'add_quotations_tables.sql')
    
    if not os.path.exists(sql_file):
        print(f"ERROR: SQL file not found at {sql_file}")
        return False
    
    with open(sql_file, 'r') as f:
        sql_content = f.read()
    
    try:
        with engine.connect() as conn:
            # Execute the SQL
            conn.execute(text(sql_content))
            conn.commit()
            print("[SUCCESS] Quotations tables created successfully!")
            return True
    except Exception as e:
        print(f"[ERROR] Error creating tables: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Creating quotations tables...")
    success = create_quotations_tables()
    if success:
        print("\n[SUCCESS] Migration completed successfully!")
        print("You can now restart your backend server.")
    else:
        print("\n[ERROR] Migration failed. Please check the error above.")
        sys.exit(1)
