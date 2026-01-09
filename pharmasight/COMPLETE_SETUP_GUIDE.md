# 🚀 Complete Setup Guide - GitHub, Supabase, and Render

This is your complete step-by-step guide to deploy PharmaSight.

## 📋 What You Have

✅ **Supabase Project**: `kwvkkbofubsjiwqlqakt`  
✅ **Password**: `6iP.zRY6QyK8L*Z`  
✅ **Database Connection**: Already configured in `.env.example`

## 🗄️ PART 1: Supabase Database Setup (5 minutes)

### Step 1.1: Run Database Schema

1. **Open Supabase SQL Editor**:
   - Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
   - Or: Dashboard → SQL Editor → New Query

2. **Copy Schema**:
   - Open `database/schema.sql` from this project
   - Select all (Ctrl+A / Cmd+A) and copy

3. **Paste and Run**:
   - Paste into Supabase SQL Editor
   - Click **Run** button (or press Cmd/Ctrl + Enter)
   - Wait for completion (should take 10-30 seconds)

4. **Verify**:
   - Go to **Table Editor** in Supabase
   - You should see tables: `companies`, `items`, `inventory_ledger`, etc.
   - ✅ Database ready!

### Step 1.2: Connection String (For Reference)

Your connection string for Render:
```
postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
```

## 📦 PART 2: GitHub Setup (5 minutes)

### Step 2.1: Configure Git (First Time Only)

**Windows (PowerShell or CMD)**:
```powershell
cd C:\PharmaSight
git config --global user.name "Your Name"
git config --global user.email "your-github-email@example.com"
```

**Mac/Linux**:
```bash
cd ~/PharmaSight
git config --global user.name "Your Name"
git config --global user.email "your-github-email@example.com"
```

⚠️ **Replace with your actual GitHub email!**

### Step 2.2: Initialize Repository

```bash
# Navigate to project folder
cd pharmasight

# Initialize git
git init

# Check status (verify .env is NOT listed)
git status
```

### Step 2.3: Create .env File (Local Only)

Create a `.env` file in the root with:

```env
DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
DEBUG=True
SECRET_KEY=your-local-secret-key-here
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

**Important**: This file is already in `.gitignore` and won't be committed.

### Step 2.4: Add and Commit Files

```bash
# Add all files
git add .

# Verify .env is NOT in the list
git status

# Commit
git commit -m "Initial commit: PharmaSight pharmacy management system"
```

### Step 2.5: Create GitHub Repository

1. **Go to GitHub**: https://github.com/new
2. **Repository name**: `pharmasight`
3. **Description**: `Pharmacy Management System with Inventory Intelligence`
4. **Visibility**: 
   - ✅ **Private** (recommended - keeps your code safe)
   - Or Public (if you want to share)
5. **DO NOT check** any boxes (README, .gitignore, license)
6. Click **Create repository**

### Step 2.6: Push to GitHub

```bash
# Add remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/pharmasight.git

# Rename branch to main
git branch -M main

# Push to GitHub
git push -u origin main
```

### Step 2.7: Authentication

When prompted for credentials:

**Option A: Personal Access Token (Recommended)**
1. Go to: https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Name: `pharmasight-deploy`
4. Select scope: ✅ `repo`
5. Click **Generate token**
6. **Copy the token** (save it securely!)
7. When git asks for password: **paste the token** (not your GitHub password)

**Option B: GitHub CLI**
```bash
gh auth login
git push -u origin main
```

### Step 2.8: Verify

1. Visit: `https://github.com/YOUR_USERNAME/pharmasight`
2. You should see all your files
3. ✅ GitHub setup complete!

## 🚀 PART 3: Render Deployment (10 minutes)

### Step 3.1: Sign Up for Render

1. Go to: https://render.com
2. Click **Get Started for Free**
3. **Sign up with GitHub** (recommended - easier setup)
4. Authorize Render to access your GitHub account

### Step 3.2: Create Web Service

1. In Render dashboard, click **New +** → **Web Service**
2. Find `pharmasight` in your repositories
3. Click **Connect** next to it

### Step 3.3: Configure Settings

Fill in these **exact** settings:

**Basic Settings:**
- **Name**: `pharmasight-backend`
- **Region**: `Oregon` (or closest to you)
- **Branch**: `main`
- **Root Directory**: *(leave empty)*
- **Runtime**: `Python 3`
- **Python Version**: `3.11` (or latest)

