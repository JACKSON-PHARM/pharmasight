# ⚡ Quick Start Guide - Run PharmaSight Locally

## 🚀 Start Everything with One Command

### Windows (Easiest)

**Just double-click:** `start.bat`

Or run from terminal:
```batch
start.bat
```

This will:
- ✅ Start backend server (http://localhost:8000)
- ✅ Start frontend server (http://localhost:3000)
- ✅ Open separate windows for each server
- ✅ Show you all the URLs you need

### PowerShell

```powershell
.\start.ps1
```

### Python

```powershell
python start.py
```

## 📋 Prerequisites Check

Before running, make sure:

1. ✅ **Database Schema is Set Up**
   - Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
   - Run the SQL from `database/schema.sql`

2. ✅ **Virtual Environment is Created**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r backend/requirements.txt
   ```

3. ✅ **.env File Exists**
   - Should be in `pharmasight/` directory
   - Contains: DATABASE_URL, DEBUG, SECRET_KEY, CORS_ORIGINS

## 🌐 Access Your Application

Once servers are running:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## 🛑 Stop the Servers

- **Batch/PowerShell**: Close the command windows
- **Python script**: Press `Ctrl+C`

## 🐛 Troubleshooting

**Backend won't start?**
- Check that virtual environment is activated
- Verify `.env` file exists
- Make sure port 8000 is not in use

**Frontend won't start?**
- Make sure port 3000 is not in use
- Check that Python HTTP server is available

**Can't connect to database?**
- Verify database schema is run in Supabase
- Check `.env` has correct DATABASE_URL
- Test connection in Supabase dashboard

For detailed information, see: `LOCAL_RUN_GUIDE.md`
