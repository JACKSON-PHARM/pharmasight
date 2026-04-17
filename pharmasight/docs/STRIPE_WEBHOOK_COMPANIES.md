# Stripe webhooks and the `companies` table (future billing)

PharmaSight uses a **single shared Postgres database**. Subscription and trial state for SaaS gating live on **`companies`**: `subscription_plan`, `subscription_status`, `trial_expires_at`, and `is_active`. The ERP and marketing portal read the same fields via `GET /api/auth/me`.

## Recommended mapping

1. **Stripe Customer** — store `stripe_customer_id` on `companies` (add column) or in a small `company_billing` table keyed by `company_id` (UUID FK to `companies.id`). Never key billing only by email without resolving `company_id` from the authenticated user.

2. **Checkout / subscription created** — webhook `customer.subscription.created` or `checkout.session.completed`:
   - Resolve `company_id` from Stripe metadata you set when creating Checkout (`metadata.company_id`) or from your `company_billing` row by `customer.id`.
   - Update **`companies.subscription_status`** to `active` (or your enum).
   - Set **`companies.subscription_plan`** to a stable slug (`basic`, `pro`, …) aligned with your pricing page.
   - Optionally clear or extend **`trial_expires_at`** when moving from trial to paid.

3. **Payment failed / canceled** — `customer.subscription.deleted` or `invoice.payment_failed`:
   - Set **`companies.subscription_status`** to `past_due`, `canceled`, or similar.
   - Do **not** delete the company row; rely on `get_company_access`-style rules so the app can show a clear paywall.

4. **Trials** — either keep using **`trial_expires_at`** only (current access logic) or set `subscription_status` when Stripe trial ends; keep one source of truth to avoid contradicting `GET /api/auth/me`.

5. **Security** — verify webhook signatures with the Stripe signing secret; run updates in a DB transaction scoped by **`company_id`** parsed from trusted metadata, not from unverified client input.

## Endpoint shape (suggested)

- `POST /api/stripe/webhook` — raw body + `Stripe-Signature` header; no JWT auth; idempotent handling using `event.id` stored in a `stripe_webhook_events` table if needed.

This document is planning-only until Stripe is integrated; keep all writes **company-scoped** on the shared database.
