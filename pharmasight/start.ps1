# PharmaSight - Start Both Backend and Frontend Servers
# This script starts both the FastAPI backend and the frontend HTTP server

Write-Host "🚀 Starting PharmaSight - Backend & Frontend" -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Green
Write-Host ""

# Check if virtual environment exists
if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "❌ Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please run: python -m venv venv" -ForegroundColor Yellow
    Write-Host "Then: .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "Then: pip install -r backend/requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "❌ .env file not found!" -ForegroundColor Red
    Write-Host "Please create .env file with your database credentials" -ForegroundColor Yellow
    exit 1
}

# Get the current directory
$projectRoot = $PSScriptRoot
if (-not $projectRoot) {
    $projectRoot = Get-Location
}

Write-Host "📁 Project Directory: $projectRoot" -ForegroundColor Cyan
Write-Host ""

# Function to start backend
function Start-Backend {
    Write-Host "🔧 Starting Backend Server..." -ForegroundColor Yellow
    
    $backendScript = @"
cd '$projectRoot'
`$env:PYTHONPATH = '$projectRoot\backend'
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
"@
    
    # Create a temporary PowerShell script for backend
    $backendTempScript = Join-Path $env:TEMP "pharmasight_backend.ps1"
    $backendScript | Out-File -FilePath $backendTempScript -Encoding UTF8
    
    # Start backend in a new window
    Start-Process powershell.exe -ArgumentList "-NoExit", "-File", $backendTempScript
}

# Function to start frontend
function Start-Frontend {
    Write-Host "🎨 Starting Frontend Server (SPA routing enabled)..." -ForegroundColor Yellow
    
    $frontendScript = @"
cd '$projectRoot\frontend'
python spa_server.py 3000
pause
"@
    
    # Create a temporary PowerShell script for frontend
    $frontendTempScript = Join-Path $env:TEMP "pharmasight_frontend.ps1"
    $frontendScript | Out-File -FilePath $frontendTempScript -Encoding UTF8
    
    # Start frontend in a new window
    Start-Process powershell.exe -ArgumentList "-NoExit", "-File", $frontendTempScript
}

# Start both servers
Start-Backend
Start-Sleep -Seconds 2
Start-Frontend

Write-Host ""
Write-Host "✅ Both servers are starting in separate windows!" -ForegroundColor Green
Write-Host ""
Write-Host "📍 URLs:" -ForegroundColor Cyan
Write-Host "   Backend API:    http://localhost:8000" -ForegroundColor White
Write-Host "   API Docs:       http://localhost:8000/docs" -ForegroundColor White
Write-Host "   Health Check:   http://localhost:8000/health" -ForegroundColor White
Write-Host "   Frontend:       http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "💡 Tip: Close the PowerShell windows to stop the servers" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to exit this script (servers will continue running)..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

