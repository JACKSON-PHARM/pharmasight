# PLATFORM_ADMIN Impersonation

Platform admins can temporarily act as a company user for troubleshooting. Impersonation is **audited**, **short-lived**, and **does not change company isolation**.

---

## Backend

### Endpoints (PLATFORM_ADMIN only)

- **POST /api/admin/impersonate/{company_id}**  
  Start impersonating a user in the given company. The backend picks an active user with access to that company (prefers admin role).  
  - **Auth:** `Authorization: Bearer <admin_token>` (from `POST /api/admin/auth/login`).  
  - **Body (optional):** `{ "reason": "Troubleshooting invoice export" }`.  
  - **Response:** `{ "access_token", "expires_in_minutes", "impersonation": true, "user_id", "company_id", "email", "message" }`.

- **POST /api/admin/impersonate-user/{user_id}**  
  Start impersonating a specific user.  
  - **Auth:** same admin token.  
  - **Body (optional):** `{ "reason": "..." }`.  
  - **Response:** same shape.

Rate limit: **5 requests per minute per IP** for both.

### Token usage

- Use the returned `access_token` as a normal user JWT:  
  `Authorization: Bearer <access_token>` on **main app** API calls (e.g. company frontend).
- The token expires in **15 minutes**. There is no refresh; request a new impersonation to continue.
- The token has the same claims as a normal access token (`sub`, `email`, `company_id`, etc.) so:
  - `get_current_user` resolves to the **impersonated user**.
  - Company isolation is unchanged (user can only see their company’s data).
- Extra claims for the frontend:
  - `impersonation`: `true`
  - `impersonated_by`: admin session identifier (for audit).

### Audit log

Every impersonation is written to **`admin_impersonation_log`** (migration `070_admin_impersonation_log.sql`):

- `admin_identifier`, `company_id`, `user_id`, `started_at`, `client_ip`, `reason`, optional `ended_at`.

---

## Frontend: using the token and showing the banner

### 1. Getting an impersonation token (admin UI)

From the **admin** app (where you are already logged in as PLATFORM_ADMIN):

```javascript
// After admin login you have adminToken.
const companyId = "uuid-of-company";
const res = await fetch("/api/admin/impersonate/" + companyId, {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${adminToken}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ reason: "Troubleshooting export" }),
});
const { access_token, expires_in_minutes, email, company_id } = await res.json();
// Store access_token for the main app (e.g. sessionStorage or pass to another tab).
```

### 2. Using the token in the main app

In the **main (company) app**, use this token for all API calls instead of the normal user token:

```javascript
// Use the impersonation token as the main app’s auth token.
const IMPERSONATION_TOKEN_KEY = "pharmasight_impersonation_token";
sessionStorage.setItem(IMPERSONATION_TOKEN_KEY, access_token);
// Then use it in fetch:
const token = sessionStorage.getItem(IMPERSONATION_TOKEN_KEY);
fetch("/api/items/company/" + company_id + "/overview", {
  headers: { "Authorization": `Bearer ${token}` },
});
```

### 3. Showing the “Admin impersonation” banner

Decode the JWT payload (no need to verify; it’s from your backend) and check `impersonation`:

```javascript
function parseJwtPayload(token) {
  try {
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(base64))));
  } catch {
    return null;
  }
}

function isImpersonationSession(token) {
  const payload = parseJwtPayload(token);
  return payload && payload.impersonation === true;
}

// In your app shell / layout:
const token = sessionStorage.getItem("pharmasight_impersonation_token") || getNormalUserToken();
if (isImpersonationSession(token)) {
  // Show a fixed banner at the top (e.g. red or orange).
  showBanner("You are viewing as a company user (Admin impersonation). Do not perform sensitive actions.");
}
```

Banner requirements:

- Visible on every page while the impersonation token is in use.
- Clearly state that the session is an **admin impersonation**.
- Optionally show “End session” that clears the token and returns to admin or login.

### 4. Ending impersonation

- Clear the stored impersonation token and switch back to normal login or admin.
- The backend does not issue a “stop impersonation” endpoint; when the token expires (15 min) or is discarded, the session effectively ends.

---

## Security

- **PLATFORM_ADMIN only:** Both endpoints use `get_current_admin`; company users cannot call them.
- **No privilege escalation:** The JWT has the same permissions as the impersonated user.
- **Company isolation:** Unchanged; all existing `company_id` / `effective_company_id` checks apply.
- **Audit:** Every start is logged with admin identifier, company, user, IP, and optional reason.
- **Short-lived:** 15-minute expiry; no refresh token for impersonation.
