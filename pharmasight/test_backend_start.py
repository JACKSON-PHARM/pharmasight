"""
Quick test to see if backend can start
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

import sys
import io

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("Testing backend startup...")
print("=" * 50)

try:
    print("1. Testing imports...")
    from app.config import settings
    print("   [OK] Config imported")
    
    from app.main import app
    print("   [OK] App imported")
    
    print("\n2. Testing database connection...")
    from app.database import get_db
    db = next(get_db())
    print("   [OK] Database connection works")
    db.close()
    
    print("\n3. Testing CORS settings...")
    cors_origins = settings.cors_origins_list
    print(f"   [OK] CORS origins: {cors_origins}")
    
    print("\n" + "=" * 50)
    print("[SUCCESS] All checks passed! Backend should start successfully.")
    print("\nTo start backend manually:")
    print("  cd backend")
    print("  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
    
except Exception as e:
    print(f"\n[ERROR] {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

