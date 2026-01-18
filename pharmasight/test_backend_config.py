"""
Test if backend can read .env file correctly
"""
import os
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

# Try to load config
try:
    print("=" * 60)
    print("Testing Backend Configuration")
    print("=" * 60)
    
    # Check .env file location
    root_env = Path(__file__).parent / ".env"
    backend_env = backend_dir / ".env"
    
    print(f"\nRoot .env exists: {root_env.exists()}")
    print(f"Backend .env exists: {backend_env.exists()}")
    
    # Load .env manually
    from dotenv import load_dotenv
    if root_env.exists():
        load_dotenv(root_env)
        print(f"[OK] Loaded .env from: {root_env}")
    elif backend_env.exists():
        load_dotenv(backend_env)
        print(f"[OK] Loaded .env from: {backend_env}")
    else:
        print("[ERROR] No .env file found!")
        sys.exit(1)
    
    # Check DATABASE_URL
    database_url = os.getenv("DATABASE_URL", "")
    print(f"\nDATABASE_URL present: {bool(database_url)}")
    if database_url:
        # Mask password
        masked = database_url.split("@")[0].split(":")[0] + ":***@" + "@".join(database_url.split("@")[1:])
        print(f"DATABASE_URL: {masked[:80]}...")
        print(f"Contains 'pooler': {'pooler' in database_url.lower()}")
        print(f"Contains '5432': {'5432' in database_url}")
    
    # Try to import config
    print("\nImporting backend config...")
    from app.config import settings
    
    print(f"[OK] Config loaded successfully!")
    print(f"Database connection string: {settings.database_connection_string[:80]}...")
    print(f"Contains 'pooler': {'pooler' in settings.database_connection_string.lower()}")
    
    # Try to create engine (with timeout)
    print("\nTesting database connection (10 second timeout)...")
    from sqlalchemy import create_engine, text
    import signal
    
    engine = create_engine(
        settings.database_connection_string,
        connect_args={
            "connect_timeout": 10,
        },
        pool_pre_ping=True
    )
    
    print("[OK] Engine created")
    print("Attempting connection...")
    
    with engine.connect() as conn:
        print("[OK] Connection successful!")
        result = conn.execute(text("SELECT 1"))
        print(f"[OK] Query successful: {result.scalar()}")
    
    print("\n[SUCCESS] Backend configuration is correct!")
    
except Exception as e:
    print(f"\n[ERROR] Configuration test failed!")
    print(f"Error: {type(e).__name__}: {str(e)}")
    import traceback
    print("\nTraceback:")
    print(traceback.format_exc())
    sys.exit(1)

print("\n" + "=" * 60)
