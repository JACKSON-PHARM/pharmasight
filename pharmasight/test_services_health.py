"""
Service Health Check Script
Tests all critical services to establish recovery point
"""
import requests
import json
import sys
from datetime import datetime

API_BASE = "http://localhost:8000"
TIMEOUT = 5

def test_endpoint(method, endpoint, description, **kwargs):
    """Test an API endpoint"""
    try:
        url = f"{API_BASE}{endpoint}"
        print(f"\n{'='*60}")
        print(f"Testing: {description}")
        print(f"Endpoint: {method} {endpoint}")
        print(f"{'='*60}")
        
        if method.upper() == "GET":
            response = requests.get(url, timeout=TIMEOUT, **kwargs)
        elif method.upper() == "POST":
            response = requests.post(url, timeout=TIMEOUT, **kwargs)
        else:
            print(f"❌ Unknown method: {method}")
            return False
        
        print(f"Status: {response.status_code}")
        
        if response.status_code < 400:
            try:
                data = response.json()
                print(f"Response: {json.dumps(data, indent=2, default=str)[:500]}")
                print(f"✅ SUCCESS")
                return True
            except:
                print(f"Response: {response.text[:200]}")
                print(f"✅ SUCCESS (non-JSON)")
                return True
        else:
            print(f"Response: {response.text[:200]}")
            print(f"❌ FAILED")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ CONNECTION ERROR - Backend not running on {API_BASE}")
        return False
    except requests.exceptions.Timeout:
        print(f"❌ TIMEOUT - Backend not responding")
        return False
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return False

def main():
    print("\n" + "="*60)
    print("PHARMASIGHT SERVICE HEALTH CHECK")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    results = {}
    
    # 1. Health Check
    results['health'] = test_endpoint("GET", "/health", "Backend Health Check")
    
    if not results['health']:
        print("\n" + "="*60)
        print("❌ BACKEND IS NOT RUNNING")
        print("Please start the backend server first:")
        print("  cd pharmasight/backend")
        print("  python -m uvicorn app.main:app --reload --port 8000")
        print("="*60)
        sys.exit(1)
    
    # 2. Root endpoint
    results['root'] = test_endpoint("GET", "/", "Root Endpoint")
    
    # 3. Items API - List (requires company_id)
    # Note: This will fail without valid company_id, but tests endpoint exists
    print("\n" + "="*60)
    print("NOTE: Items/Suppliers endpoints require valid company_id")
    print("Testing endpoint structure only...")
    print("="*60)
    
    # 4. Items Search Endpoint (requires q and company_id)
    # This will return 422 if params missing, but confirms endpoint exists
    results['items_search'] = test_endpoint(
        "GET", 
        "/api/items/search?q=test&company_id=00000000-0000-0000-0000-000000000000", 
        "Items Search Endpoint (structure test)"
    )
    
    # 5. Suppliers Search Endpoint
    results['suppliers_search'] = test_endpoint(
        "GET",
        "/api/suppliers/search?q=test&company_id=00000000-0000-0000-0000-000000000000",
        "Suppliers Search Endpoint (structure test)"
    )
    
    # 6. Inventory Endpoint (requires item_id and branch_id)
    results['inventory_stock'] = test_endpoint(
        "GET",
        "/api/inventory/stock/00000000-0000-0000-0000-000000000000/00000000-0000-0000-0000-000000000000",
        "Inventory Stock Endpoint (structure test)"
    )
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\nTotal: {passed}/{total} passed")
    
    if passed == total:
        print("\n✅ ALL CRITICAL SERVICES ARE OPERATIONAL")
    else:
        print("\n⚠️  SOME SERVICES NEED ATTENTION")
        print("Note: Some failures may be expected if:")
        print("  - No valid company_id/branch_id in database")
        print("  - Database not initialized")
        print("  - Missing environment variables")

if __name__ == "__main__":
    main()
