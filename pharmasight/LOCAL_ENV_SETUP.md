# Local .env File Setup

## ⚠️ Important Note

The `.env` file is **already in `.gitignore`**, so it's safe to create locally. However, **Render does NOT allow uploading .env files directly**. You must enter environment variables through Render's dashboard.

## 📁 Files Created

1. **`.env`** - For LOCAL development only (already configured, blocked from git)
2. **`render-env-variables.txt`** - Reference guide for Render
3. **`RENDER_ENV_COPY_PASTE.txt`** - Copy-paste ready values
4. **`generate-secret-key.py`** - Script to generate SECRET_KEY
5. **`generate-secret-key.bat`** - Windows batch script

## 🖥️ Local Development (.env file)

The `.env` file is already configured for local development with your Supabase credentials. You can use it locally:

```bash
# The .env file exists and has these values:
DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres
DEBUG=True
SECRET_KEY=local-dev-secret-key-change-in-production-2025
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

**This file is safe** - it's already in `.gitignore` and won't be committed to GitHub.

## 🚀 Render Setup (Dashboard Entry)

Render requires entering variables through their dashboard. Use these files to help:

### Quick Method:

1. **Open**: `RENDER_ENV_COPY_PASTE.txt`
2. **Generate SECRET_KEY**:
   - Windows: Double-click `generate-secret-key.bat`
   - Or: `python generate-secret-key.py`
3. **Copy values** from the file into Render dashboard
4. **Mark secrets** (DATABASE_URL and SECRET_KEY) with lock icon

### Step-by-Step:

See `RENDER_ENV_SETUP.md` for detailed instructions.

## 🔑 Generate SECRET_KEY

### Windows:
```batch
# Option 1: Double-click
generate-secret-key.bat

# Option 2: Command Prompt
python generate-secret-key.py

# Option 3: One-liner
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Mac/Linux:
```bash
python generate-secret-key.py
# Or
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## ✅ Summary

- ✅ `.env` file exists locally (safe, won't be committed)
- ✅ Use `.env` for local development
- ✅ Use `RENDER_ENV_COPY_PASTE.txt` for Render dashboard
- ✅ Use `generate-secret-key.py` to create SECRET_KEY
- ✅ Never commit `.env` (already protected)

## 🔒 Security Reminder

- ✅ `.env` is in `.gitignore` (safe)
- ✅ Never commit passwords
- ✅ Use different SECRET_KEY for production
- ✅ Mark sensitive variables as Secret in Render

