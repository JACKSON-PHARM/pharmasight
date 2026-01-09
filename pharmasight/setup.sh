#!/bin/bash
# PharmaSight Quick Setup Script

echo "🚀 PharmaSight Setup Script"
echo "============================"
echo ""

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed. Please install Git first."
    exit 1
fi

# Check if we're in the right directory
if [ ! -f "backend/app/main.py" ]; then
    echo "❌ Please run this script from the pharmasight root directory"
    exit 1
fi

echo "📦 Step 1: Initializing Git repository..."
if [ ! -d ".git" ]; then
    git init
    echo "✅ Git repository initialized"
else
    echo "✅ Git repository already exists"
fi

echo ""
echo "📝 Step 2: Configuring Git..."
read -p "Enter your name for Git commits: " git_name
read -p "Enter your GitHub email: " git_email

git config user.name "$git_name"
git config user.email "$git_email"

echo "✅ Git configured: $git_name <$git_email>"

echo ""
echo "🔍 Step 3: Checking files..."
if [ -f ".env" ]; then
    echo "⚠️  Warning: .env file exists. Make sure it's in .gitignore"
    if ! grep -q "^\.env$" .gitignore; then
        echo ".env" >> .gitignore
        echo "✅ Added .env to .gitignore"
    fi
else
    echo "✅ No .env file (safe to commit)"
fi

echo ""
echo "📋 Step 4: Checking what will be committed..."
git add .
git status

echo ""
read -p "Do you want to commit these files? (y/n): " commit_confirm

if [ "$commit_confirm" = "y" ] || [ "$commit_confirm" = "Y" ]; then
    git commit -m "Initial commit: PharmaSight pharmacy management system"
    echo "✅ Files committed"
    
    echo ""
    read -p "Do you want to push to GitHub now? (y/n): " push_confirm
    
    if [ "$push_confirm" = "y" ] || [ "$push_confirm" = "Y" ]; then
        read -p "Enter your GitHub username: " github_username
        read -p "Enter repository name (default: pharmasight): " repo_name
        repo_name=${repo_name:-pharmasight}
        
        git remote add origin "https://github.com/$github_username/$repo_name.git" 2>/dev/null
        git branch -M main
        git push -u origin main
        
        echo ""
        echo "✅ Setup complete!"
        echo "📝 Next steps:"
        echo "   1. Set up Supabase (see DEPLOYMENT.md)"
        echo "   2. Deploy to Render (see DEPLOYMENT.md)"
    else
        echo ""
        echo "✅ Committed locally. Push manually when ready:"
        echo "   git remote add origin https://github.com/YOUR_USERNAME/pharmasight.git"
        echo "   git push -u origin main"
    fi
else
    echo "⏭️  Skipped commit. Run 'git add .' and 'git commit' manually when ready."
fi

echo ""
echo "🎉 Setup script complete!"

