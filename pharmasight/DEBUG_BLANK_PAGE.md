# Debug Blank Users & Roles Page

## Issue
Users & Roles tab is blank despite backend running.

## Current Status
✅ Backend is running  
✅ Code is updated with routing fixes  
✅ Functions are defined  
❌ Page is still blank  

## Debugging Steps

### 1. Clear Browser Cache
The browser might be using cached JavaScript files.

**Chrome/Edge:**
- Press `Ctrl + Shift + Delete`
- Select "Cached images and files"
- Select "All time"
- Click "Clear data"
- **OR** Hard refresh: `Ctrl + F5` or `Ctrl + Shift + R`

**Firefox:**
- Press `Ctrl + Shift + Delete`
- Select "Cache"
- Click "Clear Now"
- **OR** Hard refresh: `Ctrl + F5`

### 2. Check Console Logs

After refreshing, open Console (F12) and look for:

**Expected logs when navigating to Settings → Users & Roles:**
```
[ROUTER] Loading settings page, subPage: users
[ROUTER] Calling window.loadSettings with subPage: users
loadSettings() called with subPage: users
[SETTINGS] loadSettingsSubPage() called with: users
[SETTINGS] Case: users - calling renderUsersPage()
[USERS] renderUsersPage() called - START
[USERS] Setting loading state...
```

**If you DON'T see these logs:**
- JavaScript file might not be loading
- Check Network tab for 404 errors on `settings.js`
- Check for JavaScript errors (red text in console)

### 3. Verify Functions Are Available

In the browser console (F12), type these commands:

```javascript
// Check if functions exist
typeof window.loadSettings
typeof window.loadSettingsSubPage
typeof window.renderUsersPage
typeof API.users.list

// Manually call the function
window.renderUsersPage()
```

**Expected output:**
- All should return `"function"`
- Manual call should render the page

### 4. Check Network Tab

1. Open DevTools (F12)
2. Go to **Network** tab
3. Navigate to Settings → Users & Roles
4. Look for:
   - `GET /api/users` - should return 200 OK
   - `GET /api/users/roles` - should return 200 OK
   - Any 404 or 500 errors

### 5. Direct Function Test

If logs don't appear, test directly:

**In Browser Console (F12):**
```javascript
// Test 1: Check if settings page element exists
document.getElementById('settings')

// Test 2: Manually call renderUsersPage
if (window.renderUsersPage) {
    window.renderUsersPage();
} else {
    console.error('renderUsersPage not found on window object');
}

// Test 3: Check API availability
if (window.API && window.API.users) {
    console.log('API.users exists');
    window.API.users.list().then(r => console.log('API test:', r));
} else {
    console.error('API.users not found');
}
```

### 6. Verify File Updates

Check if `settings.js` has the latest changes:

1. In DevTools → **Sources** tab
2. Find `frontend/js/pages/settings.js`
3. Check line ~522 - should have: `console.log('[USERS] renderUsersPage() called - START');`
4. If you see old code, the file isn't refreshing

**Force reload:**
- Close all tabs with the app
- Open new tab
- Navigate to `localhost:3000`

### 7. Check for JavaScript Errors

Look in Console for:
- **Red error messages** - these stop execution
- **Uncaught exceptions** - check the line number
- **Syntax errors** - might prevent file from loading

### 8. Verify Backend API

Test backend directly:

```powershell
# In PowerShell
Invoke-WebRequest -Uri "http://localhost:8000/api/users/roles" | Select-Object StatusCode, Content
```

Should return `StatusCode: 200` with JSON content.

## Quick Fix Attempt

If everything seems correct but page is still blank:

1. **Clear cache** (Ctrl + Shift + Delete)
2. **Hard refresh** (Ctrl + F5)
3. **Close and reopen browser tab**
4. **Check console for ANY errors** (even warnings)
5. **Try manually calling**: `window.renderUsersPage()` in console

## Report Back

After trying these steps, report:

1. ✅ Do you see `[USERS]` logs in console?
2. ✅ Does `window.renderUsersPage()` work when called manually?
3. ✅ Any red errors in console?
4. ✅ Do API calls in Network tab return 200 OK?
