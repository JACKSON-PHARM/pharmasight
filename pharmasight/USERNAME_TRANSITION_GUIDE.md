# Username Login Transition Guide

## Overview
The system has been updated to use username-based login instead of email. This guide explains how to handle the transition for existing users.

## What Changed

### Before
- Users logged in with their **email address**
- Email was visible on login page

### After
- Users log in with their **username** (e.g., "D-JACKSON", "S-WAMBUI")
- Email is only used for password resets and communication
- Username format: `{FirstLetter}-{LASTNAME}` (e.g., "Dr. Jackson" → "D-JACKSON")

## Transition Support

### Backward Compatibility
The login endpoint (`/api/auth/username-login`) now supports both:
1. **Username lookup** (primary method)
2. **Email lookup** (fallback for existing users without usernames)

This means existing users can still log in with their email during the transition period.

### Generating Usernames for Existing Users

**Option 1: Run Python Script (Recommended)**
```bash
cd backend
python generate_usernames_for_existing_users.py
```

This script will:
- Find all users without usernames
- Generate usernames from their `full_name`
- Handle duplicates automatically
- Update the database

**Option 2: Run SQL Migration**
```bash
cd backend
python run_migration.py ../database/generate_usernames_for_existing_users.sql
```

## Admin Login

Admin login works with:
- **Username:** `admin`
- **Password:** `33742377.jack` (or from `ADMIN_PASSWORD` env var)

When admin logs in, they are redirected to `/admin.html` (tenant management panel).

## New User Creation

When creating new users (via admin panel):
1. Admin provides **Email** and **Full Name**
2. System **auto-generates username** from full name
3. Username is included in invite response
4. User receives invite link with username

### Username Generation Rules

1. **Format:** `{FirstLetter}-{LASTNAME}`
   - "Dr. Jackson" → "D-JACKSON"
   - "Sarah Wambui" → "S-WAMBUI"
   - "John Doe Smith" → "J-SMITH" (uses last word)

2. **Title Removal:** Automatically removes:
   - Dr., Mr., Mrs., Ms., Miss, Prof., Professor, Eng., Engineer

3. **Duplicate Handling:** Appends numbers if needed:
   - "D-JACKSON" → "D-JACKSON1" → "D-JACKSON2"

4. **Fallback:** If no full name:
   - Uses email local part: "john.doe@example.com" → "J-DOE"

## Testing the Transition

### Step 1: Generate Usernames for Existing Users
```bash
cd backend
python generate_usernames_for_existing_users.py
```

### Step 2: Test Login
1. Try logging in with **username** (e.g., "D-JACKSON")
2. If username not generated yet, try **email** (should work as fallback)
3. Admin login: username "admin", password "33742377.jack"

### Step 3: Verify
- Check that users can log in with their new usernames
- Verify admin login redirects to tenant management
- Confirm password reset still uses email

## Troubleshooting

### Issue: "User not found" when logging in
**Solution:**
1. Run `generate_usernames_for_existing_users.py` to create usernames
2. Or use email to log in (fallback support)

### Issue: Backend won't start
**Solution:**
- The app now handles missing optional dependencies (Stripe, migrations)
- Check that all required dependencies are installed:
  ```bash
  pip install -r requirements.txt
  ```

### Issue: Admin login not working
**Solution:**
- Verify admin credentials: username="admin", password="33742377.jack"
- Check that `ADMIN_PASSWORD` env var matches (if set)
- Ensure admin_auth_router is included in main.py

## Files Modified

1. **Backend:**
   - `backend/app/api/auth.py` - Added email fallback support
   - `backend/app/main.py` - Made optional imports conditional
   - `backend/app/utils/username_generator.py` - Username generation utility
   - `backend/app/api/users.py` - Auto-generates username on user creation
   - `backend/app/api/tenants.py` - Generates username for tenant invites

2. **Frontend:**
   - `frontend/js/pages/login.js` - Updated to use username, fixed LoginSecurity calls
   - `frontend/js/pages/admin_tenants.js` - Shows username in invite modal

3. **Database:**
   - `database/add_username_field.sql` - Added username column (already applied)
   - `database/generate_usernames_for_existing_users.sql` - Migration to populate usernames

4. **Scripts:**
   - `backend/generate_usernames_for_existing_users.py` - Python script to generate usernames

## Next Steps

1. **Run username generation script** for existing users
2. **Test login** with both username and email (during transition)
3. **Notify users** about the username change (optional)
4. **After transition period**, remove email fallback support (optional)

## Notes

- Email is still required for password resets
- Username must be unique across all users
- Admin login bypasses regular user authentication
- Username generation is automatic for new users
