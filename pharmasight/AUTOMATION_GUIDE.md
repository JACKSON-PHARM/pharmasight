# Automation Guide: Database Creation, Updates & Stripe Integration

## Overview

This guide explains how to implement:
1. **Automated Database Creation** - Using Supabase Management API
2. **Update Rollout System** - How to deploy updates to all tenants
3. **Stripe Integration** - Subscription billing automation

---

## 1. Automated Database Creation (Supabase Management API)

### How It Works

Instead of manually creating Supabase projects, we'll use the Supabase Management API to automatically provision a new database for each tenant.

### Architecture

```
Client Signup
    ↓
Onboarding Service
    ↓
Supabase Management API
    ↓
New Supabase Project Created
    ↓
Database Migrations Run
    ↓
Admin User Created
    ↓
Tenant Ready
```

### Setup Steps

#### Step 1: Get Supabase Access Token

1. Go to: https://supabase.com/dashboard/account/tokens
2. Click "Generate New Token"
3. Give it a name: "PharmaSight Automation"
4. Copy the token (you'll only see it once!)
5. Add to `.env`:
   ```
   SUPABASE_ACCESS_TOKEN=your_token_here
   ```

#### Step 2: Install Supabase Python Client

```bash
pip install supabase
```

#### Step 3: Implementation

The onboarding service will:
1. Call Supabase Management API to create new project
2. Wait for project to be ready
3. Get database connection details
4. Run migrations on new database
5. Create admin user
6. Store connection info (encrypted)

### Code Implementation

See `backend/app/services/supabase_provisioning.py` (we'll create this)

### Cost Considerations

- **Free Tier**: 2 projects per organization
- **Pro Tier**: $25/month per project (after free tier)
- **Recommendation**: Start with free tier, upgrade as needed

### Benefits

- ✅ Fully automated (no manual steps)
- ✅ Consistent setup (same for all tenants)
- ✅ Isolated databases (complete data separation)
- ✅ Independent backups per tenant
- ✅ Easy to scale

---

## 2. Update Rollout System

### How Updates Work

When you deploy a new version of PharmaSight, you need to update:
1. **Code** - Deployed once (shared by all tenants)
2. **Database Schema** - Must be applied to each tenant's database

### Update Strategy

#### Phase 1: Code Updates (Easy)

**Single Deployment:**
- Deploy new code to Render
- All tenants automatically get new code
- No downtime (blue-green deployment)

**Process:**
```
1. Test locally
2. Deploy to staging tenant
3. Test on staging
4. Deploy to production (Render)
5. All tenants get update automatically
```

#### Phase 2: Database Updates (Complex)

**Challenge:** Each tenant has their own database. Updates must be applied to all.

**Solution:** Migration Queue System

### Migration System Architecture

```
Admin Triggers Migration
    ↓
Migration Service
    ↓
Queue Migration for All Tenants
    ↓
Process in Background (Parallel)
    ↓
Track Status Per Tenant
    ↓
Retry Failed Migrations
    ↓
Report Results
```

### Implementation Steps

#### Step 1: Migration Version Tracking

Each tenant database stores its schema version:

```sql
CREATE TABLE schema_migrations (
    version VARCHAR(50) PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

#### Step 2: Migration Service

A service that:
1. Lists all active tenants
2. Checks each tenant's schema version
3. Applies missing migrations
4. Tracks success/failure
5. Retries on failure

#### Step 3: Admin Dashboard

UI to:
- View migration status
- Trigger migrations
- See which tenants succeeded/failed
- Retry failed migrations

### Update Rollout Process

#### For Code Updates:

```bash
# 1. Test locally
python -m pytest

# 2. Deploy to staging
git push staging main

# 3. Test staging tenant
# Visit: staging.pharmasight.com

# 4. Deploy to production
git push production main

# 5. All tenants get update automatically
# No action needed per tenant
```

#### For Database Updates:

```bash
# 1. Create migration file
alembic revision --autogenerate -m "add_new_feature"

# 2. Test on local database
alembic upgrade head

# 3. Test on staging tenant database
python run_migration.py --tenant staging

# 4. Deploy code (with migration files)
git push production main

# 5. Trigger migration for all tenants
# Via admin dashboard or API:
POST /api/admin/migrations/run

# 6. Monitor progress
GET /api/admin/migrations/status
```

### Gradual Rollout Strategy

**Option 1: All at Once**
- Apply to all tenants simultaneously
- Fast but risky
- Use for small, safe changes

**Option 2: Gradual (Recommended)**
- 10% → 50% → 100%
- Monitor for errors
- Rollback if issues detected
- Use for major changes

**Option 3: Canary**
- Apply to 1 tenant first
- Monitor for 24 hours
- If successful, roll out to all
- Use for critical changes

### Rollback Strategy

If a migration fails:

1. **Automatic Rollback:**
   - Migration service detects failure
   - Automatically rolls back (if migration supports it)
   - Marks tenant as "failed"
   - Sends alert to admin

2. **Manual Rollback:**
   - Admin reviews failed migration
   - Fixes issue
   - Retries migration
   - Or manually applies fix

### Migration Best Practices

1. **Backward Compatible Changes:**
   - Add new columns as nullable
   - Don't remove columns immediately
   - Support both old and new code

2. **Test First:**
   - Always test on staging tenant
   - Test on local database
   - Review migration SQL

3. **Small Changes:**
   - Break large migrations into small ones
   - Easier to debug
   - Faster to apply

4. **Idempotent:**
   - Migrations should be safe to run multiple times
   - Use `IF NOT EXISTS` where possible
   - Check before applying

---

## 3. Stripe Integration

### How Stripe Works

Stripe handles:
- Payment processing
- Subscription management
- Invoicing
- Webhooks (notifications)

### Architecture

```
Client Chooses Plan
    ↓
Create Stripe Checkout Session
    ↓
Client Pays
    ↓
Stripe Webhook → Your Server
    ↓
Activate Subscription
    ↓
Enable Modules
```

### Setup Steps

#### Step 1: Create Stripe Account

1. Go to: https://stripe.com
2. Create account
3. Get API keys from dashboard
4. Add to `.env`:
   ```
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   STRIPE_WEBHOOK_SECRET=whsec_... (after setting up webhook)
   ```

#### Step 2: Create Products & Prices

In Stripe Dashboard:
1. Products → Create Product
2. Create prices for each plan:
   - Starter: $99/month
   - Professional: $299/month
   - Enterprise: Custom (manual)

Or via API (we'll automate this)

#### Step 3: Webhook Setup

1. Stripe Dashboard → Webhooks
2. Add endpoint: `https://yourdomain.com/api/webhooks/stripe`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
4. Copy webhook secret to `.env`

### Implementation Flow

#### 1. Client Signup (Trial)

```
Client signs up → 14-day trial starts
No payment required
Access to Starter plan features
```

#### 2. Trial Ending (Day 14)

```
System sends email: "Trial ending in 2 days"
Client clicks "Choose Plan"
Redirected to Stripe Checkout
```

#### 3. Payment Flow

```
Client selects plan
    ↓
Create Stripe Checkout Session
    ↓
Redirect to Stripe payment page
    ↓
Client enters payment details
    ↓
Stripe processes payment
    ↓
Webhook received: checkout.session.completed
    ↓
Activate subscription
    ↓
Enable modules based on plan
    ↓
Redirect to dashboard
```

#### 4. Subscription Management

**Upgrade/Downgrade:**
```
Client clicks "Upgrade Plan"
    ↓
Create Stripe Checkout Session (for upgrade)
    ↓
Webhook: customer.subscription.updated
    ↓
Update plan in database
    ↓
Enable/disable modules
```

**Cancellation:**
```
Client clicks "Cancel Subscription"
    ↓
Update subscription: cancel_at_period_end = true
    ↓
Access continues until period end
    ↓
Webhook: customer.subscription.deleted (at period end)
    ↓
Suspend access
```

### Webhook Events

#### `checkout.session.completed`
- Payment successful
- Activate subscription
- Enable modules

#### `customer.subscription.created`
- New subscription created
- Update tenant status to 'active'

#### `customer.subscription.updated`
- Plan changed
- Update plan in database
- Adjust modules

#### `customer.subscription.deleted`
- Subscription cancelled
- Suspend tenant access
- Preserve data for 30 days

#### `invoice.payment_succeeded`
- Monthly payment successful
- Renew subscription period
- Continue access

#### `invoice.payment_failed`
- Payment failed
- Mark as 'past_due'
- Send reminder email
- Grace period (7 days)
- Then suspend

### Subscription Lifecycle

```
Trial (14 days)
    ↓
Active (paid)
    ↓
Past Due (payment failed)
    ↓
Suspended (after grace period)
    ↓
Cancelled (client cancelled)
    ↓
Archived (after 30 days)
```

### Pricing Tiers

#### Starter Plan
- **Price:** $99/month or $990/year
- **Modules:** inventory, sales, purchases
- **Limits:** 1 branch, 5 users, 10,000 items

#### Professional Plan
- **Price:** $299/month or $2,990/year
- **Modules:** All modules
- **Limits:** 5 branches, 20 users, 50,000 items

#### Enterprise Plan
- **Price:** Custom (contact sales)
- **Modules:** All + custom modules
- **Limits:** Unlimited

### Security

- **Webhook Verification:** Verify webhook signatures
- **Idempotency:** Handle duplicate webhooks
- **Error Handling:** Retry failed webhooks
- **Logging:** Log all webhook events

---

## Implementation Priority

### Phase 1: Database Automation (Week 1)
1. Set up Supabase Management API
2. Implement automated provisioning
3. Test with first tenant
4. Deploy to production

### Phase 2: Migration System (Week 2)
1. Create migration service
2. Build admin dashboard UI
3. Test on staging tenant
4. Document process

### Phase 3: Stripe Integration (Week 3-4)
1. Set up Stripe account
2. Create products/prices
3. Implement webhook handlers
4. Build payment UI
5. Test end-to-end

---

## Next Steps

1. **Review this guide** - Understand the architecture
2. **Set up Supabase API** - Get access token
3. **Set up Stripe** - Create account, get API keys
4. **Start implementation** - Begin with database automation
5. **Test thoroughly** - Before deploying to production

---

**Ready to implement?** Let's start with the Supabase Management API integration!
