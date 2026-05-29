#!/usr/bin/env python3
"""
Mini proxy server for Deezer API (handles CORS) + serves static files
"""
import http.server
import urllib.request
import urllib.parse
import json
import os

import os
PORT = int(os.environ.get('PORT', 8080))

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/deezer/'):
            self.proxy_deezer()
        else:
            super().do_GET()

    def proxy_deezer(self):
        # Strip /api/deezer/ prefix and forward to Deezer
        path = self.path[len('/api/deezer/'):]
        url = f"https://api.deezer.com/{path}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    def log_message(self, format, *args):
        # Quiet logs
        if '/api/deezer/' in (args[0] if args else ''):
            return
        super().log_message(format, *args)

if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"🎵 Rap Blind Test → http://localhost:{PORT}")
    with http.server.HTTPServer(('', PORT), Handler) as httpd:
        httpd.serve_forever()
