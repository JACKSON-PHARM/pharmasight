# Simplified Client Onboarding Flow - Step by Step

## Overview
This document explains the **simple, automated onboarding process** where we only ask for **email + company name**, then everything else is automated.

---

## 🎯 THE SIMPLE FLOW

```
Client Signs Up (Email + Company Name)
    ↓
[Automated Magic Happens - 3-5 minutes]
    ↓
Client Receives Invite Link via Email
    ↓
Client Clicks Link → Sets Up Their Account
    ↓
Client Starts Using PharmaSight
```

---

## 📝 STEP 1: CLIENT SIGNS UP (What We Ask)

### What the Client Sees:
A simple signup form on `pharmasight.com/signup` with just **2 fields**:

```
┌─────────────────────────────────────┐
│   Get Started with PharmaSight      │
│                                     │
│   Company Name: [____________]      │
│   Email Address: [____________]     │
│                                     │
│   [ Start Free Trial ]              │
└─────────────────────────────────────┘
```

### What We Collect:
1. **Company Name** (e.g., "Acme Pharmacy")
2. **Email Address** (e.g., "john@acmepharmacy.com")

**That's it!** No subdomain selection, no payment info, no complex forms.

---

## ⚙️ STEP 2: AUTOMATED SETUP (What Happens Behind the Scenes)

**Time: 3-5 minutes (completely automated)**

When the client clicks "Start Free Trial", our system automatically:

### 2.1 Generate Unique Subdomain
- **System generates:** `acmepharmacy.pharmasight.com` (from company name)
- **If taken:** `acmepharmacy1.pharmasight.com`, `acmepharmacy2.pharmasight.com`, etc.
- **Stored in:** Master database (`tenants` table)

### 2.2 Create Supabase Database
- **System calls:** Supabase Management API
- **Creates:** New Supabase project named `pharmasight-acmepharmacy-{uuid}`
- **Result:** Fresh, empty PostgreSQL database ready to use
- **Stored:** Database connection URL (encrypted) in master database

### 2.3 Run Database Migrations
- **System runs:** All your existing database migrations
- **Creates:** All tables (items, sales_invoices, branches, users, etc.)
- **Result:** Database schema matches your current production database

### 2.4 Create Default Admin User
- **System creates:** First admin user in the new database
- **Email:** The email they provided (john@acmepharmacy.com)
- **Password:** Temporary secure password (generated randomly)
- **Role:** Super Admin (full access)
- **Status:** Active, ready to log in

### 2.5 Set Up Trial Period
- **System creates:** Trial subscription (14 days free)
- **Status:** `trial` (active, no payment required)
- **Modules:** Starter plan modules enabled (inventory, sales, purchases)

### 2.6 Generate Invite Link
- **System generates:** Secure, one-time-use invite link
- **Format:** `https://acmepharmacy.pharmasight.com/setup?token=abc123xyz`
- **Expires:** 7 days (if not used, we can resend)
- **Contains:** Encrypted token with tenant_id and user_id

### 2.7 Send Welcome Email
- **System sends:** Email to john@acmepharmacy.com
- **Subject:** "Welcome to PharmaSight - Complete Your Setup"
- **Contains:** 
  - Invite link (click to start setup)
  - Temporary password (for first login)
  - Their unique URL: `acmepharmacy.pharmasight.com`

---

## 📧 STEP 3: CLIENT RECEIVES EMAIL

### Email Content:
```
Subject: Welcome to PharmaSight - Complete Your Setup

Hi John,

Welcome to PharmaSight! Your pharmacy management system is ready.

Your Pharmacy URL: https://acmepharmacy.pharmasight.com

👉 Click here to complete setup: [Complete Setup Button]

Or copy this link: https://acmepharmacy.pharmasight.com/setup?token=abc123xyz

Your temporary password: TempPass123! (you'll change this during setup)

This link expires in 7 days.

Need help? Reply to this email.

Best regards,
PharmaSight Team
```

---

## 🖱️ STEP 4: CLIENT CLICKS INVITE LINK

### What Happens:
1. **Client clicks** the invite link
2. **System validates** the token (checks if valid, not expired)
3. **System redirects** to setup wizard at `acmepharmacy.pharmasight.com/setup`

### What Client Sees:
A **guided setup wizard** with 4 simple steps:

---

## 🎨 STEP 5: SETUP WIZARD (What Client Does)

### Step 5.1: Create Your Password
```
┌─────────────────────────────────────┐
│   Step 1 of 4: Create Password     │
│                                     │
│   New Password: [____________]     │
│   Confirm Password: [____________] │
│                                     │
│   [ Continue ]                      │
└─────────────────────────────────────┘
```
- Client sets their permanent password
- System updates their account

