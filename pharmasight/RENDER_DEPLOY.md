# Render Deployment Guide - Step by Step

## 🎯 Quick Deploy (10 Minutes)

### Prerequisites
- ✅ Code pushed to GitHub
- ✅ Supabase database schema run
- ✅ Render account (sign up at render.com)

## 📝 Step-by-Step Instructions

### Step 1: Sign Up / Login to Render

1. Go to: https://render.com
2. Click **Get Started for Free**
3. Sign up with **GitHub** (recommended - easier integration)
4. Authorize Render to access your GitHub account

### Step 2: Create New Web Service

1. In Render dashboard, click **New +** button (top right)
2. Select **Web Service**
3. You'll see a list of your GitHub repositories

### Step 3: Connect Repository

1. Find `pharmasight` in your repositories list
2. If you don't see it:
   - Click **Configure account**
   - Select repositories to give Render access
   - Refresh the page
3. Click **Connect** next to `pharmasight`

### Step 4: Configure Service Settings

Fill in these settings:

#### Basic Settings:
- **Name**: `pharmasight-backend` (or your preferred name)
- **Region**: Choose closest to you (Oregon is good default)
- **Branch**: `main` (or `master` if that's your default)
- **Root Directory**: Leave **empty** (or type `backend` if you want)
- **Runtime**: **Python 3**
- **Python Version**: Select **Python 3.11** or latest available

#### Build Settings:
- **Build Command**: 
  ```bash
  pip install -r backend/requirements.txt
  ```
  
- **Start Command**: 
  ```bash
  cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
  ```

#### Plan:
- **Free** (for testing) - spins down after 15 min inactivity
- **Hobby** ($7/month) - always on, better for production

### Step 5: Set Environment Variables

Scroll down to **Environment Variables** section and click **Add Environment Variable** for each:

#### Required Variables:

1. **DATABASE_URL**
   - Key: `DATABASE_URL`
   - Value: `postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres`
   - ✅ **Mark as Secret** (click the lock icon)

2. **DEBUG**
   - Key: `DEBUG`
   - Value: `False`

3. **SECRET_KEY**
   - Key: `SECRET_KEY`
   - Value: Generate a random key:
     ```python
     # Run this in Python to generate:
     import secrets
     print(secrets.token_urlsafe(32))
     ```
   - Or use: `pharmasight-secret-key-2025-$(openssl rand -hex 16)`
   - ✅ **Mark as Secret**

4. **CORS_ORIGINS**
   - Key: `CORS_ORIGINS`
   - Value: `*` (for development) or your frontend URL (for production)

#### Optional Variables:
- `SUPABASE_URL`: `https://kwvkkbofubsjiwqlqakt.supabase.co`
- `SUPABASE_KEY`: Your Supabase anon key (if needed later)

### Step 6: Create and Deploy

1. Scroll to bottom
2. Click **Create Web Service**
3. Render will start building:
   - Clones your repo
   - Installs dependencies
   - Starts the service
4. **Wait 5-10 minutes** for first deployment
5. Watch the logs to see progress

### Step 7: Get Your Service URL

Once deployed:
1. You'll see a URL like: `https://pharmasight-backend-xxx.onrender.com`
2. Click on it to test
3. Visit `/health` endpoint: `https://pharmasight-backend-xxx.onrender.com/health`
4. Should see: `{"status": "healthy"}`

### Step 8: Test API Documentation

Visit: `https://pharmasight-backend-xxx.onrender.com/docs`

You should see the FastAPI Swagger documentation.

## ✅ Verification Checklist

After deployment, verify:

- [ ] Service shows "Live" status in Render dashboard
- [ ] `/health` endpoint returns `{"status": "healthy"}`
- [ ] `/docs` shows API documentation
- [ ] No errors in Render logs
- [ ] Database connection works (check logs for errors)

## 🔧 Common Issues & Solutions

### Issue: "Build failed" / "Module not found"
**Solution**: 
- Check `requirements.txt` exists in `backend/` folder
- Verify all dependencies are listed
- Check build logs for specific error

### Issue: "Database connection failed"
**Solution**:
- Verify `DATABASE_URL` is correct in environment variables
- Check password has no extra spaces
- Ensure Supabase project is active
- Try connection string in a database client first

### Issue: "Port already in use"
**Solution**:
- Use `$PORT` variable (already in start command)
- Render automatically sets PORT

### Issue: "Service spins down"
**Solution**:
- Normal for free tier after 15 min inactivity
- First request after spin-down takes 30-60 seconds
- Upgrade to Hobby plan for always-on
- Or use uptimerobot.com to ping service

### Issue: "CORS errors"
**Solution**:
- Update `CORS_ORIGINS` in environment variables
- Add your frontend URL
- For testing: use `*` (not recommended for production)

## 📊 Monitoring

### View Logs:
1. In Render dashboard, click your service
2. Click **Logs** tab
3. See real-time logs

### Restart Service:
- Click **Manual Deploy** → **Clear build cache & deploy**

### Update Service:
- Push to GitHub
- Render auto-deploys (if auto-deploy is enabled)
- Or click **Manual Deploy**

## 🔄 Auto-Deploy Setup

By default, Render auto-deploys on push to main branch:
1. Make changes locally
2. Commit: `git commit -m "Your changes"`
3. Push: `git push`
4. Render automatically rebuilds and deploys
5. Wait 2-5 minutes for deployment

## 🔐 Security Best Practices

1. ✅ Mark sensitive variables as "Secret" in Render
2. ✅ Use strong SECRET_KEY
3. ✅ Restrict CORS_ORIGINS in production
4. ✅ Set DEBUG=False in production
5. ✅ Enable Supabase Row Level Security (RLS)

## 📝 Your Deployment URLs

After deployment, save these:

- **API Base URL**: `https://pharmasight-backend-xxx.onrender.com`
- **Health Check**: `https://pharmasight-backend-xxx.onrender.com/health`
- **API Docs**: `https://pharmasight-backend-xxx.onrender.com/docs`

**Update Frontend**: Change `API_BASE_URL` in `frontend/js/config.js` to your Render URL.

## 🎉 Next Steps

1. ✅ Backend deployed
2. ⏭️ Update frontend API URL
3. ⏭️ Deploy frontend (optional - can use Render Static Site or GitHub Pages)
4. ⏭️ Test full system end-to-end
5. ⏭️ Set up opening stock data

## 💡 Pro Tips

- **Free tier limitation**: First request after inactivity is slow (cold start)
- **Hobby plan ($7/month)**: Better for production - always on, faster
- **Custom domain**: Can add custom domain in Render settings
- **Environment**: Can have separate services for staging/production

