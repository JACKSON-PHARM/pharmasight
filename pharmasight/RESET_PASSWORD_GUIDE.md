# 🔐 Reset Password in Supabase - Step by Step Guide

## 📍 Step 1: Go to Authentication Section

1. **Look at the LEFT SIDEBAR** (where you see the list of tables)
2. **Scroll UP** to the top of that sidebar
3. You should see these main sections:
   - 🔍 **Project Settings**
   - 📊 **Table Editor** (you're here now)
   - 🔐 **Authentication** ← **CLICK THIS!**
   - 📝 **SQL Editor**
   - 🛠️ **Database**
   - And others...

## 📍 Step 2: Click on "Authentication"

1. **Click "Authentication"** in the left sidebar
2. You should see a submenu appear:
   - Users
   - Policies
   - Providers
   - Templates
   - Settings

## 📍 Step 3: Go to "Users"

1. **Click "Users"** (first item under Authentication)
2. You'll see a list of all users who can log in
3. This is different from the `users` table you saw in Table Editor!

## 📍 Step 4: Find Your User

1. **Look for** `jackmwas102@gmail.com` in the list
2. You can use the search box at the top to filter users
3. **Click on the user row** to select it (or click the 3 dots menu)

## 📍 Step 5: Reset Password

**Option A: Using the Actions Menu**
1. Click the **three dots (⋯)** on the right side of the user row
2. Click **"Send password reset email"**
3. Check your email inbox
4. Click the reset link in the email
5. Set new password to: **9542**

**Option B: If "Send password reset" doesn't work**
1. Click the **three dots (⋯)** on the user row
2. Click **"Edit user"** or **"Reset password"**
3. Some versions might have a direct "Reset password" button

**Option C: If user doesn't exist**
1. Click the **"Add user"** or **"Invite user"** button (usually top right)
2. Enter email: `jackmwas102@gmail.com`
3. Enter password: `9542`
4. Check **"Auto Confirm"** if available
5. Click **"Create user"** or **"Send invite"**

## 🆘 Alternative: Direct URL

If you're having trouble navigating, try this direct URL:

```
https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/auth/users
```

This will take you directly to the Authentication → Users page.

## 📸 Visual Guide

**What you should see:**
```
Left Sidebar:
  ├── Project Settings
  ├── Table Editor        ← You were here (database tables)
  ├── Authentication      ← Click this!
  │   ├── Users           ← Then click this!
  │   ├── Policies
  │   └── ...
  ├── SQL Editor
  └── ...
```

**In Authentication → Users:**
- List of users with email addresses
- Each row has: Email | Created | Last Sign In | Actions (3 dots)
- Top right: "Invite user" or "Add user" button

## ✅ After Resetting Password

1. Go back to your login page: `http://localhost:3000`
2. Enter:
   - **Email:** `jackmwas102@gmail.com`
   - **Password:** `9542`
3. Click **"Sign In"**

---

**Still having trouble?** Let me know what you see in the left sidebar, and I'll guide you further!
