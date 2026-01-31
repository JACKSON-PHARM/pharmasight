"""
Setup script for master database
Run this to create the master database schema for tenant management
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database_master import master_engine, MasterBase
from app.config import settings

def setup_master_database():
    """Create master database schema"""
    print("Setting up master database...")
    
    # Read schema file
    schema_file = backend_dir.parent / "database" / "master_schema.sql"
    
    if not schema_file.exists():
        print(f"ERROR: Schema file not found: {schema_file}")
        return False
    
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    
    # Execute schema
    try:
        with master_engine.connect() as conn:
            # Split by semicolons and execute each statement
            statements = [s.strip() for s in schema_sql.split(';') if s.strip()]
            
            for statement in statements:
                if statement:
                    try:
                        conn.execute(text(statement))
                        conn.commit()
                    except Exception as e:
                        # Some statements might fail if they already exist (like extensions)
                        if "already exists" not in str(e).lower():
                            print(f"Warning: {str(e)}")
            
            print("✓ Master database schema created successfully!")
            return True
    
    except Exception as e:
        print(f"ERROR: Failed to create schema: {e}")
        return False


if __name__ == "__main__":
    success = setup_master_database()
    sys.exit(0 if success else 1)
