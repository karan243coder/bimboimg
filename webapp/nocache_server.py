#!/usr/bin/env python3
"""PixelFree dev server — browser ko kabhi cache nahi karne deta.
Usage: python3 nocache_server.py [port]"""
import sys, http.server, socketserver

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        # needed for WebGPU/WASM multithreading
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'credentialless')
        super().end_headers()
    def log_message(self, fmt, *a):
        print(f"  {fmt % a}")

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), H) as httpd:
    print(f"\n  PixelFree running →  http://localhost:{PORT}\n  (no-cache mode · Ctrl+C to stop)\n")
    httpd.serve_forever()