---

### Step 5.2: Company Information
```
┌─────────────────────────────────────┐
│   Step 2 of 4: Company Details     │
│                                     │
│   Company Name: [Acme Pharmacy]    │
│   Phone: [____________]            │
│   Address: [____________]          │
│   City: [____________]             │
│   Country: [Select...]             │
│                                     │
│   [ Continue ]                      │
└─────────────────────────────────────┘
```
- Client fills in company details
- System saves to `companies` table in their database

---

### Step 5.3: Create Your First Branch
```
┌─────────────────────────────────────┐
│   Step 3 of 4: Add Your Branch     │
│                                     │
│   Branch Name: [Main Branch]       │
│   Location: [____________]         │
│   Phone: [____________]            │
│                                     │
│   💡 You can add more branches     │
│      later from Settings            │
│                                     │
│   [ Continue ]                      │
└─────────────────────────────────────┘
```
- Client creates their first branch
- System saves to `branches` table
- This becomes their default branch

---

### Step 5.4: Invite Team Members (Optional)
```
┌─────────────────────────────────────┐
│   Step 4 of 4: Invite Your Team    │
│                                     │
│   Email: [____________]            │
│   Role: [Select: Cashier/Manager] │
│                                     │
│   [+ Add Another]                   │
│                                     │
│   💡 You can skip this and add      │
│      team members later             │
│                                     │
│   [ Skip ]  [ Finish Setup ]       │
└─────────────────────────────────────┘
```
- Client can invite team members now (optional)
- Or skip and do it later
- System sends invite emails to team members

---

## ✅ STEP 6: SETUP COMPLETE!

### What Client Sees:
```
┌─────────────────────────────────────┐
│   🎉 Setup Complete!                │
│                                     │
│   Your pharmacy is ready to use!    │
│                                     │
│   [ Go to Dashboard ]               │
└─────────────────────────────────────┘
```

### What Happens:
- Client is logged in automatically
- Redirected to dashboard: `acmepharmacy.pharmasight.com/dashboard`
- Trial period starts (14 days)
- All core features are enabled

---

## 🚀 STEP 7: CLIENT STARTS USING PHARMASIGHT

Now the client can:

### 7.1 Load Their Stock
**Option A: Import from Excel**
- Go to **Inventory → Import Items**
- Upload Excel file with items
- System validates and imports
- Items appear in inventory

**Option B: Add Items Manually**
- Go to **Inventory → Add Item**
- Fill in item details (name, price, quantity, etc.)
- Save item
- Repeat for each item

**Option C: Start Fresh**
- Just start adding items as they need them
- No need to import everything at once

---

### 7.2 Add More Users (If Needed)
- Go to **Settings → Users → Invite User**
- Enter email and role
- System sends invite email
- User clicks link, sets password, starts working

---

### 7.3 Add More Branches (If Needed)
- Go to **Settings → Branches → Add Branch**
- Enter branch details
- Assign users to branch
- Start managing inventory per branch

---

### 7.4 Start Selling
- Go to **Sales → New Invoice**
- Select customer (or create new)
- Add items from inventory
- Process payment
- Print receipt
- **Done!** First sale completed

---

## 🔄 WHAT HAPPENS AFTER TRIAL?

### Day 14: Trial Ending Email
```
Subject: Your PharmaSight Trial Ends in 2 Days

Hi John,

Your 14-day trial ends in 2 days.

Choose your plan:
- Starter: $99/month (1 branch, 5 users)
- Professional: $299/month (5 branches, 20 users)
- Enterprise: Custom pricing

[ Choose Plan ] [ Extend Trial ]
```

### Client Chooses Plan:
1. **Clicks "Choose Plan"**
2. **Selects plan** (Starter/Professional/Enterprise)
3. **Enters payment details** (Stripe checkout)
4. **Subscription activated** automatically
5. **Access continues** seamlessly (no interruption)

### If Client Doesn't Pay:
- **Day 15:** Access suspended (read-only mode)
- **Day 20:** Full access blocked
- **Day 30:** Database archived (can be restored if they return)

---

## 📊 SUMMARY: THE ENTIRE FLOW

