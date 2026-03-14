# Render Environment Variables Setup Guide

This guide shows you exactly how to add environment variables to Render.

## 🎯 Quick Setup (3 Minutes)

### Method 1: Copy from File (Recommended)

1. Open `render-env-variables.txt` in this folder
2. Follow the instructions in that file
3. Copy each KEY and VALUE into Render dashboard

### Method 2: Manual Entry (Step-by-Step)

## 📝 Step-by-Step: Adding Variables to Render

### Step 1: Generate SECRET_KEY First

**Option A: Using Python Script**
```bash
cd pharmasight
python generate-secret-key.py
```
Copy the generated key.

**Option B: Using Python Command**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Copy the output.

### Step 2: Go to Render Dashboard

1. Log in to: https://dashboard.render.com
2. Click on your service: `pharmasight-backend`
3. Click **Environment** in the left sidebar

### Step 3: Add Each Variable

Click **Add Environment Variable** for each one:

#### Variable 1: DATABASE_URL

- **Key**: `DATABASE_URL`
- **Value**: `postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres`
- **Mark as Secret**: ✅ YES (click the lock icon 🔒)

#### Variable 2: DEBUG

- **Key**: `DEBUG`
- **Value**: `False`
- **Mark as Secret**: NO

#### Variable 3: SECRET_KEY

- **Key**: `SECRET_KEY`
- **Value**: *(Paste the key you generated in Step 1)*
- **Mark as Secret**: ✅ YES (click the lock icon 🔒)

Example SECRET_KEY format: `xK9mP2qR7vL4nJ8hT5wY3zA6bC1dE0fG1H2I3J4K5L6M7N8O9P0Q1R2S3T`

#### Variable 4: CORS_ORIGINS

- **Key**: `CORS_ORIGINS`
- **Value**: `*`
- **Mark as Secret**: NO

### Step 4: Save and Redeploy

1. After adding all variables, they're saved automatically
2. Go to **Manual Deploy** → **Clear build cache & deploy**
3. Or wait for auto-deploy on next git push

## ✅ Verification

After deployment, check logs to verify:

1. Go to **Logs** tab in Render
2. Look for:
   - ✅ No database connection errors
   - ✅ Server started successfully
   - ✅ Service is live

## 🔍 Quick Reference Table

| Variable | Value | Secret? | Required? |
|----------|-------|---------|-----------|
| `DATABASE_URL` | `postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres` | ✅ Yes | ✅ Yes |
| `DEBUG` | `False` | ❌ No | ✅ Yes |
| `SECRET_KEY` | `[Generate with script]` | ✅ Yes | ✅ Yes |
| `CORS_ORIGINS` | `*` | ❌ No | ✅ Yes |

## 🆘 Troubleshooting

### "Invalid environment variable"
- ✅ Check for extra spaces
- ✅ Check quotes are not included (Render adds them if needed)
- ✅ Verify key name is exact (case-sensitive)

### "Database connection failed"
- ✅ Verify `DATABASE_URL` is marked as Secret
- ✅ Check password has no extra spaces
- ✅ Ensure connection string is complete
- ✅ Test connection string locally first

### "SECRET_KEY not set"
- ✅ Verify SECRET_KEY is added
- ✅ Check it's marked as Secret
- ✅ Ensure no extra spaces in value

## 📋 Copy-Paste Ready Values

### DATABASE_URL (Mark as Secret)
```
postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
```

### DEBUG
```
False
```

### SECRET_KEY (Generate first, then paste - Mark as Secret)
```
[Run: python generate-secret-key.py]
```

### CORS_ORIGINS
```
*
```

## 🔒 Security Best Practices

1. ✅ **Always mark sensitive variables as Secret** (lock icon)
2. ✅ **Generate a unique SECRET_KEY** for production
3. ✅ **Don't use `*` for CORS_ORIGINS in production** - use your actual frontend URL
4. ✅ **Rotate SECRET_KEY** if compromised
5. ✅ **Never commit `.env` file** to git (already in .gitignore)

## 💡 Pro Tips

- **For Production**: Change `CORS_ORIGINS` to your actual frontend domain
  - Example: `https://pharmasight-frontend.onrender.com,https://yourdomain.com`

- **For Staging**: Use a separate Render service with different variables

- **Environment-Specific**: You can have different values for:
  - Development (local)
  - Staging (Render)
  - Production (Render)

## ✅ Checklist

Before deploying, verify:

- [ ] DATABASE_URL added and marked as Secret
- [ ] DEBUG set to `False`
- [ ] SECRET_KEY generated and added (marked as Secret)
- [ ] CORS_ORIGINS added
- [ ] All variables saved
- [ ] Service redeployed
- [ ] Logs show no errors
- [ ] `/health` endpoint works

## 🎉 Done!

Once all variables are set, your Render service will:
- ✅ Connect to Supabase database
- ✅ Run in production mode (DEBUG=False)
- ✅ Use secure secret key
- ✅ Allow CORS requests

Your PharmaSight backend is ready! 🚀

