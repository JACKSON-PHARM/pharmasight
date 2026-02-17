# SMTP Email Troubleshooting on Render

If invite emails are not being sent, follow these steps:

## 1. Check SMTP Configuration in Render

In **Render Dashboard** → Your service → **Environment**, verify these are set:

- ✅ **SMTP_HOST** (e.g. `smtp.gmail.com`, `smtp.sendgrid.net`)
- ✅ **SMTP_USER** (your email or API username)
- ✅ **SMTP_PASSWORD** (password or app password / API key)
- ✅ **SMTP_PORT** (usually `587` for TLS)
- ✅ **EMAIL_FROM** (e.g. `PharmaSight <noreply@yourdomain.com>`)

**Important:** All three (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`) must be set, or emails won't be sent.

---

## 2. Check Render Logs

After creating an invite, check **Render Dashboard** → Your service → **Logs**:

### If SMTP is NOT configured:
You'll see:
```
WARNING: SMTP not configured (missing: SMTP_HOST, SMTP_USER, SMTP_PASSWORD)
```

**Fix:** Add the missing environment variables in Render and redeploy.

### If SMTP IS configured:
You should see:
```
INFO: Invite created for user@example.com. Email sending queued in background task (SMTP configured).
INFO: Background task: Sending invite email to user@example.com for tenant...
```

Then either:
- ✅ `INFO: Background task: Successfully sent invite email to user@example.com` (email sent!)
- ❌ `WARNING: Background task: Failed to send invite email...` (check SMTP credentials or server)

---

## 3. Common SMTP Issues

### Gmail SMTP
- Use **App Password** (not your regular password)
- **SMTP_HOST**: `smtp.gmail.com`
- **SMTP_PORT**: `587`
- **SMTP_USER**: Your Gmail address
- **SMTP_PASSWORD**: App password (generate from Google Account → Security → 2-Step Verification → App passwords)

### SendGrid / Other Providers
- Use API key or SMTP credentials from your provider
- Check provider docs for correct `SMTP_HOST` and port

### Firewall / Network
- Render free tier may have network restrictions
- Some SMTP servers block connections from cloud providers
- Try a different SMTP provider if your current one blocks Render

---

## 4. Test SMTP Configuration

After setting env vars and redeploying:

1. Create a new invite for a tenant
2. Check Render logs immediately
3. Look for:
   - "SMTP configured" message → Good!
   - "SMTP not configured" → Add missing env vars
   - "Failed to send" → Check SMTP credentials or server

---

## 5. API Endpoint to Check SMTP Status

You can also check SMTP config via API:

```
GET https://pharmasight.onrender.com/api/admin/smtp-status
```

Returns:
```json
{
  "smtp_configured": true/false,
  "smtp_host_set": true/false,
  "smtp_user_set": true/false,
  "smtp_password_set": true/false,
  "smtp_port": 587,
  "email_from": "...",
  "message": "..."
}
```

---

## Quick Checklist

- [ ] `SMTP_HOST` is set in Render environment
- [ ] `SMTP_USER` is set in Render environment  
- [ ] `SMTP_PASSWORD` is set in Render environment
- [ ] Service has been redeployed after adding env vars
- [ ] Checked Render logs for SMTP errors
- [ ] SMTP credentials are correct (test with a simple email client if needed)
- [ ] SMTP server allows connections from Render (some providers block cloud IPs)
