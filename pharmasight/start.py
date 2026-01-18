#!/usr/bin/env python3
"""
PharmaSight - Single Entry Point to Start Both Backend and Frontend
Run: python start.py
"""

import subprocess
import sys
import os
import time
import signal
from pathlib import Path

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    RESET = '\033[0m'

def print_colored(message, color=Colors.WHITE):
    """Print colored message"""
    print(f"{color}{message}{Colors.RESET}")

def check_requirements():
    """Check if all requirements are met"""
    project_root = Path(__file__).parent
    
    # Check virtual environment
    venv_python = project_root / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = project_root / "venv" / "bin" / "python"
    
    if not venv_python.exists():
        print_colored("❌ Virtual environment not found!", Colors.RED)
        print_colored("Please run: python -m venv venv", Colors.YELLOW)
        return False
    
    # Check .env file
    if not (project_root / ".env").exists():
        print_colored("❌ .env file not found!", Colors.RED)
        return False
    
    return True, project_root, venv_python

def start_backend(project_root, venv_python):
    """Start the FastAPI backend server"""
    print_colored("🔧 Starting Backend Server...", Colors.YELLOW)
    
    backend_dir = project_root / "backend"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir)
    
    # Start uvicorn server
    cmd = [
        str(venv_python),
        "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload"
    ]
    
    return subprocess.Popen(
        cmd,
        cwd=str(backend_dir),
        env=env,
        stdout=None,  # Show output in console
        stderr=subprocess.STDOUT  # Merge stderr with stdout
    )

def start_frontend(project_root):
    """Start the frontend HTTP server"""
    print_colored("🎨 Starting Frontend Server...", Colors.YELLOW)
    
    frontend_dir = project_root / "frontend"
    
    # Start Python HTTP server
    cmd = [
        sys.executable,
        "-m", "http.server",
        "3000"
    ]
    
    return subprocess.Popen(
        cmd,
        cwd=str(frontend_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

def main():
    """Main function to start both servers"""
    print_colored("🚀 Starting PharmaSight - Backend & Frontend", Colors.GREEN)
    print_colored("=" * 50, Colors.GREEN)
    print()
    
    # Check requirements
    result = check_requirements()
    if not result:
        sys.exit(1)
    
    if isinstance(result, tuple):
        success, project_root, venv_python = result
    else:
        success = result
        project_root = Path(__file__).parent
        venv_python = project_root / "venv" / "Scripts" / "python.exe"
    
    print_colored(f"📁 Project Directory: {project_root}", Colors.CYAN)
    print()
    
    processes = []
    
    try:
        # Start backend
        backend_process = start_backend(project_root, venv_python)
        processes.append(("Backend", backend_process))
        time.sleep(2)  # Give backend time to start
        
        # Start frontend
        frontend_process = start_frontend(project_root)
        processes.append(("Frontend", frontend_process))
        time.sleep(1)  # Give frontend time to start
        
        print()
        print_colored("✅ Both servers are running!", Colors.GREEN)
        print()
        print_colored("📍 URLs:", Colors.CYAN)
        print_colored("   Backend API:    http://localhost:8000", Colors.WHITE)
        print_colored("   API Docs:       http://localhost:8000/docs", Colors.WHITE)
        print_colored("   Health Check:   http://localhost:8000/health", Colors.WHITE)
        print_colored("   Frontend:       http://localhost:3000", Colors.WHITE)
        print()
        print_colored("💡 Press Ctrl+C to stop both servers", Colors.YELLOW)
        print()
        
        # Wait for processes (they run in background, so we'll monitor them)
        # In a real scenario, we'd want to see their output
        # For now, we'll just wait for interrupt
        try:
            while True:
                # Check if processes are still running
                for name, proc in processes:
                    if proc.poll() is not None:
                        print_colored(f"⚠️  {name} server stopped unexpectedly (exit code: {proc.returncode})", Colors.RED)
                        print_colored(f"   Check the error messages above", Colors.YELLOW)
                
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            print_colored("🛑 Stopping servers...", Colors.YELLOW)
            
            # Terminate all processes
            for name, proc in processes:
                if proc.poll() is None:  # Still running
                    print_colored(f"   Stopping {name}...", Colors.YELLOW)
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            
            print_colored("✅ All servers stopped", Colors.GREEN)
    
    except Exception as e:
        print_colored(f"❌ Error starting servers: {e}", Colors.RED)
        # Clean up on error
        for name, proc in processes:
            if proc.poll() is None:
                proc.terminate()
        sys.exit(1)

if __name__ == "__main__":
    main()

