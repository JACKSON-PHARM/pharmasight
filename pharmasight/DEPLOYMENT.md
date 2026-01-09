# PharmaSight Deployment Guide

This guide walks you through deploying PharmaSight to GitHub, Supabase, and Render.

## 📋 Prerequisites

- GitHub account
- Supabase account (already created)
- Render account (free tier available)

## 🗄️ Step 1: Set Up Supabase Database

### 1.1 Run Database Schema

1. Go to your Supabase project: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt
2. Click on **SQL Editor** in the sidebar
3. Click **New Query**
4. Open `database/schema.sql` from this project
5. Copy the entire contents
6. Paste into Supabase SQL Editor
7. Click **Run** (or press Cmd/Ctrl + Enter)
8. Verify tables were created by checking the **Table Editor** section

### 1.2 Get Your Connection Details

Your Supabase connection details:
- **Host**: `db.kwvkkbofubsjiwqlqakt.supabase.co`
- **Database**: `postgres`
- **User**: `postgres`
- **Password**: `6iP.zRY6QyK8L*Z`
- **Port**: `5432`

Connection String:
```
postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
```

## 🔐 Step 2: Set Up Local Environment

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Update `.env` with your values:
   ```env
   DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
   DEBUG=True
   SECRET_KEY=your-secret-key-here
   ```

3. **Important**: Add `.env` to `.gitignore` (already done) - never commit passwords!

## 📦 Step 3: Push to GitHub

### 3.1 Initialize Git Repository

```bash
cd pharmasight
git init
```

### 3.2 Configure Git (if not already done)

```bash
git config --global user.name "Your Name"
git config --global user.email "your-email@example.com"
```

### 3.3 Add Files and Commit

```bash
# Add all files
git add .

# Check what will be committed (make sure .env is NOT listed)
git status

# Commit
git commit -m "Initial commit: PharmaSight pharmacy management system"
```

### 3.4 Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `pharmasight` (or your preferred name)
3. Description: "Pharmacy Management System with Inventory Intelligence"
4. Choose **Private** (recommended) or **Public**
5. **DO NOT** initialize with README, .gitignore, or license
6. Click **Create repository**

### 3.5 Push to GitHub

GitHub will show you commands, but here they are:

```bash
# Add remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/pharmasight.git

# Or if using SSH:
# git remote add origin git@github.com:YOUR_USERNAME/pharmasight.git

# Push to GitHub
git branch -M main
git push -u origin main
```

If asked for credentials:
- **Username**: Your GitHub username
- **Password**: Use a Personal Access Token (not your GitHub password)
  - Create one at: https://github.com/settings/tokens
  - Select scope: `repo`

## 🚀 Step 4: Deploy to Render

### 4.1 Create Render Account

1. Go to https://render.com
2. Sign up with GitHub (recommended)
3. Connect your GitHub account

### 4.2 Create Web Service

1. In Render dashboard, click **New +** → **Web Service**
2. Connect your GitHub repository:
   - Click **Connect account** if needed
   - Select `pharmasight` repository
   - Click **Connect**

3. Configure service:
   - **Name**: `pharmasight-backend`
   - **Region**: Choose closest (Oregon recommended)
   - **Branch**: `main`
   - **Root Directory**: Leave blank (or `backend` if you prefer)
   - **Runtime**: `Python 3`
   - **Build Command**: 
     ```bash
     pip install -r backend/requirements.txt
     ```
   - **Start Command**:
     ```bash
     cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
     ```
   - **Plan**: Free (or Hobby if you need more)

### 4.3 Set Environment Variables in Render

In the Render service settings, go to **Environment** and add:

```
DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
DEBUG=False
SECRET_KEY=generate-a-strong-random-key-here
CORS_ORIGINS=*
```

**Important Notes:**
- Render will provide a URL like: `https://pharmasight-backend.onrender.com`
- Free tier services spin down after 15 minutes of inactivity
- First deployment takes 5-10 minutes

### 4.4 Deploy

1. Click **Create Web Service**
2. Render will:
   - Clone your repo
   - Install dependencies
   - Start your service
