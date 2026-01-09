# GitHub Setup Instructions

## 🔧 Step-by-Step GitHub Setup

### 1. Configure Git (First Time Only)

Open terminal/command prompt in the `pharmasight` folder and run:

```bash
# Set your name (replace with your actual name)
git config --global user.name "Your Name"

# Set your email (REPLACE WITH YOUR GITHUB EMAIL)
git config --global user.email "your-email@example.com"
```

**Important**: Use the email associated with your GitHub account.

### 2. Initialize Git Repository

```bash
# Make sure you're in the pharmasight folder
cd pharmasight

# Initialize git
git init
```

### 3. Check What Will Be Committed

```bash
# This shows all files that will be added
git status

# IMPORTANT: Make sure .env is NOT listed (it should be ignored)
# If .env shows up, DO NOT commit it!
```

### 4. Add Files to Git

```bash
# Add all files (except those in .gitignore)
git add .
```

### 5. Make Your First Commit

```bash
git commit -m "Initial commit: PharmaSight pharmacy management system

- Complete database schema with inventory ledger
- FastAPI backend with full CRUD operations
- Modern frontend with POS, GRN, and inventory management
- Breaking bulk support with FEFO allocation
- KRA-compliant invoicing
- Cost-based pricing engine"
```

### 6. Create Repository on GitHub

1. Go to: https://github.com/new
2. **Repository name**: `pharmasight` (or your preferred name)
3. **Description**: `Pharmacy Management System with Inventory Intelligence`
4. **Visibility**: 
   - Choose **Private** (recommended - keeps your code and credentials safe)
   - Or **Public** (if you want to share)
5. **DO NOT** check any boxes (no README, .gitignore, or license - we already have these)
6. Click **Create repository**

### 7. Connect and Push to GitHub

After creating the repo, GitHub will show you commands. Here they are:

```bash
# Add GitHub as remote (replace YOUR_USERNAME with your actual GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/pharmasight.git

# If you prefer SSH (after setting up SSH keys):
# git remote add origin git@github.com:YOUR_USERNAME/pharmasight.git

# Rename branch to main (if needed)
git branch -M main

# Push to GitHub
git push -u origin main
```

### 8. Authentication

When you run `git push`, you'll be asked for credentials:

**Option A: Personal Access Token (Recommended)**
1. Go to: https://github.com/settings/tokens
2. Click **Generate new token** → **Generate new token (classic)**
3. Give it a name: `pharmasight-deploy`
4. Select scope: `repo` (check the box)
5. Click **Generate token**
6. **Copy the token** (you won't see it again!)
7. When git asks for password, paste the token

**Option B: GitHub CLI**
```bash
# Install GitHub CLI, then:
gh auth login
git push -u origin main
```

### 9. Verify Push

1. Go to your GitHub repository: `https://github.com/YOUR_USERNAME/pharmasight`
2. You should see all your files
3. ✅ Success!

## 🔒 Security Checklist

Before pushing, verify:

- [ ] `.env` file is NOT in the repository (check with `git status`)
- [ ] `.env` is in `.gitignore` (already done ✅)
- [ ] No passwords in code files
- [ ] Database password only in `.env.example` (with placeholder)
- [ ] Repository is Private (recommended)

## 📝 Quick Reference

**Your Supabase Details** (keep these safe):
- Project ID: `kwvkkbofubsjiwqlqakt`
- Password: `6iP.zRY6QyK8L*Z`
- Connection: `postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres`

**Never commit these to GitHub!**

## 🆘 Troubleshooting

### "Permission denied" error
- Check your GitHub username is correct
- Use Personal Access Token instead of password
- Verify email matches GitHub account

### ".env file is tracked"
If `.env` accidentally gets committed:
```bash
# Remove from git tracking (keeps file locally)
git rm --cached .env
git commit -m "Remove .env from tracking"
git push
```

### "Repository not found"
- Check repository name matches
- Verify you have access to the repo
- Check username is correct

## ✅ Next Steps After GitHub Push

1. ✅ Code is on GitHub
2. ⏭️ Next: Deploy to Render (see DEPLOYMENT.md)
3. ⏭️ Or: Set up Supabase (see DEPLOYMENT.md)

