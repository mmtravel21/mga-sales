"""public/ 폴더를 HTTP로 serving. AI 에이전트가 직접 fetch 할 수 있는 endpoint."""
import http.server
import socketserver
import sys
from pathlib import Path

# Windows cp949 콘솔 호환
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PORT = 8502
HERE = Path(__file__).parent.parent
DIRECTORY = HERE / "public"
DIRECTORY.mkdir(exist_ok=True)


class CorsHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"[STATIC] Server starting on http://0.0.0.0:{PORT}")
    print(f"[STATIC] Directory: {DIRECTORY}")
    with socketserver.TCPServer(("0.0.0.0", PORT), CorsHandler) as httpd:
        httpd.serve_forever()
