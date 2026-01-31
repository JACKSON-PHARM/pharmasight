# Admin Panel Troubleshooting Guide

## ✅ What We've Achieved

1. **Master Database Schema Created** ✓
   - `tenants` table exists
   - `tenant_invites` table exists
   - `subscription_plans` table exists
   - `tenant_subscriptions` table exists
   - `tenant_modules` table exists

2. **First Tenant Created** ✓
   - Name: PHARMASIGHT MEDS LTD
   - Subdomain: pharmasight-meds-ltd
   - Email: pharmasightsolutions@gmail.com
   - Status: active
   - ID: cf56d87f-89ce-4d9d-b3c9-c4622f676bfb

3. **Admin Panel UI Created** ✓
   - File: `frontend/admin.html`
   - JavaScript: `frontend/js/pages/admin_tenants.js`
   - API endpoints: `/api/admin/tenants`

---

## 🔍 Current Issue: Admin Panel Shows Error

The admin panel shows "Error loading admin panel" instead of the tenant list.

### Step 1: Verify Tenant Exists

Run this test script:

```bash
cd pharmasight/backend
python test_tenant_api.py
```

This will show:
- If tenant exists in database
- Database connection status
- Any query errors

### Step 2: Test API Endpoint Directly

Open in your browser:
```
http://localhost:8000/api/admin/tenants
```

**Expected Response:**
```json
{
  "tenants": [
    {
      "id": "cf56d87f-89ce-4d9d-b3c9-c4622f676bfb",
      "name": "PHARMASIGHT MEDS LTD",
      "subdomain": "pharmasight-meds-ltd",
      "admin_email": "pharmasightsolutions@gmail.com",
      "status": "active",
      ...
    }
  ],
  "total": 1
}
```

**If you get an error:**
- Check backend terminal for error messages
- Verify master database connection
- Check if tables exist

### Step 3: Check Browser Console

1. Open admin panel: `http://localhost:3000/admin.html`
2. Press **F12** to open Developer Tools
3. Go to **Console** tab
4. Look for errors like:
   - "API client not properly initialized"
   - Network errors
   - CORS errors
   - "Failed to load tenants"

### Step 4: Check Network Tab

1. Open Developer Tools (F12)
2. Go to **Network** tab
3. Refresh the admin panel
4. Look for request to `/api/admin/tenants`
5. Check:
   - Status code (should be 200)
   - Response body
   - Any errors

---

## 🛠️ Common Fixes

### Fix 1: Backend Not Running

**Symptom:** Network error, connection refused

**Fix:**
```bash
# Make sure backend is running
cd pharmasight
python start.py
```

### Fix 2: CORS Error

**Symptom:** CORS policy error in browser console

**Fix:** Check `backend/app/main.py` CORS settings

### Fix 3: Database Connection Error

**Symptom:** 500 error from API, "Error listing tenants" in backend logs

**Fix:**
- Verify `MASTER_DATABASE_URL` environment variable
- Check database connection string
- Verify master database tables exist

### Fix 4: API Client Not Loaded

**Symptom:** "API client not properly initialized" error

**Fix:**
- Refresh the page
- Check browser console for script loading errors
- Verify `api.js` is loaded before `admin_tenants.js`

---

## 📋 Quick Checklist

- [ ] Backend is running on port 8000
- [ ] Frontend is running on port 3000
- [ ] Master database schema created (`python setup_master_database.py`)
- [ ] First tenant created (`python create_first_client.py`)
- [ ] Admin logged in (username: `admin`, password: `33742377.jack`)
- [ ] Browser console shows no errors
- [ ] API endpoint `/api/admin/tenants` returns JSON

---

## 🎯 How to Access Admin Panel

### Method 1: Direct URL (Current)
```
http://localhost:3000/admin.html
```

### Method 2: After Admin Login (Future)
1. Go to: `http://localhost:3000/#login`
2. Username: `admin`
3. Password: `33742377.jack`
4. Automatically redirected to admin panel

---

## 🔧 Next Steps

1. **Run test script:**
   ```bash
   cd pharmasight/backend
   python test_tenant_api.py
   ```

2. **Test API directly:**
   - Open: `http://localhost:8000/api/admin/tenants`
   - Should see JSON with tenant data

3. **Check browser console:**
   - Open admin panel
   - Press F12
   - Check Console and Network tabs
   - Share any errors you see

4. **Fix triggers (optional):**
   ```bash
   cd pharmasight/backend
   python fix_triggers.py
   ```

---

**The tenant exists in the database!** The issue is likely in the API call or response format. Check the browser console for specific errors.
