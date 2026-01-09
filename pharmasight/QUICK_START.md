# PharmaSight Quick Start Guide

## 🚀 Fast Setup (5 Minutes)

### 1. Supabase Setup (2 min)

1. Open: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
2. Open `database/schema.sql` in this project
3. Copy entire file
4. Paste in Supabase SQL Editor
5. Click **Run**
6. ✅ Done!

### 2. Local Testing (1 min)

```bash
# Terminal 1: Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Terminal 2: Frontend (optional)
cd frontend
python -m http.server 3000
```

Visit: http://localhost:8000/docs

### 3. GitHub Push (1 min)

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/pharmasight.git
git push -u origin main
```

**Note**: You'll need to provide your GitHub email. Replace `YOUR_USERNAME` with your actual GitHub username.

### 4. Render Deploy (1 min)

1. Go to: https://render.com
2. **New +** → **Web Service**
3. Connect GitHub repo
4. Settings:
   - **Name**: `pharmasight-backend`
   - **Build Command**: `pip install -r backend/requirements.txt`
   - **Start Command**: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Environment Variables**:
   ```
   DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
   DEBUG=False
   SECRET_KEY=generate-a-random-key
   ```
6. **Create Web Service**
7. ✅ Wait 5-10 minutes for deployment

### Your URLs

- **Backend API**: `https://pharmasight-backend-xxx.onrender.com`
- **API Docs**: `https://pharmasight-backend-xxx.onrender.com/docs`
- **Health Check**: `https://pharmasight-backend-xxx.onrender.com/health`

## 📝 What You Need

- ✅ Supabase project: `kwvkkbofubsjiwqlqakt`
- ✅ Password: `6iP.zRY6QyK8L*Z`
- ⚠️ GitHub email: (you'll provide when pushing)
- ⚠️ GitHub username: (for repository URL)

## 🎯 Next Steps After Deployment

1. **Get Company & Branch IDs**:
   - Query Supabase database or create via API
   - Save in frontend Settings

2. **Add Items**: Use Items page

3. **Create GRN**: Add purchases

4. **Process Sales**: Use POS page

## ⚠️ Important

- Never commit `.env` file
- Never share your password publicly
- Use environment variables in Render
- Free Render tier spins down after 15 min inactivity

## 🆘 Quick Troubleshooting

**Database error?**
- Check connection string in Render
- Verify Supabase project is active

**Build failed?**
- Check `requirements.txt` exists
- Verify Python 3.10+ is selected

**CORS error?**
- Add frontend URL to `CORS_ORIGINS`
- Or use `*` for testing (not production)

