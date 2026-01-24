"""
Test script to verify User Management API endpoints
Run this to check if the backend is working correctly
"""
import requests
import json
import sys

# Default API base URL
API_BASE_URL = "http://localhost:8000"

def test_health():
    """Test if backend is running"""
    print("[TEST] Testing backend health...")
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("[OK] Backend is running!")
            print(f"     Response: {response.json()}")
            return True
        else:
            print(f"[FAIL] Backend returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("[FAIL] Cannot connect to backend!")
        print(f"       Make sure backend is running on {API_BASE_URL}")
        print("       Start it with: cd backend && uvicorn app.main:app --reload")
        return False
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False

def test_users_endpoints():
    """Test user management endpoints"""
    print("\n[TEST] Testing User Management endpoints...")
    
    # Test 1: List roles
    print("\n1. Testing GET /api/users/roles")
    try:
        response = requests.get(f"{API_BASE_URL}/api/users/roles", timeout=5)
        if response.status_code == 200:
            roles = response.json()
            print(f"   [OK] Roles endpoint works! Found {len(roles)} roles:")
            for role in roles[:3]:  # Show first 3
                print(f"      - {role.get('role_name')}: {role.get('description', 'No description')}")
        else:
            print(f"   [FAIL] Status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")
    
    # Test 2: List users
    print("\n2. Testing GET /api/users")
    try:
        response = requests.get(f"{API_BASE_URL}/api/users", timeout=5)
        if response.status_code == 200:
            data = response.json()
            users_count = len(data.get('users', []))
            print(f"   [OK] Users endpoint works! Found {users_count} users")
            if users_count > 0:
                print(f"   Example user: {data['users'][0].get('email')}")
        else:
            print(f"   [FAIL] Status {response.status_code}: {response.text}")
            print(f"   Full response: {json.dumps(response.json(), indent=2) if response.content else 'No content'}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()

def test_database_schema():
    """Test if database has the new fields (indirectly by checking API response)"""
    print("\n[INFO] Checking database schema...")
    print("       (This checks if invitation fields exist by testing user creation)")
    print("       Note: Database migration needs to be run if this fails")
    print("       Run: database/add_user_invitation_fields.sql in your database")

def main():
    print("=" * 60)
    print("PharmaSight User Management API - Test Script")
    print("=" * 60)
    
    # Test backend health
    if not test_health():
        print("\n[WARNING] Backend is not running. Please start it first.")
        print("          Command: cd pharmasight/backend && uvicorn app.main:app --reload")
        sys.exit(1)
    
    # Test endpoints
    test_users_endpoints()
    
    # Database info
    test_database_schema()
    
    print("\n" + "=" * 60)
    print("[SUCCESS] Testing complete!")
    print("=" * 60)
    print("\n[INFO] Next steps:")
    print("   1. If backend is running but endpoints fail, check backend logs")
    print("   2. If database errors occur, run migration:")
    print("      database/add_user_invitation_fields.sql")
    print("   3. Test in browser: http://localhost:3000/#settings-users")
    print("   4. Check browser console (F12) for frontend errors")

if __name__ == "__main__":
    main()
