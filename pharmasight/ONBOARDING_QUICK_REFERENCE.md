# Onboarding Quick Reference - At a Glance

## 🎯 The 3-Minute Overview

### What Client Provides:
```
┌─────────────────────────────┐
│  Email: john@acme.com       │
│  Company: Acme Pharmacy     │
└─────────────────────────────┘
```

### What System Does Automatically:
```
1. Generate subdomain → acmepharmacy.pharmasight.com
2. Create Supabase database → Fresh PostgreSQL database
3. Run migrations → All tables created
4. Create admin user → john@acme.com (temporary password)
5. Set up trial → 14 days free
6. Generate invite link → Secure token
7. Send email → Welcome email with link
```

### What Client Does:
```
1. Clicks invite link
2. Sets password
3. Adds company info
4. Creates first branch
5. (Optional) Invites team
6. Starts using PharmaSight!
```

---

## 📋 Step-by-Step Checklist

### Phase 1: Client Signup (30 seconds)
- [ ] Client visits `pharmasight.com/signup`
- [ ] Enters email + company name
- [ ] Clicks "Start Free Trial"
- [ ] System shows: "Check your email"

### Phase 2: Automated Setup (3-5 minutes)
- [ ] System generates unique subdomain
- [ ] System creates Supabase database
- [ ] System runs all migrations
- [ ] System creates admin user
- [ ] System sets up 14-day trial
- [ ] System generates invite token
- [ ] System sends welcome email

### Phase 3: Client Setup (5-10 minutes)
- [ ] Client receives email
- [ ] Client clicks invite link
- [ ] Client sets password
- [ ] Client adds company details
- [ ] Client creates first branch
- [ ] Client (optionally) invites team
- [ ] Client lands on dashboard

### Phase 4: Client Onboarding (Variable)
- [ ] Client loads stock (Excel import or manual)
- [ ] Client adds more users (if needed)
- [ ] Client adds more branches (if needed)
- [ ] Client makes first sale
- [ ] Client is fully operational!

---

## 🔄 The Complete Flow Diagram

```
CLIENT ACTION                    SYSTEM ACTION
─────────────────────────────────────────────────────
1. Fills signup form      →     Validates & processes
                                 
2. (Waits for email)      →     Creates database
                                 Runs migrations
                                 Creates admin user
                                 Generates invite link
                                 Sends email
                                 
3. Clicks invite link     →     Validates token
                                 Shows setup wizard
                                 
4. Completes setup        →     Saves company info
                                 Creates branch
                                 Updates password
                                 
5. Starts using app       →     All data stored in
                                 their isolated database
                                 
6. Trial ends (Day 14)    →     Sends payment reminder
                                 
7. Chooses plan & pays    →     Activates subscription
                                 Enables modules
                                 
8. Continues using        →     Full access maintained
```

---

## 💡 Key Simplifications

### ✅ What We Simplified:
1. **No subdomain selection** → System auto-generates
2. **No payment upfront** → Trial first, pay later
3. **No complex forms** → Just email + company name
4. **No manual database setup** → Fully automated
5. **No technical knowledge needed** → Guided wizard

### 🎯 What Makes It Smooth:
- **3-5 minute setup** → Database ready automatically
- **One-click access** → Invite link handles everything
- **Guided experience** → Setup wizard walks them through
- **Flexible** → Can skip steps, complete later
- **No interruptions** → Seamless from signup to first sale

---

## 🛠️ Technical Components Needed

### 1. Signup Form
- Simple 2-field form
- Email validation
- Company name sanitization
- Subdomain generation logic

### 2. Automation Service
- Supabase Management API integration
- Database creation script
- Migration runner
- User creation script
- Email sender

### 3. Setup Wizard
- Token validation
- Password reset flow
- Company info form
- Branch creation form
- User invitation form

### 4. Master Database
- `tenants` table (tenant metadata)
- `tenant_invites` table (invite tokens)
- `tenant_subscriptions` table (trial/subscription info)

### 5. Email Templates
- Welcome email (with invite link)
- Password reset email
- Team invitation email
- Trial ending reminder

---

## 📊 Timeline Breakdown

| Phase | Duration | Who Does It |
|-------|----------|-------------|
| Client signup | 30 seconds | Client |
| Automated setup | 3-5 minutes | System |
| Email delivery | 1-2 minutes | Email service |
| Client setup | 5-10 minutes | Client |
| Stock loading | 10-60 minutes | Client |
| First sale | Immediate | Client |

**Total time to first sale:** 20-80 minutes (depending on stock import)

---

## 🎯 Success Criteria

### ✅ Onboarding is successful when:
1. Client can sign up in < 1 minute
2. Database is ready in < 5 minutes
3. Client can complete setup in < 10 minutes
4. Client can make first sale within 1 hour
5. No manual intervention needed
6. Zero technical knowledge required

---

## 🚨 Edge Cases to Handle

### 1. Subdomain Already Taken
- **Solution:** Auto-increment (companyname1, companyname2, etc.)

### 2. Email Already Exists
- **Solution:** Show error, allow login instead

### 3. Invite Link Expired
- **Solution:** Admin can resend from dashboard

### 4. Database Creation Fails
- **Solution:** Retry 3 times, then notify admin

### 5. Client Doesn't Complete Setup
- **Solution:** Send reminder emails (Day 1, Day 3, Day 6)

### 6. Trial Expires Without Payment
- **Solution:** Suspend access, preserve data for 30 days

---

## 📞 Support Scenarios

### Client Says: "I didn't receive the email"
- **Check:** Spam folder
- **Action:** Resend invite from admin dashboard
- **Alternative:** Generate new invite link

### Client Says: "I forgot my password"
- **Action:** Use "Forgot Password" link
- **Flow:** Email → Reset link → New password

### Client Says: "I want to change my subdomain"
- **Action:** Manual update (for now)
- **Future:** Self-service subdomain change

### Client Says: "I need more time on trial"
- **Action:** Admin can extend trial (up to 30 days)
- **Reason:** Track why they need extension

---

## 🎓 Training Points for Support Team

### What to Tell Clients:
1. **"Just enter your email and company name"** → That's all we need
2. **"Check your email in 3-5 minutes"** → Setup is automatic
3. **"Click the link in the email"** → It will guide you through setup
4. **"You can skip steps and do them later"** → No pressure
5. **"Your data is completely isolated"** → Each client has own database

### What NOT to Say:
- ❌ "You need to set up your database" → It's automatic
- ❌ "You need technical knowledge" → It's guided
- ❌ "You need to pay first" → Trial is free
- ❌ "It takes hours to set up" → It's 5-10 minutes

---

## 🚀 Next Steps

1. **Review this flow** → Make sure it makes sense
2. **Identify gaps** → What's missing?
3. **Prioritize features** → What's essential vs. nice-to-have?
4. **Start building** → Begin with signup form
5. **Test end-to-end** → Try the full flow
6. **Iterate** → Improve based on feedback

---

**Ready to build? Let's start with the signup form!** 🎉
