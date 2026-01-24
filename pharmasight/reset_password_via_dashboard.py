"""
Guide script for password reset - shows you how to reset via Supabase Dashboard
This is safer than programmatic reset
"""
import webbrowser

print("=" * 70)
print("🔐 Password Reset Guide")
print("=" * 70)
print()
print("Your email: jackmwas102@gmail.com")
print()
print("📋 STEPS TO RESET PASSWORD:")
print()
print("1. Go to Supabase Auth Users page:")
print("   https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users")
print()
print("2. Find your user: jackmwas102@gmail.com")
print()
print("3. Click on the user row to open user details")
print()
print("4. Scroll down to 'Password' section")
print()
print("5. Click 'Set Password' or 'Update Password' button")
print()
print("6. Enter your NEW password (minimum 6 characters)")
print()
print("7. Click 'Save' or 'Update'")
print()
print("8. Go back to your app and login with the new password")
print()
print("=" * 70)
print()

# Ask if user wants to open the page
response = input("Open Supabase Auth Users page in browser? (y/n): ")
if response.lower() == 'y':
    url = "https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users"
    print(f"\nOpening {url}...")
    webbrowser.open(url)
    print("\n✅ Page opened! Follow the steps above to reset your password.")
else:
    print("\n📋 Copy and paste this URL in your browser:")
    print("   https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users")

print("\n" + "=" * 70)
