# 🚀 Local Development Guide - Running PharmaSight

This guide will help you run PharmaSight locally using Supabase as your database.

## ✅ Prerequisites Check

1. **Python 3.8+ installed** ✅ (You have Python 3.13.7)
2. **Virtual environment created** ✅ (Done)
3. **Dependencies installed** ✅ (Done)
4. **.env file created** ✅ (Done)
5. **Database connection working** ✅ (Verified)

## 📋 Step 1: Set Up Database Schema in Supabase

**IMPORTANT**: Before the app will work fully, you need to run the database schema in Supabase.

### Option A: Using Supabase Dashboard (Recommended)

1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
2. Open the file: `database/schema.sql` from this project
3. Copy ALL the contents (Ctrl+A, Ctrl+C)
4. Paste into Supabase SQL Editor
5. Click **Run** (or press Ctrl+Enter)
6. Wait for completion (should take 10-30 seconds)
7. Verify: Go to **Table Editor** - you should see tables like:
   - `companies`
   - `branches`
   - `items`
   - `inventory_ledger`
   - `sales_invoices`
   - etc.

### Option B: Using psql (Command Line)

```bash
psql "postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres" -f database/schema.sql
```

## 🖥️ Step 2 & 3: Start Both Servers (Backend & Frontend)

### 🚀 Method 1: Single Command - Start Everything (RECOMMENDED)

**Option A: Using Batch File (Easiest - Just Double-Click!)**
```batch
# Simply double-click: start.bat
# OR run from terminal:
cd C:\PharmaSight\pharmasight
start.bat
```

**Option B: Using PowerShell Script**
```powershell
cd C:\PharmaSight\pharmasight
.\start.ps1
```

**Option C: Using Python Script**
```powershell
cd C:\PharmaSight\pharmasight
python start.py
```

All three methods will:
- ✅ Start the backend server on http://localhost:8000
- ✅ Start the frontend server on http://localhost:3000
- ✅ Open separate windows for each server (batch/PS) or run in one terminal (Python)
- ✅ Allow you to see logs from both servers

### Method 2: Manual Start (If you prefer separate terminals)

**Terminal 1 - Backend:**
```powershell
cd C:\PharmaSight\pharmasight
.\venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD\backend"
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - Frontend:**
```powershell
cd C:\PharmaSight\pharmasight\frontend
python -m http.server 3000
```

### Verify Servers are Running

Open your browser and visit:
- **Backend API Root**: http://localhost:8000/
- **Health Check**: http://localhost:8000/health
- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc
- **Frontend**: http://localhost:3000

You should see:
- JSON response with app name and version from backend
- `{"status": "healthy"}` from `/health`
- Interactive API documentation at `/docs`
- Your PharmaSight frontend application

## 🌐 Step 4: Access the Application

1. **Frontend**: Open http://localhost:3000 (or the port you chose)
2. **Backend API**: http://localhost:8000
3. **API Docs**: http://localhost:8000/docs

## 🔧 Configuration

### Backend Configuration

The backend is configured via `.env` file (already created):
```env
DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
DEBUG=True
SECRET_KEY=HAlPg6zyTzeEAcYdmnC9c9MbQHSHiEAUk9qEjefRkDA
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:8000,http://127.0.0.1:5500,http://127.0.0.1:3000
```

### Frontend Configuration

The frontend API URL is configured in `frontend/js/config.js`:
```javascript
const CONFIG = {
    API_BASE_URL: 'http://localhost:8000',
    // ...
}
```

If your backend runs on a different port, update this file.

## 📝 Testing the Setup

### Test 1: Backend Health Check
```powershell
curl http://localhost:8000/health
# Should return: {"status":"healthy"}
```

### Test 2: API Documentation
Visit: http://localhost:8000/docs
- You should see interactive API documentation
- Try the `/health` endpoint

### Test 3: Database Connection
```powershell
$env:PYTHONPATH = "C:\PharmaSight\pharmasight\backend"
cd C:\PharmaSight\pharmasight\backend
python -c "from app.database import engine; from sqlalchemy import text; conn = engine.connect(); result = conn.execute(text('SELECT COUNT(*) FROM companies')); print('Tables exist:', result.scalar()); conn.close()"
```

## 🐛 Troubleshooting

### Backend won't start

**Error: Module not found**
- Solution: Make sure virtual environment is activated and dependencies are installed:
  ```powershell
  .\venv\Scripts\Activate.ps1
  pip install -r backend/requirements.txt
  ```

**Error: Database connection failed**
- Check: `.env` file exists and has correct `DATABASE_URL`
- Verify: Database schema has been run in Supabase
- Test: Connection string works in Supabase dashboard

**Error: Port 8000 already in use**
- Solution: Change port or stop the process using port 8000:
  ```powershell
  # Find process using port 8000
  netstat -ano | findstr :8000
  # Kill the process (replace PID with actual process ID)
  taskkill /PID <PID> /F
  ```

### Frontend can't connect to backend

**Error: CORS error in browser console**
- Check: Backend CORS_ORIGINS includes your frontend URL
- Verify: Backend is running on the correct port
- Solution: Update `.env` CORS_ORIGINS and restart backend

**Error: 404 on API calls**
- Check: Frontend `config.js` has correct `API_BASE_URL`
- Verify: Backend is actually running
- Test: Visit http://localhost:8000/docs to verify backend

### Database issues

**Error: Table doesn't exist**
- Solution: Run the database schema in Supabase (see Step 1)

**Error: Permission denied**
- Check: Database credentials in `.env` are correct
- Verify: Supabase project is active

## 🎯 Next Steps

Once everything is running:

1. **Create a Company**: Use the API or frontend to create your first company
2. **Create a Branch**: Set up your first branch/location
3. **Add Items**: Start adding inventory items
4. **Test Features**: Try creating purchases, sales, and inventory transactions

## 📚 Useful URLs

- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Frontend**: http://localhost:3000
- **Supabase Dashboard**: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt

## 🆘 Need Help?

- Check the logs in your terminal for error messages
- Review the API documentation at `/docs`
- Verify database schema is correctly set up
- Ensure all environment variables are set correctly

