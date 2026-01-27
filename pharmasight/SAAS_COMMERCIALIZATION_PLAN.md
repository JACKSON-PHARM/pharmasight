# PharmaSight SaaS Commercialization Plan

## Executive Summary

Transform PharmaSight from a single-tenant application to a multi-tenant SaaS platform where each client has:
- **Isolated database** (Supabase PostgreSQL)
- **Unique domain/subdomain** (e.g., `client1.pharmasight.com` or `client1.com`)
- **Shared codebase** (single deployment on Render)
- **Subscription-based access** with module management
- **Automated onboarding** and updates

---

## 1. Architecture Overview

### 1.1 Multi-Tenancy Model: Database-Per-Tenant

**Why Database-Per-Tenant?**
- ✅ Complete data isolation (security, compliance)
- ✅ Independent scaling per client
- ✅ Client-specific backups/restores
- ✅ Easier data export for client offboarding
- ✅ No cross-tenant data leakage risk

**Architecture Pattern:**
```
┌─────────────────────────────────────────┐
│     Render (Single Codebase)            │
│  ┌───────────────────────────────────┐  │
│  │  FastAPI Application              │  │
│  │  - Tenant Router                  │  │
│  │  - Subscription Manager           │  │
│  │  - Module Manager                 │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
           │
           ├───> Supabase Database 1 (Client A)
           ├───> Supabase Database 2 (Client B)
           ├───> Supabase Database 3 (Client C)
           └───> ... (N databases)
```

### 1.2 Tenant Identification Strategy

**Option A: Subdomain Routing** (Recommended)
- `client1.pharmasight.com` → Client 1
- `client2.pharmasight.com` → Client 2
- `acmepharmacy.com` (custom domain) → Client 3

**Option B: Path-Based Routing**
- `pharmasight.com/client1` → Client 1
- `pharmasight.com/client2` → Client 2

**Option C: Header-Based**
- `X-Tenant-ID` header identifies tenant

**Recommendation: Subdomain Routing**
- Cleaner URLs
- Better SEO for custom domains
- Easier SSL certificate management
- Industry standard (Stripe, Shopify, etc.)

---

## 2. Core Components

### 2.1 Tenant Management System

**Database: `pharmasight_control` (Master Database)**
- Stores tenant metadata
- Subscription information
- Module licenses
- Database connection strings

**Tables:**
```sql
tenants (
    id UUID PRIMARY KEY,
    name VARCHAR(255),
    subdomain VARCHAR(100) UNIQUE,
    custom_domain VARCHAR(255),
    database_name VARCHAR(100),  -- Supabase project name
    database_url TEXT,            -- Encrypted connection string
    status VARCHAR(20),            -- 'active', 'suspended', 'trial', 'cancelled'
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)

tenant_subscriptions (
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    plan_id UUID REFERENCES subscription_plans(id),
    status VARCHAR(20),            -- 'active', 'cancelled', 'past_due'
    current_period_start TIMESTAMP,
    current_period_end TIMESTAMP,
    cancel_at_period_end BOOLEAN,
    stripe_subscription_id VARCHAR(255)
)

tenant_modules (
    id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    module_name VARCHAR(100),     -- 'inventory', 'sales', 'purchases', 'reports', etc.
    is_enabled BOOLEAN,
    expires_at TIMESTAMP,          -- NULL = perpetual
    created_at TIMESTAMP
)

subscription_plans (
    id UUID PRIMARY KEY,
    name VARCHAR(100),             -- 'Starter', 'Professional', 'Enterprise'
    price_monthly DECIMAL(10,2),
    price_yearly DECIMAL(10,2),
    max_users INTEGER,
    max_branches INTEGER,
    included_modules TEXT[],        -- Array of module names
    features JSONB
)
```

### 2.2 Tenant Router (Middleware)

**Purpose:** Identify tenant from request and route to correct database

**Implementation Points:**
1. **Subdomain Extraction**
   - Extract subdomain from `Host` header
   - Lookup tenant in master database
   - Load tenant's database connection

2. **Database Connection Pooling**
   - Maintain connection pool per tenant
   - Cache connections (with TTL)
   - Lazy initialization (create on first request)

3. **Request Context**
   - Attach `tenant_id` to request context
   - Make available to all routes via dependency injection

