"""
Run a SQL migration script on the master database
Usage: python run_migration.py <migration_file.sql>
"""
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database_master import master_engine

def run_migration(migration_file: Path):
    """Run a migration SQL file on the master database"""
    if not migration_file.exists():
        print(f"ERROR: Migration file not found: {migration_file}")
        return False
    
    print(f"Running migration: {migration_file.name}")
    
    with open(migration_file, 'r', encoding='utf-8') as f:
        migration_sql = f.read()
    
    try:
        with master_engine.connect() as conn:
            # Execute the entire migration as a single transaction
            # This handles multi-line statements properly
            conn.execute(text(migration_sql))
            conn.commit()
            
            print(f"SUCCESS: Migration '{migration_file.name}' applied successfully!")
            return True
    
    except Exception as e:
        print(f"ERROR: Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_migration.py <migration_file.sql>")
        print("\nExample:")
        print("  python run_migration.py ../database/add_tenant_phone.sql")
        sys.exit(1)
    
    migration_path = Path(sys.argv[1])
    if not migration_path.is_absolute():
        # Make relative to backend directory parent (pharmasight root)
        migration_path = (backend_dir.parent / migration_path).resolve()
    
    success = run_migration(migration_path)
    sys.exit(0 if success else 1)
