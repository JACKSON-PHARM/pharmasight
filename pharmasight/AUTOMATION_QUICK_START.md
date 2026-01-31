# Automation Quick Start Guide

## 🎯 What We Built

Three critical automation systems:

1. **Automated Database Creation** - Supabase Management API
2. **Update Rollout System** - Migrations across all tenants
3. **Stripe Integration** - Subscription billing

---

## 1. Automated Database Creation

### How It Works

**Before (Manual):**
```
1. Go to Supabase dashboard
2. Click "New Project"
3. Fill in details
4. Wait for project to be ready
5. Copy connection string
6. Add to tenant record
```

**After (Automated):**
```
Client signs up → System automatically creates Supabase project → Ready in 2-5 minutes
```

### Setup (5 minutes)

1. **Get Supabase Access Token:**
   - Go to: https://supabase.com/dashboard/account/tokens
   - Generate new token
   - Copy token

2. **Get Organization ID:**
   - Go to: https://supabase.com/dashboard/organizations
   - Copy organization ID from URL or settings

3. **Add to `.env`:**
   ```bash
   SUPABASE_ACCESS_TOKEN=your_token_here
   SUPABASE_ORGANIZATION_ID=your_org_id
   SUPABASE_REGION=us-east-1
   SUPABASE_PLAN=free
   ```

4. **Test:**
   ```python
   from app.services.supabase_provisioning import SupabaseProvisioningService
   
   service = SupabaseProvisioningService()
   project = service.create_project(
       project_name="pharmasight-test",
       organization_id="your-org-id"
   )
   print(project)
   ```

### What Happens

1. Client signs up with email + company name
2. System calls Supabase API
3. New Supabase project created (1-5 minutes)
4. Database connection stored
5. Migrations run automatically
6. Admin user created
7. Tenant ready to use!

---

## 2. Update Rollout System

### How Updates Work

**Code Updates (Easy):**
- Deploy once to Render
- All tenants get update automatically
- No per-tenant action needed

**Database Updates (Complex):**
- Each tenant has own database
- Must apply migrations to all
- Track status per tenant

### Update Process

#### For Code:
```bash
# 1. Test locally
python -m pytest

# 2. Deploy
git push production main

# 3. Done! All tenants get update
```

#### For Database:
```bash
# 1. Create migration
# Edit: database/migrations/001_add_feature.sql

# 2. Test on staging
python -m app.services.migration_service --tenant staging

# 3. Deploy code
git push production main

# 4. Run migration for all tenants
POST /api/admin/migrations/run
{
  "migration_sql": "ALTER TABLE items ADD COLUMN new_field VARCHAR(255);",
  "version": "20240127_add_new_field"
}

# 5. Check status
GET /api/admin/migrations/status
```

### Rollout Strategies

**Option 1: All at Once** (Fast, Risky)
- Apply to all tenants simultaneously
- Use for small, safe changes

**Option 2: Gradual** (Recommended)
- 10% → 50% → 100%
- Monitor for errors
- Rollback if needed

**Option 3: Canary** (Safest)
- Apply to 1 tenant first
- Monitor 24 hours
- Then roll out to all

### Migration Best Practices

1. **Backward Compatible:**
   ```sql
   -- Good: Add nullable column
   ALTER TABLE items ADD COLUMN new_field VARCHAR(255);
   
   -- Bad: Remove column immediately
   ALTER TABLE items DROP COLUMN old_field;
   ```

2. **Idempotent:**
   ```sql
   -- Good: Safe to run multiple times
   ALTER TABLE items ADD COLUMN IF NOT EXISTS new_field VARCHAR(255);
   ```

3. **Test First:**
   - Always test on staging tenant
   - Review SQL before running
   - Small changes are better

---

## 3. Stripe Integration

### How It Works

```
Client Chooses Plan
    ↓
Stripe Checkout (Payment Page)
    ↓
Payment Successful
    ↓
Webhook → Your Server
    ↓
Activate Subscription
    ↓
Enable Modules
```

### Setup (10 minutes)

