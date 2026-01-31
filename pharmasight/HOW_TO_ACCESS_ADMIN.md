# How to Access the Admin Panel for Tenant Management

## 🎯 Quick Answer

The admin panel is a **separate HTML page** in the same frontend. You access it by going to:

```
http://localhost:3000/admin.html
```

**NOT** `http://localhost:3000` (that's the main app)

---

## 📋 Understanding the Setup

### Two Different Pages in Same Frontend

Your frontend has **two HTML files**:

1. **`index.html`** - Main PharmaSight app (pharmacy management)
   - URL: `http://localhost:3000`
   - What you're seeing now (Dashboard, Sales, Purchases, etc.)

2. **`admin.html`** - Admin dashboard (tenant management)
   - URL: `http://localhost:3000/admin.html`
   - This is what you need for managing clients/tenants

### Same Frontend, Different Pages

```
pharmasight/frontend/
├── index.html     ← Main app (what you see at localhost:3000)
├── admin.html     ← Admin panel (what you need at localhost:3000/admin.html)
├── css/
└── js/
```

---

## 🚀 How to Access Admin Panel

### Step 1: Make Sure Servers Are Running

You're using `start.py`, so you should see:
- ✅ Backend running on port 8000
- ✅ Frontend running on port 3000

### Step 2: Open Admin Panel in Browser

**Simply type in your browser:**
```
http://localhost:3000/admin.html
```

**OR click this link:**
[Open Admin Panel](http://localhost:3000/admin.html)

---

## 🔍 What You'll See

### Main App (`index.html`):
- Dashboard with sales, inventory, etc.
- Sidebar with: Dashboard, Sales, Purchases, Inventory, etc.
- This is for **using** PharmaSight

### Admin Panel (`admin.html`):
- Tenant Management interface
- List of all clients
- "Create New Tenant" button
- Search and filter options
- This is for **managing** clients

---

## ⚠️ Important: Fix Backend Error First

I see there's an error preventing the backend from starting properly:

```
IndentationError: unexpected indent
File: migration_service.py, line 219
```

**This needs to be fixed first** so the admin panel can load tenant data.

**Quick Fix:**
I've already fixed it in the code. Just restart your server:

1. Press `Ctrl+C` to stop
2. Run `python start.py` again
3. Backend should start without errors
4. Then access `http://localhost:3000/admin.html`

---

## 📊 Visual Guide

### Current Situation:
```
Browser: http://localhost:3000
         ↓
    index.html (Main App)
    - Dashboard
    - Sales
    - Purchases
    - etc.
```

### What You Need:
```
Browser: http://localhost:3000/admin.html
         ↓
    admin.html (Admin Panel)
    - Tenant Management
    - List of Clients
    - Create Tenant
    - etc.
```

---

## ✅ Step-by-Step Instructions

1. **Stop current server** (if running):
   - Press `Ctrl+C` in terminal

2. **Fix the backend error** (I've fixed it in code):
   - The IndentationError is now fixed

3. **Restart server**:
   ```bash
   python start.py
   ```

4. **Wait for both servers to start**:
   - Backend: `http://localhost:8000`
   - Frontend: `http://localhost:3000`

5. **Open admin panel**:
   - Go to: `http://localhost:3000/admin.html`
   - **NOT** `http://localhost:3000` (that's the main app)

---

## 🎯 Summary

**Q: Did we create a different start point?**
A: No! Same frontend, same server. Just a different HTML file (`admin.html` instead of `index.html`).

**Q: How do I access it?**
A: Go to `http://localhost:3000/admin.html` (add `/admin.html` to the URL)

**Q: Why can't I see it?**
A: You're probably at `http://localhost:3000` (main app). You need `http://localhost:3000/admin.html` (admin panel).

---

**Try it now:** Open `http://localhost:3000/admin.html` in your browser! 🚀
