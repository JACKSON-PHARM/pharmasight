# Admin Login Guide - How It Works

## 🎯 Overview

When you log in, the system automatically detects if you're an admin and redirects you accordingly:

- **Admin Login** → Redirects to **Admin Panel** (Tenant Management)
- **Regular User Login** → Redirects to **Main App** (PharmaSight)

---

## 🔐 Admin Credentials

**Username/Email:** `admin`  
**Password:** `33742377.jack`

**Alternative:** You can also use:
- Email: `admin@pharmasight.com`
- Email: `pharmasightsolutions@gmail.com`

---

## 🚀 How to Login as Admin

### Step 1: Go to Login Page

Open: `http://localhost:3000/#login`

### Step 2: Enter Admin Credentials

- **Email:** `admin`
- **Password:** `33742377.jack`

### Step 3: Click "Sign In"

**What happens:**
1. System detects admin login
2. Validates credentials
3. Stores admin token
4. **Automatically redirects to:** `http://localhost:3000/admin.html`
5. You see the Tenant Management dashboard

---

## 👤 How Regular Users Login

### Step 1: Go to Login Page

Open: `http://localhost:3000/#login`

### Step 2: Enter Regular Credentials

- **Email:** `user@example.com` (any non-admin email)
- **Password:** `their-password`

### Step 3: Click "Sign In"

**What happens:**
1. System uses Supabase Auth
2. Validates credentials
3. **Automatically redirects to:** `http://localhost:3000/#branch-select`
4. User sees normal PharmaSight app

---

## 🔍 Technical Flow

### Admin Login Flow:

```
User enters "admin" / "33742377.jack"
    ↓
Login.js detects admin email
    ↓
Calls /api/admin/auth/login
    ↓
Backend validates credentials
    ↓
Returns admin token
    ↓
Frontend stores token in localStorage
    ↓
Redirects to /admin.html
    ↓
Admin panel loads
```

### Regular Login Flow:

```
User enters regular credentials
    ↓
Login.js uses Supabase Auth
    ↓
Supabase validates credentials
    ↓
Returns user session
    ↓
Redirects to /#branch-select
    ↓
Main app loads
```

---

## 🛡️ Security

### Development:
- Admin password: `33742377.jack` (hardcoded for now)

### Production (Render):
- Set environment variable: `ADMIN_PASSWORD=33742377.jack`
- Password stored securely, not in code
- Can be changed without code changes

---

## 📋 What You'll See

### After Admin Login:
- **URL:** `http://localhost:3000/admin.html`
- **Page:** Tenant Management Dashboard
- **Features:**
  - List of all tenants
  - Create New Tenant button
  - Search and filter
  - Generate invite links

### After Regular Login:
- **URL:** `http://localhost:3000/#branch-select`
- **Page:** Branch Selection (then Dashboard)
- **Features:**
  - Normal PharmaSight app
  - Sales, Purchases, Inventory, etc.

---

## ✅ Testing

### Test Admin Login:
1. Go to: `http://localhost:3000/#login`
2. Email: `admin`
3. Password: `33742377.jack`
4. Should see: Tenant Management dashboard

### Test Regular Login:
1. Go to: `http://localhost:3000/#login`
2. Email: `your-email@example.com`
3. Password: `your-password`
4. Should see: Branch selection screen

---

## 🔧 For Production (Render)

### Set Environment Variables:

In Render dashboard, add:
```
ADMIN_PASSWORD=33742377.jack
```

**Why:**
- Password not in code
- Easy to change
- Secure

---

## 📝 Summary

**Admin Login:**
- Email: `admin`
- Password: `33742377.jack`
- → Auto-redirects to Admin Panel

**Regular Login:**
- Any other credentials
- → Auto-redirects to Main App

**No URL Typing Needed!**
- System automatically detects admin
- Redirects to correct page
- Works on Render too!

---

**Ready to test?** Login with `admin` / `33742377.jack` and you'll automatically see the admin panel! 🚀