1. **Create Stripe Account:**
   - Go to: https://stripe.com
   - Create account
   - Get API keys from dashboard

2. **Add to `.env`:**
   ```bash
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   ```

3. **Create Products in Stripe:**
   - Products → Create Product
   - "Starter Plan" - $99/month
   - "Professional Plan" - $299/month
   - Copy Price IDs

4. **Store Price IDs:**
   ```sql
   UPDATE subscription_plans 
   SET stripe_price_id_monthly = 'price_...' 
   WHERE name = 'Starter';
   ```

5. **Set Up Webhook:**
   - Webhooks → Add endpoint
   - URL: `https://yourdomain.com/api/webhooks/stripe`
   - Select events (see below)
   - Copy webhook secret to `.env`:
     ```bash
     STRIPE_WEBHOOK_SECRET=whsec_...
     ```

### Webhook Events

Select these events in Stripe dashboard:

- ✅ `checkout.session.completed` - Payment successful
- ✅ `customer.subscription.created` - New subscription
- ✅ `customer.subscription.updated` - Plan changed
- ✅ `customer.subscription.deleted` - Cancelled
- ✅ `invoice.payment_succeeded` - Monthly payment
- ✅ `invoice.payment_failed` - Payment failed

### Payment Flow

1. **Trial (14 days):**
   - Client signs up
   - No payment required
   - Access to Starter features

2. **Trial Ending:**
   - System sends email
   - Client clicks "Choose Plan"
   - Redirected to Stripe Checkout

3. **Payment:**
   - Client enters card details
   - Stripe processes payment
   - Webhook received
   - Subscription activated

4. **Monthly Renewal:**
   - Stripe charges automatically
   - Webhook: `invoice.payment_succeeded`
   - Access continues

5. **Payment Failure:**
   - Webhook: `invoice.payment_failed`
   - Status: `past_due`
   - Grace period (7 days)
   - Then suspended

### Subscription Lifecycle

```
Trial (14 days, free)
    ↓
Active (paid, monthly/yearly)
    ↓
Past Due (payment failed)
    ↓
Suspended (after grace period)
    ↓
Cancelled (client cancelled)
```

---

## Quick Reference

### Environment Variables

```bash
# Supabase Management API
SUPABASE_ACCESS_TOKEN=...
SUPABASE_ORGANIZATION_ID=...
SUPABASE_REGION=us-east-1
SUPABASE_PLAN=free

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### API Endpoints

**Migrations:**
```
POST /api/admin/migrations/run - Run migration on all tenants
GET  /api/admin/migrations/status - Get migration status
```

**Stripe:**
```
POST /api/webhooks/stripe - Webhook endpoint
GET  /api/webhooks/stripe/test - Test endpoint
```

### Testing

**Database Automation:**
```python
from app.services.supabase_provisioning import SupabaseProvisioningService
service = SupabaseProvisioningService()
project = service.create_project("test-project", "org-id")
```

**Migrations:**
```python
from app.services.migration_service import MigrationService
service = MigrationService()
result = service.run_migration_for_all_tenants(
    migration_sql="ALTER TABLE items ADD COLUMN test VARCHAR(255);",
    version="test_001"
)
```

**Stripe Webhooks:**
```bash
# Use Stripe CLI for testing
stripe listen --forward-to localhost:8000/api/webhooks/stripe
stripe trigger checkout.session.completed
```

---

## Implementation Order

1. **Week 1: Database Automation**
   - Set up Supabase API
   - Test provisioning
   - Integrate with onboarding

2. **Week 2: Migration System**
   - Create migration service
   - Build admin UI
   - Test on staging

3. **Week 3-4: Stripe**
   - Set up Stripe account
   - Create products/prices
   - Implement webhooks
   - Build payment UI

---

## Next Steps

1. **Review `AUTOMATION_GUIDE.md`** - Detailed explanation
2. **Follow `IMPLEMENTATION_CHECKLIST.md`** - Step-by-step tasks
3. **Start with database automation** - Easiest to implement
4. **Test thoroughly** - Before production

**Ready to automate?** Start with Supabase API setup!
