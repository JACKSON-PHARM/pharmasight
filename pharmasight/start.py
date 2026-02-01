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

def start_backend(project_root, venv_python, port=8000):
    """Start the FastAPI backend server"""
    print_colored("🔧 Starting Backend Server...", Colors.YELLOW)
    
    backend_dir = project_root / "backend"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir)
    
    # Check if port is in use and try to free it (Windows WinError 10013)
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    if result == 0:
        print_colored(f"⚠️  Port {port} is in use. Attempting to free it...", Colors.YELLOW)
        try:
            import subprocess as sp
            netstat = sp.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in netstat.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        try:
                            sp.run(['taskkill', '/F', '/PID', pid], capture_output=True, check=True)
                            print_colored(f"✅ Freed port {port} (killed process {pid})", Colors.GREEN)
                            time.sleep(2)
                            break
                        except Exception:
                            pass
            # If still in use, try alternate port
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if sock2.connect_ex(('127.0.0.1', port)) == 0:
                sock2.close()
                port = 8001
                print_colored(f"⚠️  Using alternate port {port}. Set API base URL to http://localhost:{port} if needed.", Colors.YELLOW)
            else:
                sock2.close()
        except Exception as e:
            print_colored(f"⚠️  Could not free port {port}: {e}. Trying port 8001...", Colors.YELLOW)
            port = 8001
    
    # Start uvicorn server
    cmd = [
        str(venv_python),
        "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--reload"
    ]
    
    proc = subprocess.Popen(
        cmd,
        cwd=str(backend_dir),
        env=env,
        stdout=None,  # Show output in console
        stderr=subprocess.STDOUT  # Merge stderr with stdout
    )
    return proc, port


def start_frontend(project_root, port=3000):
    """Start the frontend HTTP server with SPA routing"""
    print_colored("🎨 Starting Frontend Server (SPA routing enabled)...", Colors.YELLOW)
    
    frontend_dir = project_root / "frontend"
    spa_server = frontend_dir / "spa_server.py"
    
    # Check if port is in use and try to free it
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    
    if result == 0:
        # Port is in use, try to find and kill the process
        print_colored(f"⚠️  Port {port} is in use. Attempting to free it...", Colors.YELLOW)
        try:
            import subprocess as sp
            # Find process using the port (Windows)
            result = sp.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        try:
                            sp.run(['taskkill', '/F', '/PID', pid], capture_output=True)
                            print_colored(f"✅ Freed port {port} (killed process {pid})", Colors.GREEN)
                            time.sleep(1)  # Wait a moment for port to be released
                        except:
                            pass
        except:
            print_colored(f"⚠️  Could not free port {port}. Trying alternative port 3001...", Colors.YELLOW)
            port = 3001
    
    # Start SPA-enabled HTTP server
    cmd = [
        sys.executable,
        str(spa_server),
        str(port)
    ]
    
    # IMPORTANT: Do NOT capture stdout/stderr here.
    # We want any errors (e.g. port in use, syntax errors) to be visible
    # directly in the console, otherwise start.py only shows an exit code.
    return subprocess.Popen(
        cmd,
        cwd=str(frontend_dir),
        stdout=None,              # Show frontend logs in the main console
        stderr=subprocess.STDOUT  # Merge stderr with stdout
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
        backend_process, backend_port = start_backend(project_root, venv_python)
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
        print_colored(f"   Backend API:    http://localhost:{backend_port}", Colors.WHITE)
        print_colored(f"   API Docs:       http://localhost:{backend_port}/docs", Colors.WHITE)
        print_colored(f"   Health Check:   http://localhost:{backend_port}/health", Colors.WHITE)
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

