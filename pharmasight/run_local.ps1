# PharmaSight Local Development Startup Script
# Run this script to start the backend server

Write-Host "🚀 Starting PharmaSight Backend Server..." -ForegroundColor Green
Write-Host ""

# Activate virtual environment
if (Test-Path "venv\Scripts\Activate.ps1") {
    & "venv\Scripts\Activate.ps1"
    Write-Host "✅ Virtual environment activated" -ForegroundColor Green
} else {
    Write-Host "❌ Virtual environment not found. Please run: python -m venv venv" -ForegroundColor Red
    exit 1
}

# Set PYTHONPATH
$env:PYTHONPATH = "$PWD\backend"

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "❌ .env file not found. Please create it first." -ForegroundColor Red
    exit 1
}

Write-Host "✅ Configuration files found" -ForegroundColor Green
Write-Host ""
Write-Host "📡 Starting FastAPI server on http://localhost:8000" -ForegroundColor Cyan
Write-Host "📚 API Documentation: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "🔍 Health Check: http://localhost:8000/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Start the server
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

