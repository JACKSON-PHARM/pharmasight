# Tenant Invite Email

When you create an invite from the admin panel, the system **sends the invite link to the tenant's admin email** so they can join from their inbox.

**Sender:** `pharmasightsolutions@gmail.com` (wired via Gmail SMTP in `.env`).  
**Recipient:** The tenant’s **admin email** (set at tenant creation). Future flows (website signup, social, etc.) will also provide the user email.

## Setup (SMTP)

To enable email sending, set these in your `.env`:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=PharmaSight <your-email@gmail.com>
APP_PUBLIC_URL=https://your-app.pharmasight.com
```

- **Gmail:** Use an [App Password](https://support.google.com/accounts/answer/185833), not your normal password.
- **APP_PUBLIC_URL:** Base URL of your frontend (used in the invite link). Use `http://localhost:3000` for local dev.

If SMTP is not configured, invites still work: the link is shown in the modal and you can copy it to share manually. The UI will indicate that email was not sent.
