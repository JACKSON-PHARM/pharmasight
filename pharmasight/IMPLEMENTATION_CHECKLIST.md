# Implementation Checklist

## ✅ Completed
- [x] Master database schema
- [x] Tenant models and schemas
- [x] Admin API endpoints
- [x] Onboarding service (basic)
- [x] Admin dashboard UI
- [x] Documentation

## 🚧 To Implement

### 1. Supabase Management API Integration

#### Setup
- [ ] Get Supabase access token from dashboard
- [ ] Get organization ID
- [ ] Add to `.env`:
  ```
  SUPABASE_ACCESS_TOKEN=your_token
  SUPABASE_ORGANIZATION_ID=your_org_id
  SUPABASE_REGION=us-east-1
  SUPABASE_PLAN=free
  ```

#### Implementation
- [ ] Install `requests` library (already in requirements)
- [ ] Test `SupabaseProvisioningService.create_project()`
- [ ] Handle database password retrieval
- [ ] Update onboarding service to use provisioning
- [ ] Test with first tenant

#### Testing
- [ ] Create test tenant via signup
- [ ] Verify Supabase project created
- [ ] Verify database connection works
- [ ] Verify migrations run successfully

### 2. Migration System

#### Setup
- [ ] Create `database/migrations/` directory
- [ ] Set up Alembic (optional, or use SQL files)
- [ ] Create schema version tracking table

#### Implementation
- [ ] Test `MigrationService` with one tenant
- [ ] Create admin UI for migrations
- [ ] Add migration history tracking
- [ ] Implement retry mechanism
- [ ] Add rollback capability

#### Testing
- [ ] Create test migration
- [ ] Run on staging tenant
- [ ] Run on all tenants
- [ ] Verify status tracking works
- [ ] Test rollback

### 3. Stripe Integration

#### Setup
- [ ] Create Stripe account
- [ ] Get API keys (test mode first)
- [ ] Add to `.env`:
  ```
  STRIPE_SECRET_KEY=sk_test_...
  STRIPE_PUBLISHABLE_KEY=pk_test_...
  STRIPE_WEBHOOK_SECRET=whsec_...
  ```

#### Create Products & Prices
- [ ] Create "Starter" product in Stripe
- [ ] Create monthly price: $99/month
- [ ] Create yearly price: $990/year
- [ ] Create "Professional" product
- [ ] Create monthly price: $299/month
- [ ] Create yearly price: $2,990/year
- [ ] Store price IDs in `subscription_plans` table

#### Webhook Setup
- [ ] Set up webhook endpoint in Stripe dashboard
- [ ] URL: `https://yourdomain.com/api/webhooks/stripe`
- [ ] Select events:
  - checkout.session.completed
  - customer.subscription.created
  - customer.subscription.updated
  - customer.subscription.deleted
  - invoice.payment_succeeded
  - invoice.payment_failed
- [ ] Copy webhook secret to `.env`

#### Implementation
- [ ] Install `stripe` library: `pip install stripe`
- [ ] Test webhook endpoint
- [ ] Implement checkout session creation
- [ ] Test payment flow
- [ ] Implement webhook handlers
- [ ] Test all webhook events

#### Frontend
- [ ] Create "Choose Plan" page
- [ ] Integrate Stripe Checkout
- [ ] Show subscription status
- [ ] Add "Upgrade/Downgrade" UI
- [ ] Add "Cancel Subscription" UI

#### Testing
- [ ] Test signup → trial → payment flow
- [ ] Test webhook events (use Stripe CLI)
- [ ] Test subscription updates
- [ ] Test payment failures
- [ ] Test cancellations

### 4. Email Service

#### Setup
- [ ] Choose email service (SendGrid, Mailgun, AWS SES)
- [ ] Create account
- [ ] Get API key
- [ ] Add to `.env`

#### Implementation
- [ ] Create email templates
- [ ] Welcome email (with invite link)
- [ ] Trial ending reminder
- [ ] Payment failed notification
- [ ] Subscription activated
- [ ] Password reset (if needed)

#### Testing
- [ ] Send test welcome email
- [ ] Verify invite link works
- [ ] Test all email templates

### 5. Subdomain Routing

#### DNS Setup
- [ ] Configure wildcard DNS: `*.pharmasight.com`
- [ ] Point to Render IP/domain
- [ ] Set up SSL certificates (Let's Encrypt)

#### Backend
- [ ] Implement subdomain extraction middleware
- [ ] Route requests based on subdomain
- [ ] Load tenant database connection
- [ ] Test routing

#### Testing
- [ ] Test subdomain routing
- [ ] Test SSL certificates
- [ ] Test custom domains (future)

---

## Priority Order

### Week 1: Database Automation
1. Set up Supabase API
2. Test provisioning
3. Integrate with onboarding
4. Deploy

### Week 2: Migration System
1. Create migration service
2. Build admin UI
3. Test on staging
4. Document process

### Week 3-4: Stripe Integration
1. Set up Stripe account
2. Create products/prices
3. Implement webhooks
4. Build payment UI
5. Test end-to-end

### Week 5: Email & Polish
1. Set up email service
2. Create templates
3. Test all flows
4. Documentation

---

## Environment Variables Needed

```bash
# Supabase Management API
SUPABASE_ACCESS_TOKEN=your_token_here
SUPABASE_ORGANIZATION_ID=your_org_id
SUPABASE_REGION=us-east-1
SUPABASE_PLAN=free

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email Service (choose one)
SENDGRID_API_KEY=SG....
# OR
MAILGUN_API_KEY=...
MAILGUN_DOMAIN=...

# Master Database (if separate)
MASTER_DATABASE_URL=postgresql://...
```

---

## Testing Checklist

### Database Automation
- [ ] Create tenant via signup
- [ ] Verify Supabase project created
- [ ] Verify database accessible
- [ ] Verify migrations applied
- [ ] Verify admin user created

### Migrations
- [ ] Create test migration
- [ ] Run on one tenant
- [ ] Run on all tenants
- [ ] Verify status tracking
- [ ] Test rollback

### Stripe
- [ ] Test checkout session creation
- [ ] Complete test payment
- [ ] Verify webhook received
- [ ] Verify subscription activated
- [ ] Test payment failure
- [ ] Test cancellation

### End-to-End
- [ ] Client signup → database created → invite sent
- [ ] Client clicks invite → sets up account
- [ ] Trial ends → payment required
- [ ] Payment successful → subscription active
- [ ] Update plan → modules updated
- [ ] Cancel → access suspended

---

**Start with database automation, then migrations, then Stripe!**