```
┌─────────────────────────────────────────────────────────┐
│  CLIENT SIDE                    │  SYSTEM SIDE           │
├─────────────────────────────────┼────────────────────────┤
│ 1. Fills form (email + name)    │ → Validates input      │
│                                 │ → Generates subdomain  │
│                                 │ → Creates Supabase DB  │
│                                 │ → Runs migrations      │
│                                 │ → Creates admin user   │
│                                 │ → Sets up trial        │
│                                 │ → Generates invite     │
│                                 │ → Sends email          │
│                                 │                        │
│ 2. Receives email               │ ← Email delivered      │
│                                 │                        │
│ 3. Clicks invite link           │ → Validates token      │
│                                 │ → Shows setup wizard   │
│                                 │                        │
│ 4. Completes setup wizard:      │                        │
│    - Sets password              │ → Updates user         │
│    - Adds company info          │ → Saves to DB          │
│    - Creates branch             │ → Creates branch       │
│    - Invites team (optional)    │ → Sends invites        │
│                                 │                        │
│ 5. Starts using PharmaSight:    │                        │
│    - Loads stock (Excel/manual) │ → Stores in their DB   │
│    - Adds users                 │ → Creates users        │
│    - Creates sales              │ → Processes sales      │
│                                 │                        │
│ 6. Trial ends (Day 14)          │ → Sends reminder       │
│                                 │                        │
│ 7. Chooses plan & pays          │ → Activates subscription│
│                                 │ → Enables modules      │
│                                 │                        │
│ 8. Continues using PharmaSight  │ → Full access          │
└─────────────────────────────────┴────────────────────────┘
```

---

## 🎯 KEY POINTS

### ✅ What Makes This Smooth:
1. **Minimal Input:** Only email + company name required
2. **Fully Automated:** Database, migrations, user creation all automatic
3. **One-Click Setup:** Invite link handles everything
4. **Guided Experience:** Setup wizard walks them through
5. **Flexible:** Can skip steps, do them later
6. **No Payment Upfront:** Trial first, pay later

### 🔒 Security Features:
- Invite links expire (7 days)
- Tokens are one-time-use
- Passwords are hashed
- Each client has isolated database
- SSL certificates for all subdomains

### ⚡ Performance:
- Database created in 1-2 minutes
- Migrations run in 30-60 seconds
- Total setup time: 3-5 minutes
- Client can start using immediately

---

## 🛠️ TECHNICAL DETAILS (For Developers)

### Master Database Tables Needed:
```sql
-- Stores tenant info
tenants (
    id UUID PRIMARY KEY,
    name VARCHAR(255),              -- "Acme Pharmacy"
    subdomain VARCHAR(100) UNIQUE,  -- "acmepharmacy"
    database_url TEXT,               -- Encrypted Supabase connection
    status VARCHAR(20),              -- 'trial', 'active', 'suspended'
    created_at TIMESTAMP
)

-- Stores invite tokens
tenant_invites (
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    user_id UUID,                    -- Admin user in tenant DB
    token VARCHAR(255) UNIQUE,        -- Secure random token
    expires_at TIMESTAMP,
    used_at TIMESTAMP,
    created_at TIMESTAMP
)
```

### API Endpoints Needed:
```
POST /api/onboarding/signup
  - Input: { email, company_name }
  - Output: { success: true, message: "Check your email" }

GET /setup?token=abc123
  - Validates token
  - Shows setup wizard if valid
  - Redirects to login if expired

POST /api/setup/complete
  - Input: { token, password, company_info, branch_info }
  - Output: { success: true, redirect_url: "/dashboard" }
```

### Background Jobs Needed:
```
1. create_tenant_database
   - Creates Supabase project
   - Runs migrations
   - Creates admin user
   - Sends welcome email

2. send_invite_email
   - Generates secure token
   - Creates invite record
   - Sends email with link
```

---

## ❓ COMMON QUESTIONS

### Q: What if the subdomain is taken?
**A:** System automatically tries `companyname1`, `companyname2`, etc.

### Q: What if client doesn't click invite link?
**A:** After 7 days, link expires. Admin can resend invite from dashboard.

### Q: Can client change subdomain later?
**A:** Yes, but requires manual update (for now). Can be automated later.

### Q: What if database creation fails?
**A:** System retries 3 times. If still fails, admin gets notification to handle manually.

### Q: Can client skip setup wizard?
**A:** No, but they can fill minimal info and complete rest later.

### Q: What happens to data if trial expires?
**A:** Data is preserved for 30 days. Can be restored if they subscribe.

---

## 🎬 NEXT STEPS

Once you understand this flow, we can:
1. **Build the signup form** (email + company name)
2. **Create the automation scripts** (database provisioning)
3. **Build the setup wizard** (4-step process)
4. **Set up email templates** (welcome email)
5. **Test the entire flow** (end-to-end)

Ready to start building? Let me know which part you want to tackle first!
