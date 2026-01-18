"""
Send password reset email to existing user
"""
import requests
import json

# Backend API URL (we'll need to add this endpoint, or use Supabase directly)
SUPABASE_URL = "https://kwvkkbofubsjiwqlqakt.supabase.co"
EMAIL = "jackmwas102@gmail.com"

print("=" * 50)
print("Password Reset Options")
print("=" * 50)
print(f"\nEmail: {EMAIL}")
print("\n[OPTION 1] Use Supabase Dashboard:")
print("  1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users")
print("  2. Find user: jackmwas102@gmail.com")
print("  3. Click on the user")
print("  4. Click 'Send password reset email'")
print("  5. Check your email and set new password")
print("\n[OPTION 2] Check your email inbox:")
print("  - Look for emails from Supabase")
print("  - Look for 'Set your password' or 'Reset password' links")
print("  - Click the link and set your password")
print("\n[OPTION 3] If you remember your password:")
print("  - Try logging in again")
print("  - Make sure you're using the correct password")
print("\n" + "=" * 50)
