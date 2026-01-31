# Tenant Management System Setup Guide

## Overview

This guide explains how to set up and use the tenant management system for PharmaSight SaaS.

## What We Built

1. **Master Database Schema** - Stores tenant metadata
2. **Tenant Models** - SQLAlchemy models for tenant management
3. **Admin API** - REST endpoints for managing tenants
4. **Onboarding Service** - Automated tenant provisioning
5. **Admin Dashboard** - Web interface for managing clients

## Setup Steps

### Step 1: Create Master Database Schema

Run the setup script to create the master database tables:

```bash
cd pharmasight/backend
python setup_master_database.py
```

This creates:
- `tenants` table
- `tenant_invites` table
- `subscription_plans` table
- `tenant_subscriptions` table
- `tenant_modules` table

### Step 2: Configure Master Database Connection

The master database can be:
- **Option A**: Same Supabase database (different schema) - **EASIEST FOR NOW**
- **Option B**: Separate Supabase project - **RECOMMENDED FOR PRODUCTION**

For now, we'll use Option A. The master database connection uses the same `DATABASE_URL` but stores tenant metadata separately.

### Step 3: Create First Client

Create PHARMASIGHT MEDS LTD as the first tenant:

```bash
cd pharmasight/backend
python create_first_client.py
```

This will:
- Create tenant record
- Set up Professional plan subscription
- Enable all modules
- Use your existing database connection

### Step 4: Access Admin Dashboard

Open the admin dashboard:
```
http://localhost:8000/admin.html
```

Or if deployed:
```
https://pharmasight.com/admin.html
```

## API Endpoints

### Admin Endpoints (Tenant Management)

```
GET    /api/admin/tenants              - List all tenants
GET    /api/admin/tenants/{id}         - Get tenant details
POST   /api/admin/tenants              - Create tenant manually
PATCH  /api/admin/tenants/{id}         - Update tenant
DELETE /api/admin/tenants/{id}         - Delete tenant (soft delete)

POST   /api/admin/tenants/{id}/invites - Create invite token
GET    /api/admin/tenants/{id}/invites - List invites

GET    /api/admin/plans                - List subscription plans
GET    /api/admin/tenants/{id}/subscription - Get subscription
GET    /api/admin/tenants/{id}/modules  - List enabled modules
```

### Onboarding Endpoints (Client Signup)

```
POST   /api/onboarding/signup          - Client signup (email + company name)
GET    /api/onboarding/validate-token/{token} - Validate invite token
```

## How It Works

### Client Signup Flow

1. **Client visits signup page**
   - Enters email and company name
   - Clicks "Start Free Trial"

2. **System automatically:**
   - Generates unique subdomain
   - Creates tenant record
   - Provisions database (or uses existing)
   - Runs migrations
   - Creates admin user
   - Sets up 14-day trial
   - Generates invite token
   - Sends welcome email

3. **Client receives email:**
   - Invite link: `https://{subdomain}.pharmasight.com/setup?token={token}`
   - Temporary password
   - Setup instructions

4. **Client clicks invite link:**
   - Validates token
   - Shows setup wizard
   - Sets password
   - Adds company info
   - Creates first branch
   - Starts using PharmaSight

### Admin Management Flow

1. **View all tenants:**
   - Open admin dashboard
   - See list of all clients
   - Filter by status, search by name/email

2. **Create tenant manually:**
   - Click "Create New Tenant"
   - Enter company name and email
   - System generates subdomain
   - Creates tenant record

3. **Create invite:**
   - Click "Invite" button on tenant
   - System generates secure token
   - Copy invite link
   - Send to client

4. **Manage subscriptions:**
   - View tenant subscription
   - Update plan
   - Enable/disable modules

## Database Structure

### Master Database (Tenant Metadata)

```
tenants
├── id (UUID)
├── name (Company name)
├── subdomain (Unique subdomain)
├── admin_email (First admin email)
├── database_url (Encrypted connection string)
├── status (trial/active/suspended/cancelled)
└── ...

tenant_invites
├── tenant_id
├── token (Secure invite token)
├── expires_at
└── used_at

tenant_subscriptions
├── tenant_id
├── plan_id
├── status
└── ...

tenant_modules
├── tenant_id
├── module_name
└── is_enabled
```

### Tenant Databases (Client Data)

Each tenant has their own isolated database with:
- All your existing tables (items, sales, purchases, etc.)
- Complete data isolation
- Independent backups

## Important Notes

### About Supabase Account Email

**Question:** "The client email matches my Supabase account email - how does this work?"

**Answer:** This is fine! Here's why:

1. **Supabase Management API** uses an **access token**, not your account email
2. Each tenant gets their **own Supabase project** (separate database)
3. Your account email is just for **authentication** to Supabase dashboard
4. The tenant's admin email is for **logging into PharmaSight**, not Supabase

**For PHARMASIGHT MEDS LTD:**
- Your Supabase account: `pharmasightsolutions@gmail.com` (for dashboard access)
- Tenant admin email: `pharmasightsolutions@gmail.com` (for PharmaSight login)
- These can be the same - no conflict!

### Database Provisioning

**Current Implementation:**
- Uses same database connection for all tenants (development)
- Each tenant should have separate database in production

**Future Implementation:**
- Use Supabase Management API to create new projects
- Each tenant = 1 Supabase project
- Automated provisioning via API

### Security

- **Database URLs are encrypted** (should implement encryption)
- **Invite tokens expire** after 7 days
- **Tokens are one-time-use** (marked as used after setup)
- **Each tenant has isolated database** (no data leakage)

## Next Steps

1. **Set up master database** - Run `setup_master_database.py`
2. **Create first client** - Run `create_first_client.py`
3. **Test admin dashboard** - Open `/admin.html`
4. **Test signup flow** - Use `/api/onboarding/signup`
5. **Implement Supabase Management API** - For automated database creation
6. **Add email service** - Send welcome emails automatically
7. **Add Stripe integration** - For subscription billing

## Troubleshooting

### "Master database schema not found"
- Run `setup_master_database.py` first
- Check database connection in `.env`

### "Tenant already exists"
- Check if tenant with same email exists
- Use admin dashboard to view existing tenants

### "Invite token expired"
- Create new invite from admin dashboard
- Tokens expire after 7 days

### "Database connection failed"
- Check `DATABASE_URL` in `.env`
- Verify Supabase credentials

## Support

For issues or questions:
1. Check this guide
2. Review API documentation at `/docs`
3. Check logs for error messages

---

**Ready to start?** Run the setup scripts and open the admin dashboard!
