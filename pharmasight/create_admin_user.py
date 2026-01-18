"""
Quick script to create the first admin user in Supabase Auth
Run this once to set up your admin account
"""
import requests
import json

# Backend API URL
API_URL = "http://localhost:8000/api/invite/admin"

# Admin user details
admin_data = {
    "email": "jackmwas102@gmail.com",
    "full_name": "Admin User",
    "redirect_to": "/setup"
}

print("=" * 50)
print("Creating Admin User in Supabase Auth")
print("=" * 50)
print(f"\nEmail: {admin_data['email']}")
print(f"Full Name: {admin_data['full_name']}")
print(f"\nSending request to: {API_URL}")

try:
    response = requests.post(
        API_URL,
        json=admin_data,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    print(f"\nStatus Code: {response.status_code}")
    
    if response.status_code == 201:
        result = response.json()
        print("\n[SUCCESS] Admin user created!")
        print(f"\nUser ID: {result.get('user_id')}")
        print(f"Message: {result.get('message')}")
        print("\n[INFO] Check your email for the invite link!")
        print("   After setting your password, you can log in.")
    else:
        print(f"\n[ERROR] Status Code: {response.status_code}")
        try:
            error_data = response.json()
            print(f"Details: {error_data.get('detail', 'Unknown error')}")
        except:
            print(f"Response: {response.text}")
            
except requests.exceptions.ConnectionError:
    print("\n[ERROR] Cannot connect to backend server!")
    print("   Make sure the backend is running on http://localhost:8000")
    print("   Run: python start.py")
except Exception as e:
    print(f"\n[ERROR] {str(e)}")

print("\n" + "=" * 50)
