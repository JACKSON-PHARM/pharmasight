# ⚡ Quick Fix: Backend Timeout Issue

## 🔍 The Problem
The frontend is timing out after 10 seconds when trying to create a company. This means the backend is either:
1. Not running
2. Running but not responding
3. Taking too long to process the request

## ✅ Step 1: Check Backend Window

**IMPORTANT:** When you ran `start.bat`, a PowerShell window should have opened for the backend. 

**Please check that window and look for:**
- ✅ "Application startup complete" = Backend is running
- ❌ Any red error messages = Backend has an error
- ❌ "ModuleNotFoundError" = Missing Python package
- ❌ "Connection refused" = Database connection issue

**If you don't see a backend window, the backend didn't start!**

## ✅ Step 2: Manually Start Backend (To See Errors)

Open a **NEW** PowerShell terminal and run:

```powershell
cd C:\PharmaSight\pharmasight
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD\backend"
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Watch the output!** You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

If you see errors instead, **copy those error messages** and share them.

## ✅ Step 3: Test Backend Directly

Once backend starts, test it in a NEW PowerShell window:

```powershell
# Test 1: Health check
Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing

# Test 2: Create company (this is what the frontend is trying to do)
$body = @{
    name = "Test Company"
    currency = "KES"
    timezone = "Africa/Nairobi"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/companies" -Method POST -ContentType "application/json" -Body $body
```

**If these work, the backend is fine and the issue is elsewhere.**
**If these fail, the backend has a problem - share the error message.**

## ✅ Step 4: Check What's Using Port 8000

```powershell
netstat -ano | findstr :8000
```

This shows what process is using port 8000. If you see multiple entries, there might be a conflict.

## 🎯 Most Common Issues

### Issue 1: Backend Not Starting
**Symptom:** No backend window, or backend window shows errors
**Fix:** Check the error message in the backend window and fix it

### Issue 2: Database Connection Failed
**Symptom:** Backend starts but shows database errors
**Fix:** Check `.env` file has correct `DATABASE_URL` from Supabase

### Issue 3: Port Already in Use
**Symptom:** "Address already in use" error
**Fix:** 
```powershell
# Find and kill the process
$pid = (Get-NetTCPConnection -LocalPort 8000).OwningProcess
Stop-Process -Id $pid -Force
```

### Issue 4: Backend Hanging
**Symptom:** Backend starts but doesn't respond to requests
**Fix:** This is rare - check backend logs for blocking operations

## 📝 What to Share

If it still doesn't work, please share:
1. **Screenshot or copy** of the backend window output
2. **Any error messages** you see
3. **Result of Step 3** (testing backend directly)

