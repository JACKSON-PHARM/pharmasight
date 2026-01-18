#!/usr/bin/env python3
"""Quick test script for company API"""
import requests
import json

url = "http://localhost:8000/api/companies"
data = {
    "name": "Test PharmaSight Company",
    "currency": "KES",
    "timezone": "Africa/Nairobi"
}

try:
    print("Testing company creation...")
    print(f"POST {url}")
    print(f"Data: {json.dumps(data, indent=2)}")
    
    response = requests.post(url, json=data, timeout=5)
    
    print(f"\nStatus Code: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    
    if response.status_code == 201:
        print("\n✅ SUCCESS!")
        print(f"Response: {json.dumps(response.json(), indent=2, default=str)}")
    else:
        print(f"\n❌ ERROR: {response.status_code}")
        try:
            print(f"Response: {response.json()}")
        except:
            print(f"Response Text: {response.text}")
            
except requests.exceptions.ConnectionError:
    print("\n❌ ERROR: Cannot connect to backend!")
    print("   Make sure the backend server is running on http://localhost:8000")
except requests.exceptions.Timeout:
    print("\n❌ ERROR: Request timed out!")
    print("   The backend might be hanging or crashed")
except Exception as e:
    print(f"\n❌ ERROR: {type(e).__name__}: {e}")

