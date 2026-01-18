# 🔧 Force Setup Wizard to Show

If the setup wizard is not appearing, follow these steps:

## Quick Fix

1. **Clear Browser Cache and LocalStorage:**
   ```javascript
   // Open browser console (F12) and run:
   localStorage.clear();
   location.reload();
   ```

2. **Check Backend is Running:**
   - Backend should be on `http://localhost:8000`
   - Check: `http://localhost:8000/health`

3. **Manually Navigate to Setup:**
   - In browser, go to: `http://localhost:3000/#setup`
   - Or click any navigation item then manually type `#setup` in URL

## Debugging Steps

### 1. Check Console for Errors
- Press F12 to open Developer Tools
- Go to Console tab
- Look for any red error messages
- Share any errors you see

### 2. Check if Setup Page Exists
- Press F12 → Elements tab
- Search for `<div id="setup">`
- It should exist in the HTML

### 3. Force Setup Page to Show

Open browser console (F12) and run:

```javascript
// Clear config
CONFIG.COMPANY_ID = null;
CONFIG.BRANCH_ID = null;
localStorage.removeItem('pharmasight_config');

// Force load setup
loadPage('setup');
if (window.loadSetup) {
    window.loadSetup();
}
```

## If Still Not Working

1. **Hard Refresh Browser:**
   - Windows: `Ctrl + Shift + R` or `Ctrl + F5`
   - Mac: `Cmd + Shift + R`

2. **Check Script Loading:**
   - Open Network tab in DevTools
   - Refresh page
   - Check if `setup.js` is loaded (status should be 200)

3. **Verify Setup Function Exists:**
   ```javascript
   // In console, check:
   console.log(typeof window.loadSetup); // Should be "function"
   console.log(typeof window.renderSetupStep); // Should be "function"
   ```

## Manual Setup Alternative

If the wizard won't show, you can manually call the API:

### Using PowerShell:
```powershell
$body = @{
    company = @{
        name = "PharmaSight Meds Ltd"
        registration_number = "PVT-JZUA3728"
        pin = "P05248438Q"
        phone = "0708476318"
        email = "pharmasightsolutions@gmail.com"
        address = "5M35+849"
        currency = "KES"
        timezone = "Africa/Nairobi"
    }
    admin_user = @{
        id = "550e8400-e29b-41d4-a716-446655440000"
        email = "admin@pharmasight.com"
        full_name = "Admin User"
        phone = "0700000000"
    }
    branch = @{
        name = "PharmaSight Main Branch"
        code = "MAIN"
        address = "5M35+849"
        phone = "0708476318"
    }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/api/startup" -Method POST -ContentType "application/json" -Body $body
```

Then update localStorage:
```javascript
// In browser console:
CONFIG.COMPANY_ID = "YOUR_COMPANY_ID";
CONFIG.BRANCH_ID = "YOUR_BRANCH_ID";
saveConfig();
location.reload();
```

