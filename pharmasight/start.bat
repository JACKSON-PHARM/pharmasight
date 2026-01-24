@echo off
REM PharmaSight - Start Both Backend and Frontend Servers (Windows Batch)
REM This is a simple batch file that starts both servers in separate windows

echo.
echo ============================================
echo   PharmaSight - Starting Backend ^& Frontend
echo ============================================
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then: venv\Scripts\activate
    echo Then: pip install -r backend\requirements.txt
    pause
    exit /b 1
)

REM Check if .env exists
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Please create .env file with your database credentials
    pause
    exit /b 1
)

echo [INFO] Starting Backend Server on http://localhost:8000
start "PharmaSight Backend" cmd /k "cd /d %~dp0 && set PYTHONPATH=%~dp0backend && venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 /nobreak >nul

echo [INFO] Starting Frontend Server on http://localhost:3000 (SPA routing enabled)
start "PharmaSight Frontend" cmd /k "cd /d %~dp0frontend && python spa_server.py 3000"

echo.
echo ============================================
echo   ✅ Both servers are starting!
echo ============================================
echo.
echo   Backend API:    http://localhost:8000
echo   API Docs:       http://localhost:8000/docs
echo   Health Check:   http://localhost:8000/health
echo   Frontend:       http://localhost:3000
echo.
echo   💡 Close the command windows to stop the servers
echo.
pause

