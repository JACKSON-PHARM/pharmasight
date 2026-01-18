"""
Test if backend can start with the new database connection
"""
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# Load environment from parent directory
from dotenv import load_dotenv
load_dotenv('.env')

print("=" * 60)
print("Testing Backend Startup")
print("=" * 60)

try:
    print("\n1. Loading config...")
    from app.config import settings
    
    print(f"   DATABASE_URL: {settings.DATABASE_URL[:60]}...")
    print(f"   Database connection string: {settings.database_connection_string[:60]}...")
    
    print("\n2. Testing database connection...")
    from app.database import engine
    
    with engine.connect() as conn:
        from sqlalchemy import text
        result = conn.execute(text("SELECT 1"))
        print("   [OK] Database connection successful!")
    
    print("\n3. Testing FastAPI app import...")
    from app.main import app
    print("   [OK] FastAPI app imported successfully!")
    
    print("\n[SUCCESS] Backend can start with current configuration!")
    print("\nNext: Restart the backend server (python start.py)")
    
except Exception as e:
    print(f"\n[ERROR] Backend startup failed!")
    print(f"Error: {type(e).__name__}: {str(e)}")
    import traceback
    print("\nTraceback:")
    print(traceback.format_exc())

print("\n" + "=" * 60)
