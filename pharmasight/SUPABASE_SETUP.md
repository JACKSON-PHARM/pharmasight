# 🔐 Supabase Configuration Setup Guide

This guide shows you exactly where to find your Supabase credentials and how to configure them.

## 📍 Step 1: Get Your Supabase Credentials

### 1.1 Go to Supabase Dashboard

1. Open your Supabase project: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt
2. Click on **Settings** (gear icon) in the left sidebar
3. Click on **API** in the settings menu

### 1.2 Find Your Credentials

You'll see a page with several sections. Here's what you need:

#### **Project URL** (SUPABASE_URL)
- Look for **"Project URL"** section
- Copy the URL (e.g., `https://kwvkkbofubsjiwqlqakt.supabase.co`)
- This is your `SUPABASE_URL`

#### **anon/public key** (SUPABASE_KEY / SUPABASE_ANON_KEY)
- Look for **"Project API keys"** section
- Find the key labeled **"anon"** or **"public"**
- Click the **eye icon** to reveal it (or click "Reveal")
- Copy this key - this is your `SUPABASE_KEY` (for frontend) and `SUPABASE_ANON_KEY`

#### **service_role key** (SUPABASE_SERVICE_ROLE_KEY)
- In the same **"Project API keys"** section
- Find the key labeled **"service_role"**
- ⚠️ **WARNING**: This key has admin privileges! Keep it secret!
- Click the **eye icon** to reveal it
- Copy this key - this is your `SUPABASE_SERVICE_ROLE_KEY` (backend only!)

### 1.3 Database Password (if needed)

If you need the database password:
1. Go to **Settings** → **Database**
2. Look for **"Connection string"** or **"Database password"**
3. Your password is: `6iP.zRY6QyK8L*Z` (from your project)

---

## 🔧 Step 2: Configure Backend (.env file)

### 2.1 Create .env file

1. Navigate to the `backend` folder:
   ```bash
   cd pharmasight/backend
   ```

2. Copy the example file:
   ```bash
   # Windows
   copy .env.example .env
   
   # Mac/Linux
   cp .env.example .env
   ```

### 2.2 Edit .env file

Open `.env` in a text editor and fill in your values:

```env
# Supabase Auth Configuration
SUPABASE_URL=https://kwvkkbofubsjiwqlqakt.supabase.co
SUPABASE_KEY=your-anon-key-from-dashboard
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-from-dashboard

# Database (if not using DATABASE_URL)
SUPABASE_DB_HOST=db.kwvkkbofubsjiwqlqakt.supabase.co
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=6iP.zRY6QyK8L*Z

# Or use full connection string:
DATABASE_URL=postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres

# App Configuration
DEBUG=True
SECRET_KEY=your-generated-secret-key-here
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:8000
```

**Replace:**
- `your-anon-key-from-dashboard` → Your actual anon key from Step 1.2
- `your-service-role-key-from-dashboard` → Your actual service_role key from Step 1.2
- `your-generated-secret-key-here` → Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## 🎨 Step 3: Configure Frontend (config.js)

### Option A: Edit config.js directly (for development)

Open `pharmasight/frontend/js/config.js` and update:

```javascript
const CONFIG = {
    API_BASE_URL: 'http://localhost:8000',
    // Supabase Configuration
    SUPABASE_URL: 'https://kwvkkbofubsjiwqlqakt.supabase.co',  // Your Project URL
    SUPABASE_ANON_KEY: 'your-anon-key-here',  // Your anon/public key
    // ... rest of config
};
```

### Option B: Use Settings Page (recommended for production)

The frontend can load these from localStorage. You can add them via the Settings page or set them in browser console:

```javascript
// In browser console (after page loads):
CONFIG.SUPABASE_URL = 'https://kwvkkbofubsjiwqlqakt.supabase.co';
CONFIG.SUPABASE_ANON_KEY = 'your-anon-key-here';
localStorage.setItem('pharmasight_supabase_config', JSON.stringify({
    SUPABASE_URL: CONFIG.SUPABASE_URL,
    SUPABASE_ANON_KEY: CONFIG.SUPABASE_ANON_KEY
}));
location.reload();
```

---

## ✅ Step 4: Verify Configuration

### Test Backend

1. Start the backend server:
   ```bash
   cd pharmasight/backend
   python -m venv venv
   venv\Scripts\activate  # Windows
   # or: source venv/bin/activate  # Mac/Linux
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

2. Check if it starts without errors
3. Visit http://localhost:8000/docs
4. Try the `/api/invite/admin` endpoint (should work if SUPABASE_SERVICE_ROLE_KEY is set)

### Test Frontend

1. Open `pharmasight/frontend/index.html` in a browser
2. Open browser console (F12)
3. Check for errors related to Supabase
4. Try logging in (if you've invited a user)

---

## 🔒 Security Notes

⚠️ **IMPORTANT:**
- **NEVER** commit `.env` file to git
- **NEVER** expose `SUPABASE_SERVICE_ROLE_KEY` to frontend
- **NEVER** share your service_role key publicly
- The `.env` file is already in `.gitignore` - keep it that way!

✅ **Safe to share:**
- `SUPABASE_URL` (public)
- `SUPABASE_ANON_KEY` (public, used in frontend)

---

## 📝 Quick Reference

| Variable | Where to Find | Used In |
|----------|---------------|---------|
| `SUPABASE_URL` | Settings → API → Project URL | Backend & Frontend |
| `SUPABASE_ANON_KEY` | Settings → API → anon key | Frontend |
| `SUPABASE_SERVICE_ROLE_KEY` | Settings → API → service_role key | Backend only |
| `SUPABASE_DB_PASSWORD` | Settings → Database | Backend |

---

## 🆘 Troubleshooting

**"Supabase client not initialized" error:**
- Check that `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set in frontend config.js

**"SUPABASE_SERVICE_ROLE_KEY not configured" error:**
- Check that `.env` file exists in `backend/` folder
- Verify the key is copied correctly (no extra spaces)
- Restart the backend server after editing `.env`

**"Invalid API key" error:**
- Make sure you copied the full key (they're long!)
- Check for extra spaces or line breaks
- Verify you're using the correct key (anon vs service_role)