**Flow:**
```
Request → Extract Subdomain → Lookup Tenant → Get DB Connection → Process Request
```

---

## 3. Subscription Management

### 3.1 Payment Processing

**Recommended: Stripe**
- Industry standard
- Handles subscriptions, invoices, webhooks
- Supports multiple currencies
- PCI compliance handled by Stripe

**Integration Points:**
1. **Subscription Creation**
   - User selects plan
   - Create Stripe Checkout Session
   - On success, create `tenant_subscription` record

2. **Webhook Handlers**
   - `customer.subscription.created` → Activate tenant
   - `customer.subscription.updated` → Update plan
   - `customer.subscription.deleted` → Suspend tenant
   - `invoice.payment_succeeded` → Renew access
   - `invoice.payment_failed` → Mark as past_due

3. **Usage Tracking** (Optional)
   - Track API calls, storage, users
   - Bill based on usage (for Enterprise plans)

### 3.2 Subscription Plans

**Tier 1: Starter**
- $99/month or $990/year
- 1 branch
- 5 users
- Core modules: Inventory, Sales, Purchases
- 10,000 items max

**Tier 2: Professional**
- $299/month or $2,990/year
- 5 branches
- 20 users
- All modules: Inventory, Sales, Purchases, Reports, Stock Take
- 50,000 items max
- API access

**Tier 3: Enterprise**
- Custom pricing
- Unlimited branches/users
- All modules + custom modules
- Unlimited items
- Priority support
- Custom integrations
- Dedicated database (optional)

---

## 4. Module Management System

### 4.1 Module Definition

**Modules:**
- `inventory` - Core inventory management
- `sales` - Sales invoicing
- `purchases` - Purchase management
- `reports` - Reporting & analytics
- `stock_take` - Stock counting
- `multi_branch` - Multi-branch support
- `api_access` - API access
- `advanced_reports` - Advanced analytics
- `custom_branding` - White-label options

### 4.2 Module Enforcement

**Backend:**
- Decorator/ middleware to check module access
- Return 403 if module not enabled
- Feature flags in database

**Frontend:**
- Hide/disable UI elements for unavailable modules
- Show upgrade prompts
- Module-based routing guards

**Example:**
```python
@require_module('stock_take')
@router.get("/stock-take/sessions")
def get_stock_take_sessions(...):
    # Only accessible if stock_take module enabled
    pass
```

### 4.3 Module Licensing

**Per-Plan Modules:**
- Starter: `inventory`, `sales`, `purchases`
- Professional: All modules
- Enterprise: All + custom modules

**Add-On Modules:**
- Additional modules can be purchased separately
- Stored in `tenant_modules` table
- Can have expiration dates (for trials)

---

## 5. Database Management

### 5.1 Tenant Database Provisioning

**Automated Process:**
1. **Create Supabase Project**
   - Use Supabase Management API
   - Generate unique project name: `pharmasight-{tenant-id}`
   - Create database user
   - Set up connection pooling

2. **Run Schema Migrations**
   - Apply all migrations to new database
   - Seed initial data (if needed)
   - Create default admin user

3. **Store Connection Details**
   - Encrypt database URL
   - Store in `tenants.database_url`
   - Use environment variable encryption

**Tools Needed:**
- Supabase Management API client
- Migration runner (Alembic)
- Database template (for faster provisioning)

### 5.2 Database Connection Management

**Connection Pooling Strategy:**
- **Per-Tenant Pool:** Separate pool per tenant (better isolation)
- **Shared Pool with Routing:** Single pool, route by tenant_id (more efficient)

**Recommendation: Hybrid**
- Small tenants: Shared pool
- Large tenants: Dedicated pool
- Cache connections with TTL (5 minutes)

**Connection String Format:**
```
postgresql://user:password@host:port/database?sslmode=require
```

### 5.3 Database Migrations

**Challenge:** Apply migrations to all tenant databases

**Strategy:**
1. **Migration Queue System**
   - Queue migration for all active tenants
   - Process in background
   - Track status per tenant
   - Retry failed migrations

2. **Version Tracking**
   - Store schema version in each tenant database
   - Compare with current version
   - Apply only missing migrations

3. **Rollback Strategy**
   - Test migrations on staging tenant first
   - Gradual rollout (10% → 50% → 100%)
   - Monitor for errors

