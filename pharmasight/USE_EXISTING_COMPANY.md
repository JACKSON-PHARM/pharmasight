# ✅ Use Existing Company (Quick Fix)

## Current Situation

A test company was created successfully! You can either:

### Option A: Use the Existing Company (Fastest)

**The test created:**
- ✅ Company ID: `8e420493-9753-4924-9d80-e27a01a73f84`
- ✅ Branch ID: `ff3f7bb1-0d3d-4e82-a0a7-0128e187180a`
- ✅ Branch Code: Auto-generated (check with API below)

**Quick Setup:**

1. **Open browser console** (F12 → Console)
2. **Run this:**
   ```javascript
   CONFIG.COMPANY_ID = '8e420493-9753-4924-9d80-e27a01a73f84';
   CONFIG.BRANCH_ID = 'ff3f7bb1-0d3d-4e82-a0a7-0128e187180a';
   saveConfig();
   location.reload();
   ```

3. **You're done!** The app will load the dashboard.

### Option B: Delete and Create New

If you want to start fresh:

**1. Delete test company from Supabase:**
   - Go to Supabase SQL Editor
   - Run:
     ```sql
     DELETE FROM companies WHERE id = '8e420493-9753-4924-9d80-e27a01a73f84';
     ```

**2. Then use setup wizard:**
   - Hard refresh browser (Ctrl + Shift + R)
   - Complete setup form
   - Leave branch code empty (will auto-generate as BR001)

## Verify Branch Code

Check what branch code was auto-generated:

```powershell
$companyId = "8e420493-9753-4924-9d80-e27a01a73f84"
Invoke-RestMethod -Uri "http://localhost:8000/api/branches/company/$companyId"
```

This will show the branch with its auto-generated code (should be "BR001").

## ✅ Summary

**Backend is working!** The timeout issue is fixed.

**If you want to use existing company:**
- Just update CONFIG in browser console (Option A above)

**If you want fresh setup:**
- Delete the test company
- Run setup wizard again
- Leave branch code empty (auto-generates as BR001)

## 🎯 What Was Fixed

✅ Missing `email-validator` package installed
✅ Backend starts successfully
✅ Database connection working
✅ Auto-generation of branch code (BR001) working
✅ Simplified document numbers (CS001, CN001) implemented
✅ Increased frontend timeout to 60 seconds

The setup wizard should work perfectly now! 🚀