**Build & Start:**
- **Build Command**: 
  ```
  pip install -r backend/requirements.txt
  ```
- **Start Command**: 
  ```
  cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
  ```
- **Plan**: `Free` (for testing) or `Hobby` ($7/month - always on)

### Step 3.4: Add Environment Variables

Click **Add Environment Variable** for each:

| Key | Value | Secret? |
|-----|-------|---------|
| `DATABASE_URL` | `postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres` | ✅ Yes |
| `DEBUG` | `False` | No |
| `SECRET_KEY` | Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"` | ✅ Yes |
| `CORS_ORIGINS` | `*` | No |

**How to generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output and paste as `SECRET_KEY` value.

### Step 3.5: Deploy

1. Scroll to bottom
2. Click **Create Web Service**
3. **Wait 5-10 minutes** for first deployment
4. Watch the logs - you'll see:
   - ✅ Cloning repository
   - ✅ Installing dependencies
   - ✅ Starting service
   - ✅ Service is live!

### Step 3.6: Get Your URL

Once deployed:
- Your service URL: `https://pharmasight-backend-xxx.onrender.com`
- **Save this URL!**

### Step 3.7: Test Deployment

1. **Health Check**: 
   - Visit: `https://pharmasight-backend-xxx.onrender.com/health`
   - Should see: `{"status": "healthy"}`

2. **API Documentation**:
   - Visit: `https://pharmasight-backend-xxx.onrender.com/docs`
   - Should see FastAPI Swagger UI

3. ✅ Backend deployed!

## 🌐 PART 4: Update Frontend (2 minutes)

### Option A: Update Config File

Edit `frontend/js/config.js`:
```javascript
const CONFIG = {
    API_BASE_URL: 'https://pharmasight-backend-xxx.onrender.com',  // Your Render URL
    // ... rest of config
};
```

### Option B: Update in Settings Page

1. Open frontend in browser
2. Go to **Settings**
3. Enter your Render URL
4. Save

## ✅ Verification Checklist

After completing all steps:

- [ ] ✅ Database schema run in Supabase
- [ ] ✅ Tables visible in Supabase Table Editor
- [ ] ✅ Code pushed to GitHub
- [ ] ✅ Render service created
- [ ] ✅ Environment variables set in Render
- [ ] ✅ Service deployed and "Live"
- [ ] ✅ `/health` endpoint works
- [ ] ✅ `/docs` shows API documentation
- [ ] ✅ Frontend updated with Render URL

## 🔧 Troubleshooting

### Database Connection Failed
- ✅ Check `DATABASE_URL` in Render environment variables
- ✅ Verify password has no extra spaces
- ✅ Ensure Supabase project is active
- ✅ Check Render logs for specific error

### Build Failed
- ✅ Check `requirements.txt` exists in `backend/`
- ✅ Verify Python version is 3.10+
- ✅ Check build logs for specific error

### Service Won't Start
- ✅ Verify start command uses `$PORT`
- ✅ Check logs for error messages
- ✅ Ensure all environment variables are set

### CORS Errors
- ✅ Update `CORS_ORIGINS` in Render
- ✅ Add your frontend URL
- ✅ For testing: use `*`

## 📞 Quick Reference

### Your Supabase Details:
```
Project ID: kwvkkbofubsjiwqlqakt
Password: 6iP.zRY6QyK8L*Z
Host: db.kwvkkbofubsjiwqlqakt.supabase.co
Connection: postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
```

### Render Environment Variables:
```
DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
DEBUG=False
SECRET_KEY=<generate-random-key>
CORS_ORIGINS=*
```

## 🎉 Success!

Once everything is deployed:
1. ✅ Backend is live on Render
2. ✅ Database is connected
3. ✅ Frontend can connect to API
4. ✅ Ready to start using PharmaSight!

**Next Steps:**
1. Set Company and Branch IDs in frontend Settings
2. Add your first items
3. Create a GRN
4. Process your first sale!

---

**Need Help?** Check the individual guides:
- `GITHUB_SETUP.md` - Detailed GitHub instructions
- `RENDER_DEPLOY.md` - Detailed Render instructions
- `DEPLOYMENT.md` - General deployment info

