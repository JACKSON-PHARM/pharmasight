# Quick script to restart backend only
Write-Host "🛑 Stopping backend processes..." -ForegroundColor Yellow

# Find and stop Python processes using port 8000
$processes = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $processes) {
    try {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "   Stopped process $procId" -ForegroundColor Green
    } catch {
        Write-Host "   Could not stop process $procId" -ForegroundColor Yellow
    }
}

Start-Sleep -Seconds 2

Write-Host "🚀 Starting backend server..." -ForegroundColor Green

$projectRoot = "C:\PharmaSight\pharmasight"
$env:PYTHONPATH = "$projectRoot\backend"

cd "$projectRoot\backend"

# Start backend in a new window
Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", "cd '$projectRoot'; `$env:PYTHONPATH = '$projectRoot\backend'; .\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

Write-Host "✅ Backend starting in new window..." -ForegroundColor Green
Write-Host "📍 Check the new window for any errors" -ForegroundColor Cyan
Write-Host "📍 Test: http://localhost:8000/health" -ForegroundColor Cyan

