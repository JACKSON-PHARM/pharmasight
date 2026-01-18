# 🧪 Quick Backend Test

## Test if Backend is Working

Run these commands in PowerShell:

### Test 1: Health Check (Should work)
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing
```
**Expected:** Status 200, `{"status":"healthy"}`

### Test 2: Startup Status (Might timeout if database issue)
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/api/startup/status" -UseBasicParsing
```
**Expected:** `{"initialized": false, "company_id": null}`

### Test 3: Direct Startup (The actual setup)
```powershell
# Generate UUID
$uuid = [guid]::NewGuid().ToString()
Write-Host "Using UUID: $uuid"

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
        id = $uuid
        email = "admin@pharmasight.com"
        full_name = "Admin User"
        phone = "0700000000"
    }
    branch = @{
        name = "PharmaSight Main Branch"
        code = $null  # Will auto-generate as BR001
        address = "5M35+849"
        phone = "0708476318"
    }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/api/startup" -Method POST -ContentType "application/json" -Body $body
```

**If this works**, you'll get back:
```json
{
  "company_id": "...",
  "user_id": "...",
  "branch_id": "...",
  "message": "Company initialization completed successfully"
}
```

**If it fails**, check:
1. Database connection (check `.env` file)
2. Database function updated (run SQL from IMPORTANT_UPDATE_DATABASE.md)
3. Backend window for error messages

## Database Connection Check

```powershell
cd C:\PharmaSight\pharmasight
python check_database.py
```

This will tell you if the database is accessible.

## Common Issues

### Issue: Database Connection Timeout
**Fix:** Check `.env` file has correct `DATABASE_URL` from Supabase

### Issue: "Function get_next_document_number does not exist"
**Fix:** Run the SQL from `IMPORTANT_UPDATE_DATABASE.md` in Supabase

### Issue: "relation 'companies' does not exist"
**Fix:** Run `database/schema.sql` in Supabase SQL Editor

