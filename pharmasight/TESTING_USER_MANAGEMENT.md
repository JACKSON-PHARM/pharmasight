# Testing User Management - Troubleshooting Guide

## Current Status

✅ **Code Implementation**: Complete
- Backend API endpoints created
- Frontend UI implemented
- Database migration script created

⚠️ **Backend Not Running**: The test script confirms the backend is not running on `http://localhost:8000`

## Quick Diagnosis

Run the test script to check backend status:

```powershell
cd C:\PharmaSight
python pharmasight\test_users_api.py
```

If you see `[FAIL] Cannot connect to backend!` - **backend is not running**.

## Solution: Start the Backend

### Option 1: Use Start Script (Easiest)

```powershell
cd C:\PharmaSight
.\start.bat
```

This will start both frontend and backend.

### Option 2: Start Backend Manually

```powershell
# Navigate to backend directory
cd C:\PharmaSight\pharmasight\backend

# Activate virtual environment (if exists)
.\venv\Scripts\Activate.ps1

# Start backend server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Option 3: Using Python Script

```powershell
cd C:\PharmaSight
python pharmasight\start.py
```

## Verify Backend is Running

After starting the backend, test it:

1. **Check Health Endpoint**:
   ```
   http://localhost:8000/health
   ```
   Should return: `{"status": "healthy"}`

2. **Check API Docs**:
   ```
   http://localhost:8000/docs
   ```
   Should show Swagger UI with all endpoints

3. **Check Users Endpoint**:
   ```
   http://localhost:8000/api/users/roles
   ```
   Should return list of roles

4. **Run Test Script Again**:
   ```powershell
   python pharmasight\test_users_api.py
   ```
   Should show `[OK] Backend is running!`

## Database Migration (If Not Done)

Before testing user creation, run the database migration:

1. **Open Supabase SQL Editor**: https://supabase.com/dashboard/project/YOUR_PROJECT/sql/new

2. **Copy and Run** the migration script:
   ```sql
   -- Copy contents of: pharmasight/database/add_user_invitation_fields.sql
   ```

3. **Or run via psql** (if you have direct DB access):
   ```bash
   psql -h YOUR_DB_HOST -U postgres -d postgres -f pharmasight/database/add_user_invitation_fields.sql
   ```

## Testing the Frontend

Once backend is running:

1. **Open Frontend**: http://localhost:3000

2. **Navigate to Settings → Users & Roles**

3. **Expected Behavior**:
   - If backend is running: Shows "Loading users..." then either:
     - "No users found" (if database is empty)
     - Users table (if users exist)
   - If backend is NOT running: Shows error message with "Retry" button

4. **Check Browser Console** (F12):
   - Look for `renderUsersPage() called` in console
   - Check for API errors in Network tab
   - Common errors:
     - `Network error` = Backend not running
     - `404 Not Found` = Endpoint not available (backend needs restart)
     - `500 Internal Server Error` = Database migration needed

## Common Issues & Solutions

### Issue 1: Blank Page (No Content)

**Symptom**: Users & Roles tab shows blank white page

**Possible Causes**:
1. Backend not running → **Start backend**
2. JavaScript error → Check browser console (F12)
3. API endpoint not registered → Restart backend

**Solution**:
```powershell
# Start/restart backend
cd C:\PharmaSight\pharmasight\backend
uvicorn app.main:app --reload
```

### Issue 2: "Error loading users" Message

**Symptom**: Page shows error message instead of user list

**Possible Causes**:
1. Database migration not run → **Run migration**
2. Backend error → Check backend logs

**Solution**:
- Run database migration (see above)
- Check backend terminal for error messages

### Issue 3: API Endpoint Not Found (404)

**Symptom**: Browser console shows `404 Not Found` for `/api/users`

**Cause**: Backend router not registered or backend needs restart

**Solution**:
1. Verify `backend/app/main.py` includes:
   ```python
   from app.api.users import router as users_router
   app.include_router(users_router, prefix="/api", tags=["User Management"])
   ```
2. Restart backend server

### Issue 4: Database Error (500)

**Symptom**: Backend returns 500 error when calling `/api/users`

**Cause**: Database migration not run (missing fields in `users` table)

**Solution**:
- Run migration: `database/add_user_invitation_fields.sql`
- Restart backend after migration

## Step-by-Step Testing Checklist

- [ ] Backend is running (`http://localhost:8000/health` returns OK)
- [ ] Database migration has been run
- [ ] Frontend is accessible (`http://localhost:3000`)
- [ ] Navigate to Settings → Users & Roles
- [ ] Page loads (no blank screen)
- [ ] No errors in browser console (F12)
- [ ] Can click "New User" button
- [ ] Can create a user (if backend and DB are ready)

## Quick Test Commands

```powershell
# Test backend health
curl http://localhost:8000/health

# Test users API (requires requests library)
python pharmasight\test_users_api.py

# Check if backend process is running
Get-Process | Where-Object {$_.ProcessName -like "*python*" -or $_.ProcessName -like "*uvicorn*"}
```

## Next Steps After Backend is Running

1. ✅ Backend starts successfully
2. ✅ `/api/users/roles` endpoint works
3. ✅ `/api/users` endpoint works
4. ✅ Frontend can load users list
5. ✅ Create a test user via frontend
6. ✅ Verify invitation code is generated

## Support

If issues persist:
1. Check backend terminal logs for errors
2. Check browser console (F12) for JavaScript errors
3. Verify database connection is working
4. Ensure all dependencies are installed: `pip install -r backend/requirements.txt`
