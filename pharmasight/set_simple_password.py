"""
Set a simple password for a Supabase Auth user
This script uses Supabase Admin API to update user password
"""
import requests
import os

# Supabase configuration
SUPABASE_URL = "https://kwvkkbofubsjiwqlqakt.supabase.co"
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # Admin/service role key

# User details
EMAIL = "jackmwas102@gmail.com"  # Change this to your email
NEW_PASSWORD = "9542"  # The simple password you want

print("=" * 60)
print("Set Simple Password for Supabase User")
print("=" * 60)
print(f"\nEmail: {EMAIL}")
print(f"New Password: {NEW_PASSWORD}")

# Check if service key is available
if not SUPABASE_SERVICE_KEY:
    print("\n" + "⚠️" * 30)
    print("❌ SUPABASE_SERVICE_KEY not found in environment!")
    print("\nTo set a password directly, you need the Service Role Key.")
    print("\n📋 OPTIONS:")
    print("\n[OPTION 1] Use Supabase Dashboard (Easiest):")
    print("  1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users")
    print("  2. Find or create user:", EMAIL)
    print("  3. Click on the user → Click 'Send password reset email'")
    print("  4. Check your email and click the reset link")
    print("  5. Set password to:", NEW_PASSWORD)
    print("\n[OPTION 2] Use Supabase CLI (if installed):")
    print("  supabase auth admin update-user-by-email")
    print("\n[OPTION 3] Get Service Role Key and run this script:")
    print("  1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/settings/api")
    print("  2. Copy 'service_role' key (NOT anon key)")
    print("  3. Set environment variable:")
    print("     Windows PowerShell: $env:SUPABASE_SERVICE_KEY='your-service-key'")
    print("     Windows CMD: set SUPABASE_SERVICE_KEY=your-service-key")
    print("  4. Run this script again")
    print("=" * 60)
    exit(1)

# Step 1: Get user ID by email
print("\n[STEP 1] Looking up user by email...")
auth_url = f"{SUPABASE_URL}/auth/v1/admin/users"
headers = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

try:
    # List users and find by email
    response = requests.get(
        f"{auth_url}?per_page=1000",
        headers=headers,
        timeout=10
    )
    
    if response.status_code != 200:
        print(f"❌ Error getting users: {response.status_code}")
        print(f"Response: {response.text}")
        exit(1)
    
    users = response.json().get("users", [])
    user = next((u for u in users if u.get("email") == EMAIL), None)
    
    if not user:
        print(f"❌ User with email '{EMAIL}' not found!")
        print("\nWould you like to create this user? (Y/N)")
        choice = input().strip().lower()
        if choice == 'y':
            # Create user first
            print(f"\n[CREATING USER] Creating user: {EMAIL}")
            create_response = requests.post(
                auth_url,
                headers=headers,
                json={
                    "email": EMAIL,
                    "password": NEW_PASSWORD,
                    "email_confirm": True
                },
                timeout=10
            )
            if create_response.status_code in [200, 201]:
                print("✅ User created successfully!")
                user = create_response.json()
            else:
                print(f"❌ Error creating user: {create_response.status_code}")
                print(f"Response: {create_response.text}")
                exit(1)
        else:
            print("Exiting...")
            exit(1)
    else:
        user_id = user.get("id")
        print(f"✅ User found! ID: {user_id}")
        
        # Step 2: Update password
        print(f"\n[STEP 2] Updating password to: {NEW_PASSWORD}")
        update_response = requests.put(
            f"{auth_url}/{user_id}",
            headers=headers,
            json={
                "password": NEW_PASSWORD
            },
            timeout=10
        )
        
        if update_response.status_code in [200, 201]:
            print("✅ Password updated successfully!")
            print(f"\n🎉 You can now log in with:")
            print(f"   Email: {EMAIL}")
            print(f"   Password: {NEW_PASSWORD}")
        else:
            print(f"❌ Error updating password: {update_response.status_code}")
            print(f"Response: {update_response.text}")
            exit(1)

except requests.exceptions.RequestException as e:
    print(f"\n❌ Network error: {str(e)}")
    print("\nMake sure:")
    print("  1. You have internet connection")
    print("  2. The Supabase URL is correct")
    print("  3. The service key is valid")
    exit(1)
except Exception as e:
    print(f"\n❌ Error: {str(e)}")
    exit(1)

print("\n" + "=" * 60)
