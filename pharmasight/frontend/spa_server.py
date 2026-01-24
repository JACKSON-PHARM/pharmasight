#!/usr/bin/env python3
"""
Minimal SPA-enabled HTTP server
Serves index.html for all routes that don't match actual files
"""

import http.server
import socketserver
import os
from pathlib import Path

class SPAHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves index.html for SPA routes"""
    
    # Explicit MIME type mappings to ensure correct Content-Type
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.js': 'application/javascript',
        '.mjs': 'application/javascript',
        '.css': 'text/css',
        '.html': 'text/html',
    }
    
    def guess_type(self, path):
        """Override to use our explicit MIME type mappings"""
        ext = ''
        i = path.rfind('.')
        if i != -1:
            ext = path[i:].lower()
        return self.extensions_map.get(ext, 'application/octet-stream')
    
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_GET(self):
        # Parse path (remove query string and fragment)
        parsed_path = self.path.split('?')[0].split('#')[0]
        
        # Log JavaScript file requests for debugging
        if parsed_path.endswith('.js'):
            print(f"[Frontend] JS Request: {self.path} -> {parsed_path}")
            file_path = Path(parsed_path.lstrip('/'))
            print(f"[Frontend] File exists: {file_path.is_file()}, Full path: {file_path.absolute()}")
        
        # If root, serve index.html
        if parsed_path == '/':
            if os.path.exists('index.html'):
                self.path = '/index.html'
            super().do_GET()
            return
        
        # Check if requested path is an actual file
        file_path = Path(parsed_path.lstrip('/'))
        if file_path.is_file():
            # It's a real file, serve it
            super().do_GET()
        else:
            # Not a file, serve index.html for SPA routing
            if os.path.exists('index.html'):
                self.path = '/index.html'
            super().do_GET()
    
    def log_message(self, format, *args):
        """Cleaner log format"""
        print(f"[Frontend] {args[0]}")

def run(port=3000):
    """Run the SPA-enabled HTTP server"""
    # Change to the script's directory
    os.chdir(Path(__file__).parent)
    
    handler = SPAHandler
    
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"[Frontend] SPA server running on http://localhost:{port}")
        print(f"[Frontend] Serving directory: {os.getcwd()}")
        print(f"[Frontend] All routes serve index.html (SPA routing enabled)")
        print(f"[Frontend] Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[Frontend] Server stopped")

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    run(port=port)
