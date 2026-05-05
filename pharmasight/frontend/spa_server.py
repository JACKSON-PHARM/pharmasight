#!/usr/bin/env python3
"""
Local dev HTTP server: mirrors production URL split from main.py.
  /              → public marketing homepage (../marketing/index.html) when present
  /marketing/*   → static files from ../marketing/
  /app, /app/*   → ERP SPA (index.html); assets /css, /js still from frontend/
"""

import errno
import http.server
import socketserver
import os
import sys
from pathlib import Path
from typing import Optional


def _safe_wfile_write(handler: http.server.BaseHTTPRequestHandler, data: bytes) -> None:
    """Ignore broken-client writes (tab closed, navigation away). Avoids WinError 10053 noise."""
    try:
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        pass
    except OSError as exc:
        winerr = getattr(exc, "winerror", None)
        if winerr == 10053:  # WSAECONNABORTED
            return
        if exc.errno in (errno.EPIPE, errno.ECONNRESET):
            return
        raise


class _ReusableTCPServer(socketserver.TCPServer):
    """Avoid TIME_WAIT bind failures on quick restarts; use on local dev only."""

    allow_reuse_address = True


FRONTEND_ROOT = Path(__file__).resolve().parent
MARKETING_ROOT = FRONTEND_ROOT.parent / "marketing"


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    """Serve marketing at /, ERP SPA at /app, static assets from frontend or marketing."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".html": "text/html",
        ".json": "application/json",
    }

    def guess_type(self, path):
        ext = ""
        i = path.rfind(".")
        if i != -1:
            ext = path[i:].lower()
        return self.extensions_map.get(ext, "application/octet-stream")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def _parsed_path(self) -> str:
        return self.path.split("?")[0].split("#")[0]

    def _under_marketing(self, resolved: Path) -> bool:
        try:
            resolved.relative_to(MARKETING_ROOT.resolve())
            return True
        except ValueError:
            return False

    def _send_bytes(self, full_path: Path, content_type: Optional[str] = None) -> None:
        try:
            data = full_path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        ctype = content_type or self.guess_type(full_path.name)
        self.send_response(200)
        self.send_header("Content-type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        _safe_wfile_write(self, data)

    def _send_head_file(self, full_path: Path) -> None:
        try:
            n = full_path.stat().st_size
        except OSError:
            self.send_error(404)
            return
        ctype = self.guess_type(full_path.name)
        self.send_response(200)
        self.send_header("Content-type", ctype)
        self.send_header("Content-Length", str(n))
        self.end_headers()

    def _marketing_response(self, parsed: str, head: bool) -> bool:
        """Handle GET/HEAD under /marketing/*. Return False if path is not marketing."""
        if not parsed.startswith("/marketing"):
            return False
        if not MARKETING_ROOT.is_dir():
            self.send_error(404)
            return True
        rel = parsed[len("/marketing") :].lstrip("/")
        if not rel:
            candidate = MARKETING_ROOT / "index.html"
            if candidate.is_file():
                if head:
                    self._send_head_file(candidate)
                else:
                    self._send_bytes(candidate)
                return True
            self.send_error(404)
            return True
        candidate = (MARKETING_ROOT / rel).resolve()
        if not self._under_marketing(candidate):
            self.send_error(403)
            return True
        if candidate.is_file():
            if head:
                self._send_head_file(candidate)
            else:
                self._send_bytes(candidate)
            return True
        self.send_error(404)
        return True

    def do_GET(self):
        os.chdir(FRONTEND_ROOT)
        parsed = self._parsed_path()

        # Public homepage (same as backend production)
        if parsed in ("/", ""):
            mi = MARKETING_ROOT / "index.html"
            if mi.is_file():
                self._send_bytes(mi)
                return
            self.path = "/index.html"
            super().do_GET()
            return

        # Bundled marketing CSS/JS/HTML under /marketing/
        if self._marketing_response(parsed, head=False):
            return

        # ERP SPA shell (production uses /app)
        if parsed == "/app" or parsed.startswith("/app/"):
            self.path = "/index.html"
            super().do_GET()
            return

        # Existing frontend static file
        file_path = Path(parsed.lstrip("/"))
        if parsed.endswith(".js"):
            print(f"[Frontend] JS Request: {self.path} -> {parsed}")
            print(f"[Frontend] File exists: {file_path.is_file()}, Full path: {(FRONTEND_ROOT / file_path).resolve()}")

        if file_path.is_file():
            super().do_GET()
            return

        # SPA fallback for deep links (legacy dev URLs without /app)
        if Path("index.html").is_file():
            self.path = "/index.html"
            super().do_GET()
            return

        self.send_error(404)

    def do_HEAD(self):
        """Minimal HEAD support for marketing and SPA entry."""
        os.chdir(FRONTEND_ROOT)
        parsed = self._parsed_path()
        if parsed in ("/", ""):
            mi = MARKETING_ROOT / "index.html"
            if mi.is_file():
                self._send_head_file(mi)
                return
            idx = FRONTEND_ROOT / "index.html"
            if idx.is_file():
                self._send_head_file(idx)
                return
            self.send_error(404)
            return
        if self._marketing_response(parsed, head=True):
            return
        if parsed == "/app" or parsed.startswith("/app/"):
            idx = FRONTEND_ROOT / "index.html"
            if idx.is_file():
                self._send_head_file(idx)
                return
            self.send_error(404)
            return
        file_path = Path(parsed.lstrip("/"))
        if file_path.is_file():
            self.path = parsed
            super().do_HEAD()
            return
        idx = FRONTEND_ROOT / "index.html"
        if idx.is_file():
            self._send_head_file(idx)
            return
        self.send_error(404)

    def log_message(self, format, *args):
        print(f"[Frontend] {args[0]}")


def run(port=3000):
    os.chdir(FRONTEND_ROOT)

    handler = SPAHandler
    host = "127.0.0.1"
    preferred = int(port)
    candidates = [preferred] + [p for p in range(3000, 3025) if p != preferred]
    httpd = None
    bound_port = None
    last_err = None
    for p in candidates:
        try:
            httpd = _ReusableTCPServer((host, p), handler)
            bound_port = p
            break
        except OSError as e:
            last_err = e
            continue
    if httpd is None:
        print(
            f"[Frontend] Could not bind SPA server on {host} (tried {len(candidates)} ports): {last_err}",
            file=sys.stderr,
        )
        sys.exit(1)
    if bound_port != preferred:
        print(
            f"[Frontend] Port {preferred} unavailable; using {bound_port} instead.",
            file=sys.stderr,
        )
    with httpd:
        print(f"[Frontend] SPA server running on http://127.0.0.1:{bound_port}")
        print(f"[Frontend] Frontend dir: {FRONTEND_ROOT}")
        print(f"[Frontend] Marketing root: {MARKETING_ROOT} (exists={MARKETING_ROOT.is_dir()})")
        print(f"[Frontend] URLs: / → marketing home | /app → ERP | /css /js → frontend assets")
        print(f"[Frontend] Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[Frontend] Server stopped")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    run(port=port)
