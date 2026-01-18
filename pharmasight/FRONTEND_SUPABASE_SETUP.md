# Frontend Supabase Configuration

## Quick Setup

The frontend needs Supabase URL and anon key to work. Here are two ways to set them:

### Option 1: Edit config.js (Recommended for Development)

1. Open `pharmasight/frontend/js/config.js`
2. Find the `SUPABASE_URL` and `SUPABASE_ANON_KEY` lines
3. Update with your values:

```javascript
SUPABASE_URL: 'https://kwvkkbofubsjiwqlqakt.supabase.co',
SUPABASE_ANON_KEY: 'your-actual-anon-key-here',
```

4. Save the file
5. Refresh the browser (hard refresh: Ctrl+Shift+R or Cmd+Shift+R)

### Option 2: Set via Browser Console (Quick Test)

1. Open your app in browser (http://localhost:3000)
2. Press F12 to open Developer Tools
3. Go to Console tab
4. Paste and run this (replace with your actual anon key):

```javascript
CONFIG.SUPABASE_URL = 'https://kwvkkbofubsjiwqlqakt.supabase.co';
CONFIG.SUPABASE_ANON_KEY = 'your-actual-anon-key-here';
saveSupabaseConfig();
location.reload();
```

## Where to Get Your Anon Key

1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/settings/api
2. Find the **"Project API keys"** section
3. Look for the key labeled **"anon"** or **"public"**
4. Click the eye icon to reveal it
5. Copy the entire key (it's long!)

## Verify It's Working

After setting the values:
1. Refresh the page
2. The "Supabase client not initialized" message should disappear
3. You should be able to see the login form working

## Security Note

✅ **Safe to share:** The anon key is public and safe to use in frontend code
❌ **Never share:** The service_role key (backend only!)
