# Frontend Setup Explanation

## 📁 Where is the Frontend?

The frontend is located in:
```
pharmasight/frontend/
├── index.html          # Main app (your pharmacy management system)
├── admin.html          # Admin dashboard (tenant management)
├── css/
├── js/
└── spa_server.py       # Standalone frontend server
```

---

## 🚀 Two Ways to Run the Application

### Option 1: Using `start.py` (Recommended for Development)

**What it does:**
- Starts **Backend** (FastAPI) on port **8000**
- Starts **Frontend** (separate server) on port **3000**

**How to use:**
```bash
python start.py
```

**Access:**
- Main App: `http://localhost:3000`
- Admin Dashboard: `http://localhost:3000/admin.html`
- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

**Why use this:**
- ✅ Separate frontend server (better for development)
- ✅ Hot reload for frontend changes
- ✅ Easier debugging

---

### Option 2: Using `uvicorn` Directly (What You Just Did)

**What it does:**
- Starts **Backend** (FastAPI) on port **8000**
- FastAPI **also serves the frontend** on the same port

**How to use:**
```bash
cd pharmasight/backend
python -m uvicorn app.main:app --reload
```

**Access:**
- Main App: `http://localhost:8000`
- Admin Dashboard: `http://localhost:8000/admin.html`
- API Docs: `http://localhost:8000/docs`

**Why use this:**
- ✅ Single port (simpler)
- ✅ Production-ready setup
- ✅ No separate frontend server needed

---

## 🔍 How FastAPI Serves the Frontend

Looking at `backend/app/main.py` (lines 74-86):

```python
# Serve frontend static files and SPA
if _FRONTEND_DIR.is_dir():
    app.mount("/css", StaticFiles(directory=str(_FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(_FRONTEND_DIR / "js")), name="js")
    _index_path = _FRONTEND_DIR / "index.html"

    @app.get("/")
    async def root():
        return FileResponse(_index_path, media_type="text/html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path:path):
        return FileResponse(_index_path, media_type="text/html")
```

**What this means:**
- FastAPI serves CSS files from `/css`
- FastAPI serves JS files from `/js`
- Root route (`/`) serves `index.html`
- All other routes serve `index.html` (SPA routing)
- **BUT** `admin.html` is accessible directly at `/admin.html`

---

## 📋 Summary

### Same Frontend, Different Serving Methods

| Method | Backend Port | Frontend Port | Frontend Served By |
|--------|-------------|---------------|-------------------|
| `start.py` | 8000 | 3000 | Separate Python server |
| `uvicorn` | 8000 | 8000 (same) | FastAPI static files |

### For Admin Dashboard

**Using `start.py`:**
```
http://localhost:3000/admin.html
```

**Using `uvicorn`:**
```
http://localhost:8000/admin.html
```

---

## ✅ Recommendation

**For Development:**
- Use `start.py` - easier debugging, separate servers

**For Production/Testing:**
- Use `uvicorn` directly - simpler, single port

**For Admin Dashboard:**
- Either method works!
- Just use the correct port (3000 for start.py, 8000 for uvicorn)

---

## 🎯 Quick Answer

**Q: Where is the frontend?**
A: `pharmasight/frontend/` - same frontend you've been using!

**Q: Is it the same as start.py?**
A: Yes! Same frontend files. `start.py` uses a separate server, `uvicorn` serves it directly.

**Q: How do I access admin dashboard?**
A: 
- With `start.py`: `http://localhost:3000/admin.html`
- With `uvicorn`: `http://localhost:8000/admin.html`

---

**Both methods work! Use whichever you prefer.** 🚀
