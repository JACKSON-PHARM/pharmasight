"""
Test the startup API endpoint with the actual payload
"""
import requests
import json

API_URL = "http://localhost:8000/api/startup"

payload = {
    "company": {
        "name": "Pharmasight Meds limited",
        "registration_number": "PVT-JZUA3728",
        "pin": "P052484378Q",
        "phone": "0708476318",
        "email": "jackmwas102@gmail.com",
        "address": "60200\nKARIUKI RD",
        "currency": "KES",
        "timezone": "Africa/Nairobi",
        "fiscal_start_date": "2026-01-13"
    },
    "admin_user": {
        "id": "29932846-bf01-4bdf-9e13-25cb27764c16",
        "email": "jackmwas102@gmail.com",
        "full_name": "DR-JACKSON",
        "phone": "0708476318"
    },
    "branch": {
        "name": "Pharmasight Main Branch",
        "code": "",
        "address": "KURIKURI",
        "phone": "0707513766"
    }
}

print("=" * 60)
print("Testing Startup API Endpoint")
print("=" * 60)
print(f"\nURL: {API_URL}")
print(f"\nPayload:")
print(json.dumps(payload, indent=2))

try:
    print("\n" + "-" * 60)
    print("Sending request...")
    print("-" * 60)
    
    response = requests.post(
        API_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    print(f"\nStatus Code: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    
    try:
        response_data = response.json()
        print(f"\nResponse Body:")
        print(json.dumps(response_data, indent=2))
        
        if response.status_code == 201:
            print("\n[SUCCESS] Company setup completed!")
        else:
            print(f"\n[ERROR] Request failed with status {response.status_code}")
            if 'detail' in response_data:
                print(f"Error Detail: {response_data['detail']}")
    except json.JSONDecodeError:
        print(f"\nResponse Text (not JSON):")
        print(response.text[:500])
        
except requests.exceptions.ConnectionError:
    print("\n[ERROR] Cannot connect to backend server!")
    print("   Make sure the backend is running on http://localhost:8000")
    print("   Run: python start.py")
except requests.exceptions.Timeout:
    print("\n[ERROR] Request timed out after 30 seconds")
    print("   The backend might be slow or stuck")
except Exception as e:
    print(f"\n[ERROR] {type(e).__name__}: {str(e)}")

print("\n" + "=" * 60)
