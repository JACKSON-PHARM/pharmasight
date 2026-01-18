# ⚡ Quick Start: Setup Company and Branch

## 🎯 What You Need to Do RIGHT NOW

### Step 1: Ensure Database Schema is Updated

**IMPORTANT:** Your database must have the new schema with:
- `users` table
- Branch code required
- ONE COMPANY enforcement

**If you haven't updated yet:**
1. Go to Supabase SQL Editor
2. Run `database/schema.sql`
3. Verify it completed successfully

### Step 2: Start Your Servers

```powershell
cd C:\PharmaSight\pharmasight
.\start.bat
```

Wait for both backend and frontend to start:
- Backend: `http://localhost:8000`
- Frontend: `http://localhost:3000`

### Step 3: Use the Setup Wizard

1. **Open browser**: `http://localhost:3000`
2. **Setup wizard will appear automatically** (if no company exists)
3. **Fill in the 3 steps:**

   **Step 1: Company Information**
   - Company Name: `PharmaSight Meds Ltd`
   - Registration Number: `PVT-JZUA3728`
   - PIN: `P05248438Q`
   - Phone: `0708476318`
   - Email: `pharmasightsolutions@gmail.com`
   - Address: `5M35+849`
   - Currency: `KES`
   - Fiscal Year Start: `2026-10-01`

   **Step 2: Admin User**
   - User ID: `Generate a UUID or use your Supabase Auth user_id`
     - Quick UUID generator: https://www.uuidgenerator.net/
     - Example: `550e8400-e29b-41d4-a716-446655440000`
   - Email: `admin@pharmasight.com`
   - Full Name: `Admin User`
   - Phone: `0700000000`

   **Step 3: Branch Setup**
   - Branch Name: `PharmaSight Main Branch`
   - **Branch Code: `MAIN`** ⚠️ **REQUIRED**
   - Address: `5M35+849`
   - Phone: `0708476318`

4. **Click "Complete Setup"** - This will:
   - ✅ Create company
   - ✅ Create admin user
   - ✅ Create branch
   - ✅ Initialize document sequences
   - ✅ Initialize pricing defaults
   - ✅ Assign admin role to branch

### Step 4: Verify Setup

After setup completes, you should see:
- ✅ Success message
- ✅ Company, Admin User, and Branch listed
- ✅ "Go to Dashboard" button

**Click "Go to Dashboard"** and you're ready to start!

## 🔧 If Something Goes Wrong

### Error: "Company already exists"
- Your database already has a company
- Check: `GET http://localhost:8000/api/startup/status`
- If initialized, you can skip setup and go directly to dashboard

### Error: "Branch code is required"
- Make sure you filled in the Branch Code field
- It cannot be empty
- Use something like "MAIN", "BR1", "HQ", etc.

### Error: "Backend server not running"
- Check backend is running on port 8000
- Check backend window for errors
- Verify `.env` file has correct `DATABASE_URL`

### Error: "Database connection failed"
- Check Supabase is accessible
- Verify `DATABASE_URL` in `.env` file
- Check backend logs for database errors

## ✅ After Successful Setup

You now have:
- ✅ Company created
- ✅ Admin user created  
- ✅ First branch created with code "MAIN"
- ✅ Document sequences initialized (invoices will be: `MAIN-INV-2026-000001`)
- ✅ Pricing defaults set (30% markup)
- ✅ Admin role assigned to branch

**You can now:**
- Add inventory items
- Create suppliers
- Process purchases (GRN)
- Process sales (POS)
- View inventory reports

## 📝 Next Steps

1. **Add Items**: Go to Items page and start adding products
2. **Create Suppliers**: Set up your supplier list
3. **Load Inventory**: Create GRN for initial stock
4. **Start Selling**: Use the Sales/POS page

## 💡 Tips

- **Branch Code**: Keep it short (3-5 characters), uppercase recommended
- **User ID**: If using Supabase Auth later, update the user_id to match
- **Invoice Numbers**: Will automatically include branch code (e.g., `MAIN-INV-2026-000001`)
- **One Company**: Remember, this database supports only ONE company

## 🆘 Need Help?

Check these files:
- `SETUP_COMPANY_BRANCH.md` - Detailed setup guide
- `ARCHITECTURE_ONE_COMPANY.md` - Architecture documentation
- Backend logs - Check the backend PowerShell window
- Browser console - Press F12 to see frontend errors

