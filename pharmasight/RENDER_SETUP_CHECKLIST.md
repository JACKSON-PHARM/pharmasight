# Render Environment Setup - Simple Checklist

## ✅ Pre-Deployment Checklist

### Step 1: Generate SECRET_KEY
- [ ] Open terminal in `pharmasight` folder
- [ ] Run: `python generate-secret-key.py`
- [ ] Copy the generated key (save it somewhere safe)
- [ ] Example output: `8hy2zb5i7tw4RLyd0o0a9osG1_hSUXdplZqNHyLqqTM`

### Step 2: Open Render Dashboard
- [ ] Go to: https://dashboard.render.com
- [ ] Navigate to your service: `pharmasight-backend`
- [ ] Click **Environment** in left sidebar

### Step 3: Add Environment Variables

For each variable below, click **"Add Environment Variable"**:

#### ✅ Variable 1: DATABASE_URL
- [ ] Key: `DATABASE_URL`
- [ ] Value: `postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres`
- [ ] ✅ Click lock icon to mark as Secret
- [ ] Click Save

#### ✅ Variable 2: DEBUG
- [ ] Key: `DEBUG`
- [ ] Value: `False`
- [ ] Do NOT mark as secret
- [ ] Click Save

#### ✅ Variable 3: SECRET_KEY
- [ ] Key: `SECRET_KEY`
- [ ] Value: `[Paste the key you generated in Step 1]`
- [ ] ✅ Click lock icon to mark as Secret
- [ ] Click Save

#### ✅ Variable 4: CORS_ORIGINS
- [ ] Key: `CORS_ORIGINS`
- [ ] Value: `*`
- [ ] Do NOT mark as secret
- [ ] Click Save

### Step 4: Verify All Variables
- [ ] All 4 variables are listed
- [ ] DATABASE_URL is marked as Secret (🔒 icon visible)
- [ ] SECRET_KEY is marked as Secret (🔒 icon visible)
- [ ] DEBUG = False
- [ ] CORS_ORIGINS = *

### Step 5: Deploy
- [ ] Go to **Manual Deploy** tab
- [ ] Click **Clear build cache & deploy**
- [ ] Wait 5-10 minutes for deployment
- [ ] Check **Logs** tab for any errors

### Step 6: Test Deployment
- [ ] Visit: `https://your-service.onrender.com/health`
- [ ] Should see: `{"status": "healthy"}`
- [ ] Visit: `https://your-service.onrender.com/docs`
- [ ] Should see API documentation
- [ ] ✅ Deployment successful!

## 📋 Quick Copy-Paste Reference

**Open `RENDER_ENV_COPY_PASTE.txt` for exact values to copy!**

## 🆘 Troubleshooting

If deployment fails:
- [ ] Check all variables are added correctly
- [ ] Verify DATABASE_URL has no extra spaces
- [ ] Ensure SECRET_KEY was generated and copied correctly
- [ ] Check Render logs for specific error messages
- [ ] Verify Supabase database is accessible

## 📝 Notes

- **Render doesn't accept .env file uploads** - must enter via dashboard
- **Use `RENDER_ENV_COPY_PASTE.txt`** for easy copy-paste
- **Generate SECRET_KEY** using the provided script
- **Mark sensitive variables** (DATABASE_URL, SECRET_KEY) as Secret
- **Different SECRET_KEY** for production (generate new one)

## ✅ Completion

Once all checkboxes are complete:
- ✅ Backend deployed to Render
- ✅ Connected to Supabase database
- ✅ Ready to use!

**Next**: Update frontend API URL to point to your Render service!

