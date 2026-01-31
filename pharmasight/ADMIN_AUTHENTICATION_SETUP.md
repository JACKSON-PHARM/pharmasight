# Admin Authentication Setup

## 🎯 How It Works

When a user logs in, the system checks if they're an admin:

1. **Admin Login:**
   - Email: `admin` or `admin@pharmasight.com`
   - Password: `33742377.jack`
   - → Redirects to **Admin Panel** (`/admin.html`)

2. **Regular User Login:**
   - Any other email/password
   - → Redirects to **Main App** (normal PharmaSight)

---

## 🔐 Admin Credentials

**Username/Email:** `admin` (or `admin@pharmasight.com`)  
**Password:** `33742377.jack`

**Alternative Admin Email:** `pharmasightsolutions@gmail.com` (also works as admin)

---

## 🚀 How to Use

### Step 1: Login as Admin

1. Go to login page: `http://localhost:3000/#login`
2. Enter:
   - **Email:** `admin`
   - **Password:** `33742377.jack`
3. Click "Sign In"
4. **Automatically redirected to:** `http://localhost:3000/admin.html`

### Step 2: Login as Regular User

1. Go to login page: `http://localhost:3000/#login`
2. Enter regular user credentials
3. Click "Sign In"
4. **Automatically redirected to:** Main PharmaSight app (branch selection)

---

## 🔒 Security (Production)

### For Render/Production:

**Set environment variables:**

```bash
ADMIN_EMAIL=admin@pharmasight.com
ADMIN_PASSWORD=33742377.jack
```

**In Render Dashboard:**
1. Go to your service settings
2. Add environment variables:
   - `ADMIN_EMAIL` = `admin@pharmasight.com`
   - `ADMIN_PASSWORD` = `33742377.jack`

**Why this is secure:**
- Password stored in environment variable (not in code)
- Only accessible server-side
- Can be changed without code changes

---

## 📋 Implementation Details

### Backend (`admin_auth_service.py`)

- Checks if email is admin
- Validates password against environment variable
- Returns admin token for session

### Frontend (`login.js`)

- Detects admin login attempt
- Calls admin auth API
- Stores admin token in localStorage
- Redirects to `/admin.html` if admin

### Admin Panel (`admin.html`)

- Checks for admin token on load
- Redirects to login if not authenticated
- Allows access if admin token exists

---

## 🎨 User Experience

### Admin Login Flow:
```
1. User enters "admin" / "33742377.jack"
   ↓
2. System detects admin login
   ↓
3. Validates credentials
   ↓
4. Stores admin token
   ↓
5. Redirects to /admin.html
   ↓
6. Admin sees Tenant Management
```

### Regular User Login Flow:
```
1. User enters regular credentials
   ↓
2. System uses Supabase Auth
   ↓
3. Validates credentials
   ↓
4. Redirects to branch-select
   ↓
5. User sees normal PharmaSight app
```

---

## ✅ Testing

### Test Admin Login:
1. Go to: `http://localhost:3000/#login`
2. Email: `admin`
3. Password: `33742377.jack`
4. Should redirect to: `http://localhost:3000/admin.html`

### Test Regular Login:
1. Go to: `http://localhost:3000/#login`
2. Email: `your-regular-email@example.com`
3. Password: `your-password`
4. Should redirect to: `http://localhost:3000/#branch-select`

---

## 🔧 Configuration

### Change Admin Password:

**Development:**
- Edit `.env` file:
  ```
  ADMIN_PASSWORD=your-new-password
  ```

**Production (Render):**
- Update environment variable in Render dashboard
- No code changes needed!

### Add More Admin Users:

Edit `admin_auth_service.py`:
```python
admin_emails = [
    "admin@pharmasight.com",
    "admin",
    "pharmasightsolutions@gmail.com",
    "newadmin@example.com"  # Add here
]
```

---

## 🚨 Important Notes

1. **Admin credentials are separate from Supabase Auth**
   - Admin login bypasses Supabase
   - Uses simple password check
   - For production, consider JWT tokens

2. **Admin token is stored in localStorage**
   - Cleared on logout
   - Valid for session only
   - Not shared across tenants

3. **Works on Render:**
   - Set `ADMIN_PASSWORD` environment variable
   - Same code works everywhere
   - No hardcoded passwords in production

---

## 📝 Summary

**Admin Login:**
- Email: `admin`
- Password: `33742377.jack`
- → Redirects to Admin Panel

**Regular Login:**
- Any other credentials
- → Redirects to Main App

**Production:**
- Set `ADMIN_PASSWORD` environment variable
- Secure and configurable

---

**Ready to test?** Login with `admin` / `33742377.jack` and you'll be redirected to the admin panel! 🚀
