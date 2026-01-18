"""
Test database connection
"""
import os
import sys
from sqlalchemy import create_engine, text

# Load environment
from dotenv import load_dotenv
load_dotenv('C:/PharmaSight/pharmasight/.env')

# Get database URL
database_url = os.getenv("DATABASE_URL", "")
if not database_url:
    # Build from components (fallback to Session Pooler)
    db_host = os.getenv("SUPABASE_DB_HOST", "aws-1-eu-west-1.pooler.supabase.com")
    db_port = os.getenv("SUPABASE_DB_PORT", "5432")
    db_name = os.getenv("SUPABASE_DB_NAME", "postgres")
    db_user = os.getenv("SUPABASE_DB_USER", "postgres.kwvkkbofubsjiwqlqakt")
    db_password = os.getenv("SUPABASE_DB_PASSWORD", "6iP.zRY6QyK8L*Z")
    database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

print("=" * 60)
print("Testing Database Connection")
print("=" * 60)
print(f"\nDatabase URL: {database_url[:50]}...")

try:
    print("\nCreating engine...")
    engine = create_engine(
        database_url,
        connect_args={
            "connect_timeout": 10,
        },
        pool_pre_ping=True
    )
    
    print("Connecting to database...")
    with engine.connect() as conn:
        print("Connection successful!")
        
        # Test query
        print("\nTesting query...")
        result = conn.execute(text("SELECT 1 as test"))
        row = result.fetchone()
        print(f"Query result: {row[0]}")
        
        # Check if user_roles table exists and has data
        print("\nChecking user_roles table...")
        result = conn.execute(text("SELECT COUNT(*) FROM user_roles"))
        count = result.scalar()
        print(f"user_roles count: {count}")
        
        if count == 0:
            print("\n[WARNING] user_roles table is empty!")
            print("This might cause startup to fail.")
            print("Run the seed data from schema.sql")
        else:
            print("\n[OK] user_roles table has data")
        
        # Check if companies table exists
        print("\nChecking companies table...")
        result = conn.execute(text("SELECT COUNT(*) FROM companies"))
        count = result.scalar()
        print(f"companies count: {count}")
        
    print("\n[SUCCESS] Database connection is working!")
    
except Exception as e:
    print(f"\n[ERROR] Database connection failed!")
    print(f"Error: {type(e).__name__}: {str(e)}")
    import traceback
    print("\nTraceback:")
    print(traceback.format_exc())

print("\n" + "=" * 60)
