# 🔍 Debug Users & Roles Tab - Step by Step Guide

## Problem
Users & Roles tab is blank after authentication.

## End-to-End Testing

### Step 1: Test Backend API

Run the backend test:

```powershell
python pharmasight\test_users_backend.py
```

**Expected Output:**
- ✅ Backend is running
- ✅ GET /api/users/roles returns list of roles
- ✅ GET /api/users returns users list

**If backend fails:**
- Check if backend is running: `http://localhost:8000/health`
- Check backend terminal for errors
- Verify database connection

### Step 2: Test Frontend in Browser

1. **Open your app**: `http://localhost:3000`
2. **Login** with your credentials
3. **Navigate to**: Settings → Users & Roles
4. **Open Browser Console** (F12)
5. **Copy and paste this entire script** into the console:

```javascript
// Load the test script
const script = document.createElement('script');
script.src = '/js/test_users_end_to_end.js';  // Adjust path if needed
// OR paste the content of test_users_end_to_end.js directly
```

**OR manually run the test function** (paste this in console):

```javascript
// Quick manual test
(async function() {
    console.log('Testing API.users.listRoles()...');
    try {
        const roles = await API.users.listRoles();
        console.log('✅ Roles:', roles);
    } catch (e) {
        console.error('❌ Roles API failed:', e);
    }
    
    console.log('Testing API.users.list()...');
    try {
        const users = await API.users.list();
        console.log('✅ Users:', users);
    } catch (e) {
        console.error('❌ Users API failed:', e);
    }
    
    console.log('Testing renderUsersPage()...');
    try {
        await window.renderUsersPage();
        const page = document.getElementById('settings');
        console.log('✅ renderUsersPage completed. Content length:', page?.innerHTML?.length || 0);
    } catch (e) {
        console.error('❌ renderUsersPage failed:', e);
    }
})();
```

### Step 3: Check Console Logs

Look for these specific logs when navigating to Users & Roles:

**Expected Logs:**
```
[ROUTER] Loading settings page, subPage: users
[ROUTER] Calling window.loadSettings with subPage: users
loadSettings() called with subPage: users
[SETTINGS] loadSettingsSubPage() called with: users
[SETTINGS] Case: users - calling renderUsersPage()
[USERS] renderUsersPage() called - START
[USERS] Setting loading state...
[USERS] Loading state set, starting API calls...
[USERS] About to render page content. users: X errorMessage: null
[USERS] Setting page innerHTML...
[USERS] Page innerHTML set successfully!
```

**If you don't see these logs:**
- The routing is not working
- Function is not being called
- Check for JavaScript errors (red text)

### Step 4: Check Network Tab

1. Open **DevTools → Network** tab
2. Navigate to Settings → Users & Roles
3. Filter by **Fetch/XHR**
4. Look for these requests:

**Expected Requests:**
- `GET /api/users/roles` → Should be **200 OK**
- `GET /api/users` → Should be **200 OK**

**If requests fail:**
- **404 Not Found** → Backend endpoint not registered
- **500 Internal Server Error** → Backend/database error
- **Network Error** → Backend not running or CORS issue

### Step 5: Verify Database Migration

The users table needs these columns:
- `invitation_token`
- `invitation_code`
- `is_pending`
- `password_set`
- `deleted_at`

**Check in Supabase SQL Editor:**

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;
```

**If columns are missing, run migration:**

```sql
-- Copy and run: pharmasight/database/add_user_invitation_fields.sql
```

### Step 6: Manual Function Call

If automatic rendering fails, try calling manually:

**In Browser Console:**

```javascript
// Check if function exists
typeof window.renderUsersPage

// Call manually
window.renderUsersPage()

// Check page content after call
document.getElementById('settings').innerHTML.substring(0, 200)
```

### Step 7: Check Current State

**In Browser Console:**

```javascript
// Check current settings subpage
currentSettingsSubPage