**Implementation:**
- Migration service that iterates through all tenants
- Background job (Celery/BackgroundTasks)
- Admin dashboard to trigger/manage migrations

---

## 6. Client Onboarding

### 6.1 Onboarding Flow

**Step 1: Sign Up**
- User fills form: Company name, email, subdomain preference
- Validate subdomain availability
- Create trial account (14 days)

**Step 2: Database Provisioning**
- Automated: Create Supabase project
- Run migrations
- Create default admin user
- Send credentials email

**Step 3: Initial Setup**
- Admin logs in
- Complete company profile
- Add branches
- Invite users
- Import initial data (optional)

**Step 4: Subscription**
- Select plan
- Enter payment details (Stripe)
- Activate subscription
- Enable modules based on plan

**Timeline:** 5-10 minutes (automated) + user setup time

### 6.2 Onboarding Automation

**Tools:**
- Supabase Management API (create projects)
- Stripe API (create customers)
- Email service (SendGrid/Mailgun)
- Background jobs (Celery/BackgroundTasks)

**Automation Script:**
```
1. Create tenant record
2. Create Supabase project
3. Run database migrations
4. Create admin user
5. Send welcome email with credentials
6. Create Stripe customer
7. Start trial period
```

---

## 7. Updates & Deployment

### 7.1 Code Updates

**Strategy: Blue-Green Deployment**
- Deploy new version to Render
- Test on staging tenant
- Gradual rollout to production tenants
- Monitor for errors
- Rollback if issues detected

**Render Configuration:**
- Single codebase deployed
- Environment variables per tenant (if needed)
- Health checks for each tenant

### 7.2 Database Updates

**Migration Process:**
1. **Development:** Test migration on local database
2. **Staging:** Apply to staging tenant database
3. **Production:** Queue migration for all tenants
4. **Monitor:** Track success/failure per tenant
5. **Verify:** Check application functionality

**Migration Service:**
- Admin dashboard to trigger migrations
- Background job processor
- Status dashboard (which tenants migrated, which failed)
- Retry mechanism for failed migrations

### 7.3 Zero-Downtime Updates

**For Code Updates:**
- Render handles zero-downtime deployments
- Health checks ensure new version is ready
- Old version serves requests until new is ready

**For Database Updates:**
- Backward-compatible migrations first
- Add new columns as nullable
- Deploy code that handles both old and new schema
- Run data migration
- Remove old columns in next deployment

---

## 8. Domain Management

### 8.1 Subdomain Setup

**DNS Configuration:**
- Wildcard DNS: `*.pharmasight.com` → Render IP
- Each tenant gets: `{subdomain}.pharmasight.com`
- SSL certificate: Wildcard cert for `*.pharmasight.com`

**Render Configuration:**
- Single application
- Route based on `Host` header
- No per-tenant deployments needed

### 8.2 Custom Domains

