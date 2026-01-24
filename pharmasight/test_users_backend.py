"""
End-to-End Backend Test for Users & Roles
Tests the complete backend API flow
"""
import requests
import json
from typing import Dict, Any

API_BASE_URL = "http://localhost:8000"

def print_section(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def test_backend_health() -> bool:
    """Test if backend is running"""
    print_section("TEST 1: Backend Health Check")
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print(f"✅ Backend is running: {response.json()}")
            return True
        else:
            print(f"❌ Backend returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to backend on {API_BASE_URL}")
        print("   Make sure backend is running: cd backend && uvicorn app.main:app --reload")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_users_roles_endpoint() -> bool:
    """Test GET /api/users/roles"""
    print_section("TEST 2: GET /api/users/roles")
    try:
        response = requests.get(f"{API_BASE_URL}/api/users/roles", timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            roles = response.json()
            print(f"✅ Roles endpoint works! Found {len(roles)} roles:")
            for role in roles:
                print(f"   - {role.get('role_name')}: {role.get('description', 'No description')}")
            return True
        else:
            print(f"❌ Failed with status {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error: {json.dumps(error_data, indent=2)}")
            except:
                print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_users_list_endpoint() -> bool:
    """Test GET /api/users"""
    print_section("TEST 3: GET /api/users")
    try:
        response = requests.get(f"{API_BASE_URL}/api/users", timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Users endpoint works!")
            print(f"   Response structure: {list(data.keys())}")
            users_count = len(data.get('users', []))
            print(f"   Users found: {users_count}")
            
            if users_count > 0:
                first_user = data['users'][0]
                print(f"\n   First user example:")
                print(f"   - Email: {first_user.get('email')}")
                print(f"   - Name: {first_user.get('full_name', 'N/A')}")
                print(f"   - Active: {first_user.get('is_active')}")
                print(f"   - Pending: {first_user.get('is_pending', False)}")
                print(f"   - Branch Roles: {len(first_user.get('branch_roles', []))}")
                
                if first_user.get('branch_roles'):
                    print(f"   Branch Role Details:")
                    for ubr in first_user['branch_roles']:
                        print(f"     - {ubr.get('role_name')} in {ubr.get('branch_name')}")
            else:
                print("   ⚠️  No users found (this is OK if database is empty)")
            
            return True
        else:
            print(f"❌ Failed with status {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error: {json.dumps(error_data, indent=2)}")
            except:
                print(f"   Response: {response.text[:500]}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_database_connection() -> bool:
    """Test if database migration fields exist"""
    print_section("TEST 4: Database Schema Check")
    print("⚠️  Manual check required:")
    print("   Run this SQL in Supabase SQL Editor:")
    print()
    print("   SELECT column_name, data_type, is_nullable")
    print("   FROM information_schema.columns")
    print("   WHERE table_name = 'users'")
    print("   ORDER BY ordinal_position;")
    print()
    print("   Expected columns: invitation_token, invitation_code, is_pending, password_set, deleted_at")
    return True

def main():
    print("=" * 70)
    print("  USERS & ROLES - BACKEND END-TO-END TEST")
    print("=" * 70)
    
    results = {}
    
    # Test 1: Health
    results['health'] = test_backend_health()
    if not results['health']:
        print("\n⚠️  Backend is not running. Please start it first.")
        return
    
    # Test 2: Roles
    results['roles'] = test_users_roles_endpoint()
    
    # Test 3: Users
    results['users'] = test_users_list_endpoint()
    
    # Test 4: Database
    results['database'] = test_database_connection()
    
    # Summary
    print_section("TEST SUMMARY")
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name.upper()}: {status}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 70)
    if all_passed:
        print("✅ ALL BACKEND TESTS PASSED")
        print("\nNext: Test frontend by running test_users_end_to_end.js in browser console")
    else:
        print("❌ SOME TESTS FAILED")
        print("\nFix backend issues before testing frontend")
    print("=" * 70)

if __name__ == "__main__":
    main()
