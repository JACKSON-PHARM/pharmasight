# Troubleshooting Admin Panel - Tenant List Not Showing

## Issue
The admin panel shows "Error loading admin panel" and tenants are not displayed.

## Quick Checks

### 1. Check if Master Database Schema Exists

Run this to verify the master database tables exist:

```bash
cd pharmasight/backend
python setup_master_database.py
```

### 2. Check if Tenant Was Created

Verify the tenant exists in the master database:

```sql
-- Connect to your database
SELECT * FROM tenants;
```

If the table doesn't exist, run the setup script above.

### 3. Check Browser Console

Open browser console (F12) and look for:
- API errors
- Network request failures
- JavaScript errors

### 4. Check Backend Logs

Look at your backend terminal for:
- Database connection errors
- API endpoint errors
- Exception traces

## Common Issues

### Issue 1: Master Database Schema Not Created

**Symptoms:**
- Error: "relation 'tenants' does not exist"
- 500 error from API

**Fix:**
```bash
cd pharmasight/backend
python setup_master_database.py
```

### Issue 2: Tenant Not Created

**Symptoms:**
- API returns empty list
- No tenants in database

**Fix:**
```bash
cd pharmasight/backend
python create_first_client.py
```

### Issue 3: API Endpoint Not Accessible

**Symptoms:**
- Network error in browser console
- CORS errors

**Fix:**
- Check backend is running on port 8000
- Check CORS settings in `backend/app/main.py`
- Verify API_BASE_URL in `frontend/js/config.js`

### Issue 4: Authentication Issue

**Symptoms:**
- 401 Unauthorized errors
- Redirect to login page

**Fix:**
- Login as admin: username `admin`, password `33742377.jack`
- Check admin_token in localStorage

## Debug Steps

1. **Open Browser Console (F12)**
   - Look for errors
   - Check Network tab for API calls

2. **Test API Directly:**
   ```
   http://localhost:8000/api/admin/tenants
   ```
   Should return JSON with tenants list

3. **Check Backend Logs:**
   - Look for error messages
   - Check database connection errors

4. **Verify Database:**
   ```sql
   SELECT COUNT(*) FROM tenants;
   ```
   Should return number of tenants

## Expected Response Format

The API should return:
```json
{
  "tenants": [
    {
      "id": "...",
      "name": "PHARMASIGHT MEDS LTD",
      "subdomain": "...",
      "admin_email": "...",
      "status": "active",
      ...
    }
  ],
  "total": 1
}
```

If you see a different format, that's the issue!

## Still Not Working?

1. Check browser console for exact error
2. Check backend terminal for errors
3. Verify master database schema exists
4. Verify tenant was created
5. Test API endpoint directly in browser
