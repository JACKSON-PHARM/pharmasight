"""
Test script to verify tenant API is working
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant

def test_tenants():
    """Test if tenants can be queried"""
    print("Testing tenant database connection...")
    
    db = MasterSessionLocal()
    try:
        # Count tenants
        count = db.query(Tenant).count()
        print(f"✓ Found {count} tenant(s) in database")
        
        # List all tenants
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            print(f"  - {tenant.name} ({tenant.subdomain}) - Status: {tenant.status}")
            print(f"    Email: {tenant.admin_email}")
            print(f"    ID: {tenant.id}")
        
        return True
    except Exception as e:
        print(f"✗ Error querying tenants: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = test_tenants()
    sys.exit(0 if success else 1)
