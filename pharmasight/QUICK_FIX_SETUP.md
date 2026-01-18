# 🚨 Quick Fix: Setup Wizard Stuck on "Creating..."

## The Problem
The form gets stuck at "Creating..." when you click "Next: Setup Branch". This usually means:

1. **Backend server needs restart** (most common)
2. **Backend is crashing** (check backend terminal)
3. **Database connection issue**

## ✅ Quick Fix Steps

### Step 1: Check Backend Terminal
Look at the terminal/window running the backend server. You should see:
- Any error messages in RED
- The actual error that's causing the 500 error

**What to look for:**
- "relation 'companies' does not exist" → Database schema not run
- "Error creating company: ..." → This will show the actual error
- Connection timeout → Database connection issue

### Step 2: Restart Backend (IMPORTANT!)

**If using start.bat:**
1. Close the "PharmaSight Backend" window
2. Close the "PharmaSight Frontend" window  
3. Run `start.bat` again

**If using start.py:**
1. Press `Ctrl+C` to stop
2. Run `python start.py` again

**If running manually:**
1. Find the terminal running uvicorn
2. Press `Ctrl+C`
3. Restart:
   ```powershell
   cd C:\PharmaSight\pharmasight
   .\venv\Scripts\Activate.ps1
   $env:PYTHONPATH = "$PWD\backend"
   cd backend
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

### Step 3: Check Backend is Running

Open in browser: http://localhost:8000/docs

You should see:
- API documentation page
- "Company & Branch" section with `/api/companies` endpoint

If you see an error or blank page → Backend is not running correctly

### Step 4: Test the API Directly

Open browser console (F12) and run:
```javascript
fetch('http://localhost:8000/api/companies', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: 'Test Company', currency: 'KES', timezone: 'Africa/Nairobi'})
})
.then(r => r.json())
.then(data => console.log('Success:', data))
.catch(err => console.error('Error:', err));
```

### Step 5: Check Browser Console

When you click "Next: Setup Branch", check the browser console (F12 → Console tab):

**Look for:**
- ❌ Red errors with the actual error message
- ✅ "Company created successfully:" message
- 🔄 Network requests in the Network tab

## Common Errors & Solutions

### Error: "CORS policy" or "No 'Access-Control-Allow-Origin'"
**Solution:** Backend is not running or CORS not configured. Restart backend.

### Error: "500 Internal Server Error"
**Solution:** Check backend terminal for the actual error. Usually:
- Database tables don't exist → Run schema.sql in Supabase
- Database connection failed → Check .env DATABASE_URL

### Error: "Request timed out"
**Solution:** 
- Backend might be crashed → Restart it
- Database connection is slow → Check Supabase status

### Form stuck at "Creating..." (no error)
**Solution:**
1. Check backend terminal - there should be error logs
2. Restart backend server
3. Hard refresh browser (Ctrl+Shift+R)

## ✅ After Restarting

1. **Hard refresh browser**: `Ctrl + Shift + R`
2. **Fill company form again**
3. **Click "Next: Setup Branch"**
4. **Watch backend terminal** - you should see the request come in
5. **Should work!** ✅

## 🐛 Still Not Working?

**Check backend terminal output:**
- Copy any error messages you see
- The error will tell us exactly what's wrong

**Quick test:**
Visit: http://localhost:8000/api/companies
- If you see JSON (even empty array `[]`) → Backend is working
- If you see error → Backend has an issue

