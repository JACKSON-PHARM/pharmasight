# 🔍 Debug Backend Issues

## Current Problem
Backend is running but not responding to requests (timeout errors).

## ✅ Quick Checks

### 1. Check Backend Window
A new PowerShell window should have opened. **Look at that window** and check for:
- ❌ Red error messages
- ❌ Import errors
- ❌ Database connection errors
- ✅ "Application startup complete" message

### 2. Manual Backend Start (To See Errors)

Open a NEW PowerShell terminal and run:

```powershell
cd C:\PharmaSight\pharmasight
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD\backend"
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Watch for errors** when it starts. Common errors:

#### Error: "ModuleNotFoundError: No module named 'app'"
**Fix:** Make sure you're in the `backend` directory and PYTHONPATH is set

#### Error: "relation 'companies' does not exist"
**Fix:** Run database schema in Supabase (see LOCAL_RUN_GUIDE.md)

#### Error: "Connection refused" or database errors
**Fix:** Check `.env` file has correct DATABASE_URL

#### Error: "Address already in use"
**Fix:** Port 8000 is already in use. Kill the process:
```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force
```

### 3. Test Backend Directly

Once backend starts, test it:

```powershell
# Test 1: Health check
curl http://localhost:8000/health

# Test 2: API docs
# Open in browser: http://localhost:8000/docs

# Test 3: Create company (from PowerShell)
$body = @{name="Test";currency="KES";timezone="Africa/Nairobi"} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/api/companies" -Method POST -ContentType "application/json" -Body $body
```

### 4. Check What's Actually Running

```powershell
# See what's using port 8000
netstat -ano | findstr :8000

# See Python processes
Get-Process python | Select-Object Id, Path, StartTime
```

## 🎯 Most Likely Issues

1. **Backend crashed on startup** → Check the backend window for errors
2. **Database connection failed** → Check .env DATABASE_URL
3. **Import error** → Check backend window for Python errors
4. **Port conflict** → Another process using port 8000

## ✅ Solution Steps

1. **Stop all backend processes:**
   ```powershell
   Get-Process python | Where-Object {$_.Path -like "*pharmasight*"} | Stop-Process -Force
   ```

2. **Start backend manually** (to see errors):
   ```powershell
   cd C:\PharmaSight\pharmasight
   .\venv\Scripts\Activate.ps1
   $env:PYTHONPATH = "$PWD\backend"
   cd backend
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **Watch the terminal** - it will show:
   - ✅ "Application startup complete" if successful
   - ❌ Error messages if something is wrong

4. **Copy any error messages** you see and share them

## 📝 What to Share

If it still doesn't work, please share:
1. **Any error messages** from the backend terminal
2. **The last few lines** of output when backend starts
3. **Whether you see** "Application startup complete" or errors

