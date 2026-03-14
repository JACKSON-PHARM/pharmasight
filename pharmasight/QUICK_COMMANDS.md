# Quick Command Reference

Copy and paste these commands (replace placeholders first).

## 🔧 Step 1: Configure Git

```bash
git config --global user.name "Your Name"
git config --global user.email "YOUR_GITHUB_EMAIL@example.com"
```

## 📦 Step 2: Initialize and Push to GitHub

```bash
# Navigate to project
cd pharmasight

# Initialize git
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit: PharmaSight pharmacy management system"

# Add remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/pharmasight.git

# Push to GitHub
git branch -M main
git push -u origin main
```

## 🗄️ Step 3: Supabase (One-Time Setup)

1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
2. Open `database/schema.sql`
3. Copy entire file
4. Paste in Supabase SQL Editor
5. Click **Run**

## 🚀 Step 4: Render Environment Variables

In Render dashboard → Your Service → Environment, add:

```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
DEBUG=False
SECRET_KEY=<generate-with-command-below>
CORS_ORIGINS=*
```

**Generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 🧪 Step 5: Test Locally (Optional)

```bash
# Terminal 1: Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Terminal 2: Frontend (optional)
cd frontend
python -m http.server 3000
```

Visit: http://localhost:8000/docs

## 📝 Important Notes

⚠️ **Replace these placeholders:**
- `YOUR_GITHUB_EMAIL@example.com` → Your actual GitHub email
- `YOUR_USERNAME` → Your GitHub username
- `<generate-with-command-below>` → Run the SECRET_KEY generation command

✅ **Security:**
- `.env` file is already in `.gitignore` (safe)
- Never commit passwords
- Use environment variables in Render

## 🔗 Your Connection String

```
postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
```