3. Wait for deployment (watch logs)
4. Once deployed, you'll get a URL like: `https://pharmasight-backend-xxx.onrender.com`

### 4.5 Update Frontend API URL

After deployment, update your frontend `js/config.js`:

```javascript
API_BASE_URL: 'https://your-render-app.onrender.com'
```

Or update in Settings page after deploying frontend.

## 🌐 Step 5: Deploy Frontend (Optional)

### Option A: Render Static Site

1. In Render, click **New +** → **Static Site**
2. Connect your GitHub repo
3. Configure:
   - **Name**: `pharmasight-frontend`
   - **Build Command**: (leave empty or `echo "No build needed"`)
   - **Publish Directory**: `frontend`
4. Deploy

### Option B: GitHub Pages (Free)

1. Go to your GitHub repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / `frontend` folder
4. Save
5. Your site will be at: `https://YOUR_USERNAME.github.io/pharmasight/`

### Option C: Netlify (Alternative)

1. Go to https://netlify.com
2. Connect GitHub
3. Select repo
4. Publish directory: `frontend`
5. Deploy

## ✅ Step 6: Verify Deployment

### Test Backend

1. Visit: `https://your-render-app.onrender.com/health`
   - Should return: `{"status": "healthy"}`

2. Visit: `https://your-render-app.onrender.com/docs`
   - Should show FastAPI documentation

### Test Database Connection

1. Check Render logs for any database connection errors
2. If errors, verify `DATABASE_URL` in Render environment variables
3. Make sure Supabase allows connections from Render IPs (usually enabled by default)

## 🔧 Troubleshooting

### Database Connection Issues

**Error**: `could not connect to server`

**Solutions**:
1. Verify password is correct (no extra spaces)
2. Check Supabase project is active
3. Ensure connection string is correct
4. Check Supabase → Settings → Database → Connection pooling (optional)

### Build Failures on Render

**Error**: `Module not found` or `Import error`

**Solutions**:
1. Verify `requirements.txt` includes all dependencies
2. Check build logs in Render dashboard
3. Ensure Python version is compatible (Python 3.10+)

### CORS Issues

**Error**: `CORS policy blocked`

**Solutions**:
1. Update `CORS_ORIGINS` in Render environment variables
2. Add your frontend URL to the list
3. For development: use `*` (not recommended for production)

### Services Spinning Down (Free Tier)

**Issue**: Service takes time to respond after inactivity

**Solutions**:
1. This is normal for Render free tier
2. First request after 15 min takes 30-60 seconds
3. Consider upgrading to Hobby plan for always-on
4. Or use a ping service to keep it awake (e.g., uptimerobot.com)

## 📝 Quick Reference

### Connection String Template
```
postgresql://postgres:PASSWORD@db.PROJECT_ID.supabase.co:5432/postgres
```

Your connection string:
```
postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
```

### Render Environment Variables
```
DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
DEBUG=False
SECRET_KEY=your-generated-secret-key
CORS_ORIGINS=*
```

### Local Testing

Before deploying, test locally:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Visit: http://localhost:8000/docs

## 🎉 Success Checklist

- [ ] Database schema run in Supabase
- [ ] Tables visible in Supabase Table Editor
- [ ] Code pushed to GitHub
- [ ] Render service created
- [ ] Environment variables set in Render
- [ ] Backend deployed and accessible
- [ ] `/health` endpoint returns success
- [ ] `/docs` shows API documentation
- [ ] Frontend updated with Render URL (if deploying frontend)

## 🔒 Security Notes

1. **Never commit**:
   - `.env` file
   - Passwords
   - API keys
   - Secret keys

2. **Always use environment variables** for sensitive data

3. **Use strong SECRET_KEY** in production:
   ```python
   import secrets
   print(secrets.token_urlsafe(32))
   ```

4. **Restrict CORS_ORIGINS** in production to your actual frontend domain

5. **Enable Supabase Row Level Security (RLS)** for production

## 📞 Need Help?

- Render Docs: https://render.com/docs
- Supabase Docs: https://supabase.com/docs
- FastAPI Docs: https://fastapi.tiangolo.com

