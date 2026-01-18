# 🚀 Setup Company and Branch - Step by Step Guide

## Overview
With the new ONE COMPANY architecture, we need to use the `/api/startup` endpoint which creates everything in one go:
- Company
- Admin User
- First Branch
- Document Sequences
- Pricing Defaults

## Step 1: Update Database Schema

**IMPORTANT:** Before proceeding, ensure your database has the updated schema.

1. Go to your Supabase dashboard
2. Navigate to SQL Editor
3. Run the schema: `database/schema.sql`
4. This will:
   - Create `users` table
   - Add trigger to enforce ONE COMPANY rule
   - Make branch `code` required
   - Update document numbering functions

## Step 2: Prepare Your Data

You'll need:
- **Company Information**: Name, registration, PIN, contact details
- **Admin User Information**: 
  - User ID (from Supabase Auth - if using authentication)
  - Email, full name, phone
- **Branch Information**: Name, **CODE (REQUIRED)**, address, phone

## Step 3: Use the Startup Endpoint

### Option A: Using Frontend Setup Wizard (Recommended)

1. Start your backend server:
   ```powershell
   cd C:\PharmaSight\pharmasight
   .\start.bat
   ```

2. Open frontend in browser: `http://localhost:3000`
3. The setup wizard will appear automatically
4. Fill in all three sections:
   - Company Details
   - Admin User Details (user ID from Supabase Auth)
   - Branch Details (**Branch Code is REQUIRED**)

5. Click "Complete Setup" - it will call `/api/startup`

### Option B: Using API Directly (Testing)

Use Postman, curl, or PowerShell:

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
        fiscal_start_date = "2026-10-01"
    }
    admin_user = @{
        id = "YOUR-SUPABASE-USER-ID"
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

### Option C: Using Python Script

```python
import requests
import json

url = "http://localhost:8000/api/startup"

data = {
    "company": {
        "name": "PharmaSight Meds Ltd",
        "registration_number": "PVT-JZUA3728",
        "pin": "P05248438Q",
        "phone": "0708476318",
        "email": "pharmasightsolutions@gmail.com",
        "address": "5M35+849",
        "currency": "KES",
        "timezone": "Africa/Nairobi",
        "fiscal_start_date": "2026-10-01"
    },
    "admin_user": {
        "id": "YOUR-SUPABASE-USER-ID",  # Replace with actual user ID
        "email": "admin@pharmasight.com",
        "full_name": "Admin User",
        "phone": "0700000000"
    },
    "branch": {
        "name": "PharmaSight Main Branch",
        "code": "MAIN",  # REQUIRED - Used in invoice numbering
        "address": "5M35+849",
        "phone": "0708476318"
    }
}

response = requests.post(url, json=data)
print(response.json())
```

## Step 4: Verify Setup

Check that everything was created:

```powershell
# Check startup status
Invoke-RestMethod -Uri "http://localhost:8000/api/startup/status"

# Get company
Invoke-RestMethod -Uri "http://localhost:8000/api/companies"

# Get branches
$companyId = (Invoke-RestMethod -Uri "http://localhost:8000/api/companies").id
Invoke-RestMethod -Uri "http://localhost:8000/api/branches/company/$companyId"
```

## Important Notes

### Branch Code Format
- **REQUIRED**: Cannot create branch without code
- Used in invoice numbering: `{BRANCH_CODE}-INV-YYYY-000001`
- Examples: "MAIN", "BR1", "NBI", "MOMBASA"
- Keep it short (max 50 chars), uppercase recommended

### User ID
- If using Supabase Auth, get the user ID from Supabase dashboard
- If not using auth yet, you can use a temporary UUID
- The user ID in `users` table must match Supabase Auth user_id

### Single Company Rule
- This database supports **ONLY ONE COMPANY**
- If company already exists, startup will fail
- To reset: Delete the company record manually from database

## Troubleshooting

### Error: "Company already exists"
- Check: `GET /api/startup/status`
- If initialized, you can't create another company
- Update existing company instead

### Error: "Branch code is required"
- Make sure branch.code is provided and not empty
- Check that branch code field is filled in the form

### Error: "Admin role not found"
- Ensure `user_roles` table has been seeded
- Run the seed data from `schema.sql` (already included in the schema file)

### Error: "Database connection failed"
- Check your `.env` file has correct `DATABASE_URL`
- Ensure Supabase is accessible
- Check backend logs for database errors

## Next Steps After Setup

1. ✅ Company created
2. ✅ Admin user created
3. ✅ First branch created
4. ✅ Document sequences initialized
5. ✅ Pricing defaults set

**Now you can:**
- Start adding items
- Create suppliers
- Begin inventory management
- Process sales and purchases