**Process:**
1. Client provides domain: `acmepharmacy.com`
2. Add CNAME record: `acmepharmacy.com` → `client1.pharmasight.com`
3. Generate SSL certificate (Let's Encrypt via Render)
4. Update `tenants.custom_domain` in database
5. Route both subdomain and custom domain to same tenant

**SSL Management:**
- Render handles SSL automatically
- Let's Encrypt certificates
- Auto-renewal

---

## 9. Infrastructure Setup

### 9.1 Render Configuration

**Services:**
1. **Web Service** (FastAPI)
   - Single deployment
   - Environment variables for master database
   - Health checks

2. **Background Worker** (Optional)
   - Celery worker for async tasks
   - Migration processing
   - Email sending
   - Subscription webhooks

3. **PostgreSQL** (Master Database)
   - Small instance for tenant metadata
   - Or use Supabase for master DB too

### 9.2 Supabase Setup

**Per-Tenant:**
- Each tenant gets own Supabase project
- Standard PostgreSQL database
- Connection pooling enabled
- Backups configured (daily)

**Management:**
- Supabase Management API for provisioning
- Terraform/Pulumi for infrastructure as code (optional)

### 9.3 Monitoring & Logging

**Per-Tenant Logging:**
- Tag logs with `tenant_id`
- Separate log streams per tenant (optional)
- Error tracking (Sentry) with tenant context

**Metrics:**
- Request count per tenant
- Database query performance per tenant
- Subscription health (active vs. suspended)

---

## 10. Security Considerations

### 10.1 Data Isolation

**Database-Level:**
- Complete isolation (separate databases)
- No cross-tenant queries possible
- Tenant-specific backups

**Application-Level:**
- Tenant context in every request
- Validate tenant_id on all operations
- No shared sessions between tenants

### 10.2 Authentication

**Per-Tenant:**
- Each tenant has own user base
- JWT tokens include `tenant_id`
- Validate tenant_id matches request subdomain

**Admin Access:**
- Super admin can access all tenants (for support)
- Audit log all admin access
- Require 2FA for admin accounts

### 10.3 API Security

**Rate Limiting:**
- Per-tenant rate limits
- Based on subscription plan
- Protect against abuse

**API Keys:**
- Per-tenant API keys (for Enterprise)
- Track usage per key
- Revoke if compromised

---

## 11. Billing & Subscription Management

### 11.1 Stripe Integration

**Setup:**
1. Create Stripe account
2. Configure products and prices
3. Set up webhook endpoint
4. Handle webhook events

**Webhook Events:**
- `checkout.session.completed` → Activate subscription
- `customer.subscription.updated` → Update plan
- `customer.subscription.deleted` → Cancel subscription
- `invoice.payment_succeeded` → Renew access
- `invoice.payment_failed` → Mark past_due, send email

### 11.2 Subscription Lifecycle

**States:**
- `trial` → 14-day free trial
- `active` → Paid and current
- `past_due` → Payment failed, grace period
- `cancelled` → Cancelled but active until period end
- `suspended` → Access revoked (payment overdue)

**Actions:**
- `past_due` → Send payment reminder, limit features
- `suspended` → Block access, show payment required
- `cancelled` → Allow access until period end, then suspend

### 11.3 Usage Tracking (Optional)

**Metrics to Track:**
- API calls per month
- Storage used (database size)
- Number of users
- Number of branches
- Number of items

**Billing:**
- Starter/Professional: Fixed price
- Enterprise: Base price + usage-based (optional)

---

## 12. Admin Dashboard

### 12.1 Super Admin Features

**Tenant Management:**
- List all tenants
- View tenant details
- Suspend/activate tenants
- View subscription status
- Access tenant database (read-only, for support)

**Subscription Management:**
- View all subscriptions
- Manually adjust plans
- Extend trials
- Process refunds

**Module Management:**
- Enable/disable modules per tenant
- Grant trial modules
- View module usage

**Migration Management:**
- Trigger migrations
- View migration status
- Retry failed migrations
- Rollback migrations (if needed)

### 12.2 Tenant Admin Features

**Subscription:**
- View current plan
- Upgrade/downgrade plan
- View billing history
- Update payment method
- Cancel subscription

**Modules:**
- View enabled modules
- Request module trials
- Purchase add-on modules

---

## 13. Implementation Phases

### Phase 1: Foundation (Weeks 1-2)
- [ ] Create master database schema
- [ ] Implement tenant router middleware
- [ ] Set up Supabase Management API integration
- [ ] Create tenant provisioning automation
- [ ] Build basic admin dashboard

### Phase 2: Subscription System (Weeks 3-4)
- [ ] Integrate Stripe
- [ ] Build subscription management
- [ ] Implement webhook handlers
- [ ] Create billing dashboard
- [ ] Set up payment flows

### Phase 3: Module System (Week 5)
- [ ] Define module structure
- [ ] Implement module checking middleware
- [ ] Update frontend for module-based UI
- [ ] Create module management interface

### Phase 4: Domain & Infrastructure (Week 6)
- [ ] Set up wildcard DNS
- [ ] Configure SSL certificates
- [ ] Set up Render deployment
- [ ] Configure monitoring

### Phase 5: Onboarding Automation (Week 7)
- [ ] Build signup flow
- [ ] Automate database provisioning
- [ ] Create welcome emails
- [ ] Build initial setup wizard

### Phase 6: Migration System (Week 8)
- [ ] Build migration service
- [ ] Create migration dashboard
- [ ] Implement rollback mechanism
- [ ] Test on multiple tenants

### Phase 7: Testing & Launch (Weeks 9-10)
- [ ] Load testing
- [ ] Security audit
- [ ] Documentation
- [ ] Beta testing with 2-3 clients
- [ ] Launch

---

## 14. Cost Estimation

### Infrastructure Costs (Monthly)

**Render:**
- Web Service: $7-25/month (depending on traffic)
- Background Worker: $7/month (optional)
- PostgreSQL (Master DB): $7/month (or use Supabase free tier)

**Supabase (Per Tenant):**
- Free tier: $0 (up to 500MB, 2 projects)
- Pro tier: $25/month per tenant (if needed)
- **Note:** Each tenant = 1 Supabase project

**Stripe:**
- 2.9% + $0.30 per transaction
- No monthly fee

**Domain & SSL:**
- Domain: $10-15/year
- SSL: Free (Let's Encrypt via Render)

**Total Base Cost:** ~$50-100/month (before tenant databases)

**Per-Tenant Cost:** $0-25/month (depending on Supabase tier)

### Revenue Projection

**10 Tenants (Starter Plan):**
- Revenue: $990/month
- Costs: $50 (base) + $0 (free tier) = $50
- Profit: $940/month

**50 Tenants (Mix):**
- 30 Starter @ $99 = $2,970
- 15 Professional @ $299 = $4,485
- 5 Enterprise @ $500 = $2,500
- **Total:** $9,955/month
- **Costs:** $50 (base) + $1,250 (50 × $25 if Pro tier) = $1,300
- **Profit:** $8,655/month

---

## 15. Risk Mitigation

### 15.1 Technical Risks

**Database Provisioning Failures:**
- Retry mechanism
- Manual fallback process
- Monitor Supabase API limits

**Migration Failures:**
- Test on staging first
- Gradual rollout
- Rollback capability
- Per-tenant error handling

**Performance Issues:**
- Connection pooling
- Database query optimization
- Caching strategy
- Load testing before launch

### 15.2 Business Risks

**Payment Failures:**
- Grace period (7 days)
- Email reminders
- Automatic retry
- Manual intervention option

**Client Churn:**
- Onboarding support
- Feature requests
- Regular check-ins
- Usage analytics

**Scaling Challenges:**
- Start with manageable number of tenants
- Monitor resource usage
- Plan for database sharding if needed (future)

---

## 16. Success Metrics

### 16.1 Technical Metrics
- Tenant provisioning time: < 5 minutes
- Migration success rate: > 99%
- Uptime: > 99.9%
- API response time: < 200ms (p95)

### 16.2 Business Metrics
- Monthly Recurring Revenue (MRR)
- Customer Acquisition Cost (CAC)
- Lifetime Value (LTV)
- Churn rate: < 5% monthly
- Trial-to-paid conversion: > 30%

---

## 17. Next Steps

### Immediate Actions:
1. **Review & Approve Plan** - Confirm architecture decisions
2. **Set Up Master Database** - Create `pharmasight_control` database
3. **Supabase API Access** - Get Management API credentials
4. **Stripe Account** - Create account, configure products
5. **Render Account** - Set up project structure

### Decision Points:
- [ ] Confirm database-per-tenant approach
- [ ] Choose subdomain vs. path-based routing
- [ ] Finalize subscription pricing tiers
- [ ] Define module list and pricing
- [ ] Choose monitoring/logging tools

### Documentation Needed:
- [ ] API documentation for tenant management
- [ ] Admin dashboard user guide
- [ ] Client onboarding guide
- [ ] Migration runbook
- [ ] Support procedures

---

## Conclusion

This plan provides a comprehensive roadmap for transforming PharmaSight into a multi-tenant SaaS platform. The database-per-tenant approach ensures complete isolation while the shared codebase keeps maintenance manageable.

**Key Success Factors:**
1. **Automation** - Minimize manual work in onboarding and updates
2. **Monitoring** - Track everything (tenants, subscriptions, migrations)
3. **Scalability** - Design for growth from day one
4. **Security** - Complete data isolation and access controls
5. **User Experience** - Smooth onboarding and clear upgrade paths

**Estimated Timeline:** 10 weeks to full launch
**Initial Investment:** ~$500-1,000 (infrastructure + tools)
**Break-Even:** 5-10 paying customers (depending on plan mix)

Ready to proceed to Phase 1 implementation when approved.
