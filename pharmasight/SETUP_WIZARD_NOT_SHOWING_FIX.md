# 🔧 Fix: Setup Wizard Not Showing

## Quick Fix Steps

### Step 1: Clear Browser Cache
1. Open browser (Chrome/Edge)
2. Press `Ctrl + Shift + Delete` (Windows) or `Cmd + Shift + Delete` (Mac)
3. Select "Cached images and files"
4. Clear data

### Step 2: Clear LocalStorage
1. Open browser console (Press `F12`)
2. Go to Console tab
3. Type and press Enter:
   ```javascript
   localStorage.clear();
   location.reload();
   ```

### Step 3: Hard Refresh
- **Windows**: Press `Ctrl + Shift + R` or `Ctrl + F5`
- **Mac**: Press `Cmd + Shift + R`

### Step 4: Verify Backend is Running
- Check backend is running: `http://localhost:8000/health`
- If not running, start it: `start.bat` or `python start.py`

### Step 5: Navigate Directly to Setup
Type in browser address bar:
```
http://localhost:3000/#setup
```

## Debugging in Console

Open browser console (F12) and check:

1. **Is setup function loaded?**
   ```javascript
   console.log(typeof window.loadSetup); // Should say "function"
   ```

2. **Check CONFIG:**
   ```javascript
   console.log(CONFIG); // Should show COMPANY_ID: null, BRANCH_ID: null
   ```

3. **Force load setup:**
   ```javascript
   CONFIG.COMPANY_ID = null;
   CONFIG.BRANCH_ID = null;
   localStorage.clear();
   loadPage('setup');
   if (window.loadSetup) {
       window.loadSetup();
   }
   ```

4. **Check if setup element exists:**
   ```javascript
   const setup = document.getElementById('setup');
   console.log('Setup element:', setup);
   if (setup) {
       setup.classList.add('active');
       if (window.renderSetupStep) {
           window.renderSetupStep();
       }
   }
   ```

## Manual API Setup (If Wizard Still Doesn't Show)

If the wizard won't appear, you can set up via API directly:

### 1. Generate a UUID for Admin User

**Option A: PowerShell**
```powershell
[guid]::NewGuid().ToString()
```

**Option B: Online**
- Go to: https://www.uuidgenerator.net/
- Copy the UUID

**Option C: Browser Console**
```javascript
crypto.randomUUID() // If browser supports it
```

### 2. Call Startup API

**Using PowerShell:**
```powershell
$uuid = "YOUR-UUID-HERE" # Replace with generated UUID

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
        fiscal_start_date = "2026-10-01"
    }
    admin_user = @{
        id = $uuid
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

$response = Invoke-RestMethod -Uri "http://localhost:8000/api/startup" -Method POST -ContentType "application/json" -Body $body
Write-Host "Setup complete!"
Write-Host "Company ID: $($response.company_id)"
Write-Host "Branch ID: $($response.branch_id)"
```

**Save the IDs you get back!**

### 3. Update Frontend Config

After API setup, update localStorage in browser console:

```javascript
CONFIG.COMPANY_ID = "PASTE-COMPANY-ID-HERE";
CONFIG.BRANCH_ID = "PASTE-BRANCH-ID-HERE";
CONFIG.USER_ID = "PASTE-USER-ID-HERE";
saveConfig();
location.reload();
```

## Still Not Working?

Check these:

1. **Backend Error?** Check backend PowerShell window for errors
2. **Network Error?** Open DevTools → Network tab, refresh, check for failed requests
3. **JavaScript Error?** Open DevTools → Console tab, look for red errors
4. **Page Element Missing?** Open DevTools → Elements tab, search for `id="setup"`

## Expected Result

After successful setup:
- Setup wizard should show 3 steps: Company → Admin User → Branch
- After completing all steps, you should see "Setup Complete!" message
- Then you can go to Dashboard and start using the app

