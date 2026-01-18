# 🚀 How to Run the Startup Scripts

## Quick Answer

You're currently in `C:\PharmaSight`, but the startup files are in `C:\PharmaSight\pharmasight\`

### ✅ Correct Way to Run:

```powershell
# Step 1: Navigate to the pharmasight folder
cd C:\PharmaSight\pharmasight

# Step 2: Run the batch file (choose one method below)
```

## Three Ways to Run:

### Method 1: From PowerShell/CMD (Recommended)
```powershell
cd C:\PharmaSight\pharmasight
.\start.bat
```
**OR simply:**
```powershell
cd C:\PharmaSight\pharmasight
start.bat
```

### Method 2: Double-Click in Windows Explorer
1. Open File Explorer (Windows + E)
2. Navigate to: `C:\PharmaSight\pharmasight`
3. Find `start.bat`
4. **Double-click it**
5. Two command windows will open (one for backend, one for frontend)

### Method 3: Use Full Path
```powershell
C:\PharmaSight\pharmasight\start.bat
```

## ❌ What NOT to Do:

```powershell
# ❌ WRONG - Don't use python to run .bat files
python start.bat

# ❌ WRONG - Don't try to execute from wrong directory
cd C:\PharmaSight
.\start.bat  # File not found!
```

## 📝 Alternative: Use PowerShell Script

If you prefer PowerShell:
```powershell
cd C:\PharmaSight\pharmasight
.\start.ps1
```

If you get an execution policy error, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\start.ps1
```

## 🐍 Or Use Python Script

If you prefer Python:
```powershell
cd C:\PharmaSight\pharmasight
python start.py
```

## 📍 Summary

- **File location**: `C:\PharmaSight\pharmasight\start.bat`
- **Current location**: `C:\PharmaSight` (you need to `cd` into `pharmasight` first)
- **Best method**: `cd pharmasight` then `.\start.bat` or just double-click in File Explorer

## 🎯 Quick Command:

```powershell
cd C:\PharmaSight\pharmasight; .\start.bat
```

