#!/usr/bin/env python3
"""
PharmaSight - Single Entry Point to Start Both Backend and Frontend
Run: python start.py
"""

import json
import subprocess
from subprocess import Popen
import sys
import os
import time
import signal
from pathlib import Path
from typing import Optional, Tuple

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
    # Some environments (Windows cmd/PowerShell) may default to cp1252, which
    # can't encode emoji/special symbols used in the startup banner.
    # Strip non-ASCII characters to avoid UnicodeEncodeError.
    try:
        safe_message = message.encode("ascii", errors="ignore").decode("ascii")
    except Exception:
        safe_message = str(message)
    print(f"{color}{safe_message}{Colors.RESET}")

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
    
    # Start uvicorn server (use RELOAD=0 to disable reload and avoid file-watcher shutdown noise)
    use_reload = os.environ.get("RELOAD", "1").strip().lower() not in ("0", "false", "no")
    cmd = [
        str(venv_python),
        "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ]
    if use_reload:
        cmd.append("--reload")
    
    proc = subprocess.Popen(
        cmd,
        cwd=str(backend_dir),
        env=env,
        stdout=None,  # Show output in console
        stderr=subprocess.STDOUT  # Merge stderr with stdout
    )
    return proc, port


def write_frontend_runtime_config(project_root: Path, backend_port: int) -> None:
    """
    Write active backend URL so the SPA (frontend/js/config.js) uses the same port as uvicorn
    (e.g. 8001 when 8000 is still occupied after taskkill attempts).
    """
    path = project_root / "frontend" / "js" / "runtime_config.json"
    data = {"apiBaseUrl": f"http://localhost:{backend_port}"}
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print_colored(f"   Wrote {path.name} -> {data['apiBaseUrl']}", Colors.CYAN)
    except Exception as e:
        print_colored(f"   Could not write runtime_config.json: {e}", Colors.YELLOW)


def _find_bindable_port_on_loopback(start: int, span: int) -> Optional[int]:
    """Pick first TCP port we can bind on 127.0.0.1 (avoids WinError 10013 on some Windows setups)."""
    import socket
    for p in range(start, start + span):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            try:
                s.close()
            except Exception:
                pass
    return None


def _resolve_frontend_port_preference() -> int:
    """Preferred start port: FRONTEND_PORT env, else 3000."""
    raw = os.environ.get("FRONTEND_PORT", "").strip()
    if raw.isdigit():
        p = int(raw)
        if 1 <= p <= 65535:
            return p
    return 3000


def start_frontend(project_root, preferred_port: Optional[int] = None) -> Tuple[Optional[Popen], Optional[int]]:
    """Start the frontend HTTP server with SPA routing. Returns (process, port) or (None, None)."""
    print_colored("🎨 Starting Frontend Server (SPA routing enabled)...", Colors.YELLOW)

    frontend_dir = project_root / "frontend"
    spa_server = frontend_dir / "spa_server.py"

    if preferred_port is None:
        preferred_port = _resolve_frontend_port_preference()

    # Scan primary range then fallback (many dev machines have 3000-3024 busy from other tools).
    primary_span = int(os.environ.get("FRONTEND_PORT_SPAN", "100").strip() or "100")
    primary_span = max(1, min(primary_span, 500))
    port = _find_bindable_port_on_loopback(preferred_port, primary_span)
    if port is None:
        fb_start = 3100 if preferred_port < 3100 else preferred_port + primary_span
        if fb_start > 65000:
            fb_start = 4000
        port = _find_bindable_port_on_loopback(fb_start, primary_span)
    if port is None:
        print_colored(
            f"❌ No free port for frontend on 127.0.0.1 (tried {preferred_port}-{preferred_port + primary_span - 1} "
            f"and {fb_start}-{fb_start + primary_span - 1}).",
            Colors.RED,
        )
        print_colored(
            "   Set FRONTEND_PORT to a free port, or close apps using those ports (e.g. other dev servers).",
            Colors.YELLOW,
        )
        return None, None
    if port != preferred_port:
        print_colored(
            f"⚠️  Using port {port} (preferred {preferred_port} was busy or blocked).",
            Colors.YELLOW,
        )

    cmd = [sys.executable, str(spa_server), str(port)]

    proc = subprocess.Popen(
        cmd,
        cwd=str(frontend_dir),
        stdout=None,
        stderr=subprocess.STDOUT,
    )
    return proc, port

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
        write_frontend_runtime_config(project_root, backend_port)
        time.sleep(2)  # Give backend time to start
        
        # Start frontend
        frontend_process, frontend_port = start_frontend(project_root)
        if frontend_process is not None:
            processes.append(("Frontend", frontend_process))
        time.sleep(1)  # Give frontend time to start

        print()
        if frontend_process is None or (frontend_process.poll() is not None):
            print_colored("⚠️  Backend is running; frontend failed to start (see errors above).", Colors.YELLOW)
        else:
            print_colored("✅ Both servers are running!", Colors.GREEN)
        print()
        print_colored("📍 URLs:", Colors.CYAN)
        print_colored(f"   Backend API:    http://localhost:{backend_port}", Colors.WHITE)
        print_colored(f"   API Docs:       http://localhost:{backend_port}/docs", Colors.WHITE)
        print_colored(f"   Health Check:   http://localhost:{backend_port}/health", Colors.WHITE)
        if frontend_port is not None:
            print_colored(f"   Frontend:       http://127.0.0.1:{frontend_port}", Colors.WHITE)
        else:
            print_colored("   Frontend:       (not started)", Colors.WHITE)
        print()
        print_colored("💡 Press Ctrl+C to stop both servers", Colors.YELLOW)
        print()
        
        # Wait for processes (they run in background, so we'll monitor them)
        # In a real scenario, we'd want to see their output
        # For now, we'll just wait for interrupt
        try:
            logged_stopped = set()
            while True:
                # Check if processes are still running
                for name, proc in processes:
                    if proc.poll() is not None and name not in logged_stopped:
                        logged_stopped.add(name)
                        print_colored(
                            f"⚠️  {name} server stopped unexpectedly (exit code: {proc.returncode})",
                            Colors.RED,
                        )
                        print_colored("   Check the error messages above", Colors.YELLOW)

                time.sleep(1)
        except KeyboardInterrupt:
            print()
            print_colored("🛑 Stopping servers...", Colors.YELLOW)
            
            # Terminate all processes (backend may log CancelledError on exit — that's normal)
            for name, proc in processes:
                if proc.poll() is None:  # Still running
                    print_colored(f"   Stopping {name}...", Colors.YELLOW)
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            
            print_colored("✅ All servers stopped", Colors.GREEN)
            print_colored("   (Backend may have printed CancelledError on exit — that's normal when stopping.)", Colors.CYAN)
    
    except Exception as e:
        print_colored(f"❌ Error starting servers: {e}", Colors.RED)
        # Clean up on error
        for name, proc in processes:
            if proc.poll() is None:
                proc.terminate()
        sys.exit(1)

if __name__ == "__main__":
    main()

