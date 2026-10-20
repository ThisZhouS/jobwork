"""Tiny one-shot localhost sink: receives a POST body and writes it to a file.

Used only to move cookie data from the GUI browser into the scraper process
without printing credentials into the chat log.
"""
import http.server
import pathlib
import socketserver
import sys

TARGET = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".state/bridge.txt")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765


class Handler(http.server.BaseHTTPRequestHandler):
    def _save(self, length: int) -> None:
        body = self.rfile.read(length)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_bytes(body)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        self._save(int(self.headers.get("Content-Length", 0)))

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, *args):
        pass


with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"listening on {PORT} -> {TARGET}", flush=True)
    httpd.handle_request()
print("done", flush=True)
