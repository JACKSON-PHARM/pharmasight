# ⚠️ Backend Needs Restart

## Issue

The bulk import endpoint was added, but the backend server needs to be restarted to load it.

**Symptoms:**
- Progress bar shows correctly ✅
- But import times out ❌
- Backend not responding to health check ❌

## Solution: Restart Backend

### Option 1: Using start.bat (Easiest)

1. **Stop any running backend processes:**
   ```powershell
   Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like "*pharmasight*"} | Stop-Process -Force
   ```

2. **Start servers:**
   ```powershell
   cd C:\PharmaSight\pharmasight
   .\start.bat
   ```

3. **Wait for:**
   - ✅ Backend: "Application startup complete"
   - ✅ Frontend: Server running on port 3000

### Option 2: Manual Restart

1. **Stop old processes:**
   ```powershell
   Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
   ```

2. **Start backend:**
   ```powershell
   cd C:\PharmaSight\pharmasight\backend
   $env:PYTHONPATH = "$PWD"
   ..\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **In another terminal, start frontend:**
   ```powershell
   cd C:\PharmaSight\pharmasight\frontend
   python -m http.server 3000
   ```

## Verify Backend is Running

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing
```

Should return: `{"status":"healthy"}`

## Test Bulk Endpoint

After restart, check if bulk endpoint exists:

1. Go to: http://localhost:8000/docs
2. Look for: `POST /api/items/bulk`
3. Should be listed under "Items" tag

## Then Try Import Again

1. Hard refresh browser: `Ctrl + Shift + R`
2. Go to Items page
3. Click "Import Excel"
4. Select your file
5. Click "Import Items"

Should work now! 🚀
