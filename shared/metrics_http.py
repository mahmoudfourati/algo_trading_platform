from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


_server: Optional[ThreadingHTTPServer] = None
_thread: Optional[threading.Thread] = None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return

        payload = generate_latest()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE_LATEST)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Avoid noisy HTTP logs; rely on structured audit logs elsewhere.
        return


def start_metrics_http_server(*, host: str = "0.0.0.0", port: int) -> None:
    """Start a tiny HTTP server that exposes Prometheus metrics at `/metrics`.

    This is intentionally minimal and dependency-free (beyond prometheus-client).
    """

    global _server, _thread

    if _server is not None:
        return

    httpd = ThreadingHTTPServer((host, int(port)), _Handler)
    t = threading.Thread(target=httpd.serve_forever, name="metrics-http", daemon=True)
    t.start()

    _server = httpd
    _thread = t
