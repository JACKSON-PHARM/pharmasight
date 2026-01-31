# Username-Based Login Migration Guide

## ✅ What Changed

The login system has been updated to use **username** instead of **email** for authentication:

- **Login:** Users now log in with their **username** (not email)
- **Email:** Still required and used for:
  - Password resets
  - Communication
  - Account recovery

---

## 🔧 Database Migration Required

### Step 1: Run the Migration

```bash
# Connect to your database
psql -U your_user -d your_database

# Run the migration
\i database/add_username_field.sql
```

Or manually:
```sql
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS username VARCHAR(100) UNIQUE;

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
```

### Step 2: Set Usernames for Existing Users

For existing users, you'll need to set usernames. You can:

**Option A: Use a script to generate usernames from names:**
```sql
UPDATE users 
SET username = LOWER(REGEXP_REPLACE(full_name, '[^a-zA-Z0-9]', '', 'g'))
WHERE username IS NULL AND full_name IS NOT NULL;
```

**Option B: Manually set usernames:**
```sql
UPDATE users SET username = 'johndoe' WHERE email = 'john@example.com';
```

**Option C: Use email prefix as username (temporary):**
```sql
UPDATE users 
SET username = LOWER(SPLIT_PART(email, '@', 1))
WHERE username IS NULL;
```

---

## 📋 Changes Made

### Backend:

1. **Database Schema:**
   - Added `username` field to `users` table (unique, nullable)
   - Created index on `username` for faster lookups

2. **User Model** (`backend/app/models/user.py`):
   - Added `username` field

3. **User Schema** (`backend/app/schemas/user.py`):
   - `UserCreate` now requires `username`
   - `UserResponse` includes `username`

4. **New API Endpoint** (`backend/app/api/auth.py`):
   - `POST /api/auth/username-login` - Looks up email from username

5. **Admin Auth** (`backend/app/api/admin_auth.py`):
   - Updated to use `username` instead of `email`

6. **User Creation** (`backend/app/api/users.py`):
   - Now requires and validates `username`
   - Checks for duplicate usernames

### Frontend:

1. **Login Form** (`frontend/js/pages/login.js`):
   - Changed from "Email" to "Username" field
   - Updated authentication flow:
     - User enters username
     - System looks up email from username
     - Uses email for Supabase Auth

2. **Login Form** (`frontend/index.html`):
   - Updated to use "Username" instead of "Email"

3. **Password Reset** (`frontend/js/pages/password_reset.js`):
   - **Still uses email** (correct - email for communication)

---

## 🚀 How It Works Now

### Login Flow:

```
1. User enters username and password
   ↓
2. Frontend calls /api/auth/username-login
   ↓
3. Backend looks up user by username
   ↓
4. Returns user's email
   ↓
5. Frontend uses email for Supabase Auth
   ↓
6. User is authenticated
```

### Admin Login:

- **Username:** `admin`
- **Password:** `33742377.jack`

### Regular User Login:

- **Username:** Their unique username (e.g., `johndoe`)
- **Password:** Their password

---

## 📝 Important Notes

1. **Email Still Required:**
   - Email is still stored and required
   - Used for password resets
   - Used for communication

2. **Username Must Be Unique:**
   - Each user must have a unique username
   - Username is case-insensitive (stored lowercase)

3. **Existing Users:**
   - Need to have usernames set (see migration step 2)
   - Can use email prefix or generate from name

4. **New Users:**
   - Must provide username when created
   - Username is validated for uniqueness

---

## ✅ Testing

### Test Username Login:

1. **Set username for a test user:**
   ```sql
   UPDATE users SET username = 'testuser' WHERE email = 'test@example.com';
   ```

2. **Login:**
   - Go to: `http://localhost:3000/#login`
   - Username: `testuser`
   - Password: `your-password`
   - Should authenticate successfully

### Test Admin Login:

1. **Login:**
   - Go to: `http://localhost:3000/#login`
   - Username: `admin`
   - Password: `33742377.jack`
   - Should redirect to admin panel

### Test Password Reset:

1. **Password reset still uses email:**
   - Go to: `http://localhost:3000/#password-reset`
   - Enter email address
   - Reset link sent to email

---

## 🔄 Migration Checklist

- [ ] Run database migration (`add_username_field.sql`)
- [ ] Set usernames for existing users
- [ ] Test login with username
- [ ] Test admin login
- [ ] Test password reset (should still use email)
- [ ] Update any user creation forms to include username field
- [ ] Verify new user creation requires username

---

## 🎯 Summary

**Before:**
- Login with: Email
- Email visible in login form

**After:**
- Login with: Username
- Email hidden (only used for password resets)
- More privacy-friendly

**Email Usage:**
- ✅ Password resets
- ✅ Communication
- ✅ Account recovery
- ❌ Login (now uses username)

---

**Ready to migrate?** Run the database migration and set usernames for existing users! 🚀
