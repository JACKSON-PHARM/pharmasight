# 🔧 Backend Timeout Fix

## Problem
Frontend is timing out when trying to call `/api/startup` endpoint. Error shows:
- "Request timed out after 30 seconds"
- Backend at `http://localhost:8000` not responding

## Solution Steps

### Step 1: Check Backend Status

**In PowerShell:**
```powershell
# Test if backend is responding
Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing

# Check what's using port 8000
netstat -ano | findstr :8000
```

**If backend is NOT running:**
```powershell
cd C:\PharmaSight\pharmasight
.\start.bat
```

### Step 2: Restart Backend (Clean Start)

**Stop existing processes:**
```powershell
# Kill any Python processes using port 8000
Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like "*pharmasight*"} | Stop-Process -Force
```

**Start backend manually to see errors:**
```powershell
cd C:\PharmaSight\pharmasight
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD\backend"
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Watch for:**
- ✅ "Application startup complete" = Good
- ❌ Any red error messages = Problem

### Step 3: Check Database Connection

**Backend might be failing to connect to database. Check:**

1. **`.env` file exists** in `pharmasight/backend/`
2. **DATABASE_URL is correct** (Supabase connection string)
3. **Database is accessible** from your network

**Test database connection:**
```powershell
cd C:\PharmaSight\pharmasight
python check_database.py
```

### Step 4: Common Issues

#### Issue 1: Database Connection Failed
**Symptom:** Backend starts but hangs on requests
**Fix:** Check `.env` file has correct `DATABASE_URL`

#### Issue 2: Import Errors
**Symptom:** Backend won't start at all
**Fix:** 
```powershell
cd C:\PharmaSight\pharmasight
.\venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

#### Issue 3: Port Already in Use
**Symptom:** "Address already in use"
**Fix:**
```powershell
# Find process using port 8000
$pid = (Get-NetTCPConnection -LocalPort 8000).OwningProcess
Stop-Process -Id $pid -Force
```

### Step 5: Manual Test

**Once backend is running, test the startup endpoint:**

```powershell
# Generate UUID first
$uuid = [guid]::NewGuid().ToString()

$body = @{
    company = @{
        name = "PharmaSight Meds Ltd"
        registration_number = "PVT-JZUA3728"
        pin = "P05248438Q"
        phone = "0708476318"
        email = "pharmasightsolutions@gmail.com"
        address = "5M35+849"
        currency = "KES"
        timezone = "Africa/Nairobi"
    }
    admin_user = @{
        id = $uuid
        email = "admin@pharmasight.com"
        full_name = "Admin User"
        phone = "0700000000"
    }
    branch = @{
        name = "MAIN BRANCH"
        code = $null  # Will auto-generate as BR001
        address = "5M35+849"
        phone = "0708476318"
    }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/api/startup" -Method POST -ContentType "application/json" -Body $body
```

**If this works, the backend is fine and the issue is frontend timeout.**

### Step 6: Increase Frontend Timeout (Temporary Fix)

If backend is slow to respond, you can temporarily increase timeout in `frontend/js/api.js`:

```javascript
const timeoutMs = options.timeout || 60000; // Change from 30000 to 60000 (60 seconds)
```

## Expected Behavior After Fix

✅ Backend responds to `/health` immediately
✅ `/api/startup/status` returns in < 1 second
✅ `/api/startup` completes in < 5 seconds
✅ No timeout errors in browser console

## Next Steps

Once backend is working:
1. ✅ Branch code will auto-generate as "BR001" if not provided
2. ✅ Document numbers will be simplified: CS001, CN001, etc.
3. ✅ Setup wizard should complete successfully