// Check API configuration
CONFIG.API_BASE_URL
CONFIG.COMPANY_ID
CONFIG.BRANCH_ID

// Check if API is available
typeof API.users.list

// Test API call
API.users.list().then(r => console.log('Users:', r)).catch(e => console.error('Error:', e))
```

## Common Issues & Solutions

### Issue 1: No `[USERS]` logs in console

**Cause:** `renderUsersPage()` is not being called

**Solution:**
- Check if `loadSettingsSubPage('users')` is being called
- Check routing in `app.js` - should call `window.loadSettings('users')`
- Verify `case 'users':` in `loadSettingsSubPage()` switch statement

### Issue 2: API calls fail (404 or Network Error)

**Cause:** Backend not running or endpoint not registered

**Solution:**
1. Check backend: `http://localhost:8000/health`
2. Check backend logs for errors
3. Verify `backend/app/main.py` includes:
   ```python
   from app.api.users import router as users_router
   app.include_router(users_router, prefix="/api", tags=["User Management"])
   ```

### Issue 3: API returns 500 (Database Error)

**Cause:** Database migration not run or schema mismatch

**Solution:**
1. Run migration: `database/add_user_invitation_fields.sql`
2. Check if `user_roles` table has data:
   ```sql
   SELECT * FROM user_roles;
   ```

### Issue 4: Page renders but shows "Error loading users"

**Cause:** API is accessible but returns error

**Solution:**
1. Check backend terminal for error details
2. Check Network tab for API response
3. Verify database connection is working

### Issue 5: Blank page even after successful API calls

**Cause:** JavaScript error in rendering or innerHTML not updating

**Solution:**
1. Check console for JavaScript errors (red text)
2. Try manual call: `window.renderUsersPage()`
3. Check if page element exists: `document.getElementById('settings')`

## Quick Diagnostic Commands

**Run in Browser Console (F12):**

```javascript
// 1. Test if everything exists
console.log('API:', typeof API?.users?.list);
console.log('renderUsersPage:', typeof window.renderUsersPage);
console.log('Settings page:', document.getElementById('settings'));

// 2. Test API calls
Promise.all([
    API.users.listRoles().then(r => ({roles: r.length})).catch(e => ({roles: 'ERROR', e})),
    API.users.list().then(r => ({users: r.users?.length || 0})).catch(e => ({users: 'ERROR', e}))
]).then(results => console.table(results));

// 3. Test rendering
window.renderUsersPage().then(() => {
    const page = document.getElementById('settings');
    console.log('Content length:', page?.innerHTML?.length || 0);
    console.log('Has "Users & Roles" text:', page?.innerHTML?.includes('Users & Roles'));
});

// 4. Check current route
console.log('Hash:', window.location.hash);
console.log('Current subpage:', currentSettingsSubPage);
```

## Expected Database Structure

### users table
- `id` (UUID, primary key, matches Supabase Auth user_id)
- `email` (unique)
- `full_name`
- `phone`
- `is_active`
- `invitation_token` (nullable, NEW)
- `invitation_code` (nullable, NEW)
- `is_pending` (boolean, NEW)
- `password_set` (boolean, NEW)
- `deleted_at` (nullable, NEW)
- `created_at`, `updated_at`

### user_roles table
- `id` (UUID)
- `role_name` (unique: 'admin', 'pharmacist', 'cashier', etc.)
- `description`
- `created_at`

### user_branch_roles table
- `id` (UUID)
- `user_id` → `users.id`
- `branch_id` → `branches.id`
- `role_id` → `user_roles.id`
- `created_at`

**Note:** A user can have different roles in different branches (many-to-many relationship).

## Report Results

After running tests, report:

1. ✅ Backend test results (`test_users_backend.py`)
2. ✅ Browser console logs when navigating to Users & Roles
3. ✅ Network tab requests (status codes)
4. ✅ Any JavaScript errors (red text in console)
5. ✅ Database migration status (columns exist?)

This will help identify exactly where the flow is breaking.
