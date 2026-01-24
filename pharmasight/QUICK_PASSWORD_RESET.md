# 🔐 Quick Password Reset Guide

## Problem
You forgot your admin password and Supabase reset email is blank.

## ✅ Solution: Reset Password Directly in Supabase

### Option 1: Via Supabase Dashboard (Easiest)

1. **Go to Supabase Dashboard**:
   ```
   https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users
   ```

2. **Find Your User**:
   - Look for `jackmwas102@gmail.com`
   - Click on the user row

3. **Update Password**:
   - Scroll to "Password" section
   - Click "Set Password" or "Update Password"
   - Enter your NEW password (at least 6 characters)
   - Click "Save" or "Update"

4. **Login**:
   - Go to your app: `http://localhost:3000`
   - Login with `jackmwas102@gmail.com` and your NEW password

### Option 2: Send Password Reset Email (If Option 1 doesn't work)

1. **In Supabase Dashboard**:
   - Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users
   - Find user: `jackmwas102@gmail.com`
   - Click the user
   - Click **"Send password reset email"** button

2. **Check Your Email**:
   - Check inbox for `jackmwas102@gmail.com`
   - Look for email from Supabase
   - Click the reset link (even if it looks blank)

3. **Set New Password**:
   - The link should open a page to set new password
   - Enter new password (minimum 6 characters)
   - Confirm password
   - Submit

### Option 3: Create a New Admin User (If you can't access the old one)

If the user doesn't exist or you can't reset it, create a new admin:

**Via Backend API** (Backend must be running):

```powershell
# Start backend first (if not running)
cd pharmasight\backend
uvicorn app.main:app --reload

# In another terminal, run:
python pharmasight\create_admin_user.py
```

This will:
- Create a new admin user in Supabase Auth
- Send an invitation email
- You can set password from the invitation link

### Option 4: Manual SQL Update (Advanced - Only if needed)

⚠️ **WARNING**: This is for advanced users only!

1. **Go to Supabase SQL Editor**:
   ```
   https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
   ```

2. **Run this SQL** (replaces user password):
   ```sql
   -- This updates the auth.users table directly
   -- Replace 'YOUR_NEW_PASSWORD' with your desired password
   UPDATE auth.users 
   SET encrypted_password = crypt('YOUR_NEW_PASSWORD', gen_salt('bf'))
   WHERE email = 'jackmwas102@gmail.com';
   ```

   **Note**: This requires `crypt` extension. If it doesn't work, use Option 1 or 2.

## 🔍 Troubleshooting

### "Blank Email" Issue

If Supabase emails are blank or not arriving:

1. **Check Supabase Email Settings**:
   - Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/settings/auth
   - Check "Email Templates"
   - Verify email provider is configured

2. **Check Email Spam Folder**:
   - Emails might be going to spam
   - Look for emails from `noreply@supabase.io` or similar

3. **Try Different Email** (if possible):
   - Use a different email address
   - Update user email in Supabase dashboard
   - Send reset to new email

### "User Not Found" Issue

If user doesn't exist in Supabase Auth:

1. **Create User via Invite API**:
   ```powershell
   python pharmasight\create_admin_user.py
   ```

2. **Or Create via Supabase Dashboard**:
   - Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users
   - Click "Add user" → "Create new user"
   - Enter email: `jackmwas102@gmail.com`
   - Set password (at least 6 characters)
   - Click "Create user"

### "400 Bad Request" on Login

This means:
- Password is incorrect
- User doesn't exist
- User account is disabled

**Fix**:
1. Verify user exists in Supabase Auth dashboard
2. Reset password using Option 1 above
3. Try logging in again

## ✅ Recommended Steps (In Order)

1. **Try Option 1** (Supabase Dashboard - Update Password directly)
2. **If that fails, try Option 2** (Send reset email)
3. **If user doesn't exist, use Option 3** (Create new admin)

## 📝 After Password Reset

Once you can log in:

1. Go to: `http://localhost:3000`
2. Login with `jackmwas102@gmail.com` and your new password
3. Navigate to **Settings → Users & Roles**
4. You should now see the Users & Roles tab content!

## 🆘 Still Having Issues?

1. **Check Supabase Status**: https://status.supabase.com/
2. **Verify Backend is Running**: `http://localhost:8000/health`
3. **Check Browser Console**: Look for errors (F12)
4. **Verify User Exists**: Check Supabase Auth dashboard
