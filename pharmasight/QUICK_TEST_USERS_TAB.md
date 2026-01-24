# 🧪 Quick Test - Users & Roles Tab

## Copy-Paste Test for Browser Console

**When you're on Settings → Users & Roles tab**, open browser console (F12) and paste this:

```javascript
(async function() {
    console.log('=== TESTING USERS TAB ===');
    
    // Test 1: API calls
    try {
        const roles = await API.users.listRoles();
        console.log('✅ Roles:', roles.length, 'found');
    } catch (e) {
        console.error('❌ Roles API failed:', e);
    }
    
    try {
        const users = await API.users.list();
        console.log('✅ Users:', users.users?.length || 0, 'found');
    } catch (e) {
        console.error('❌ Users API failed:', e);
    }
    
    // Test 2: Render function
    try {
        await window.renderUsersPage();
        const page = document.getElementById('settings');
        console.log('✅ renderUsersPage called');
        console.log('Content length:', page?.innerHTML?.length || 0);
    } catch (e) {
        console.error('❌ renderUsersPage failed:', e);
    }
})();
```

## Or Use Full Test Script

Copy entire contents of `test_in_browser_console.js` and paste in console.

## Expected Output

If everything works, you should see:
- ✅ Roles API: X found
- ✅ Users API: X found  
- ✅ renderUsersPage called
- Content length: > 1000

If you see errors, they will show what's broken!
