"""API model calls keep one connection pool per base URL (2026-10-27).

Measured: ApiHttpxTransport built a new httpx.Client per call, so every model
call paid a TCP + TLS handshake - against api.inceptionlabs.ai a median 86 ms
(max 1.9 s, a stalled handshake that set off a hedge) vs 23 ms on a kept
connection, ~30 calls in a coding turn. Each call still builds its own Client
(its own timeouts) over the shared transport; closing it must not close the pool.

Driven against a local HTTP/1.1 server that counts TCP connections.
"""
from __future__ import annotations

import ast
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from backend.agent.inference import transport as tr

_TRANSPORT = Path(tr.__file__)


class _Counting(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # keep-alive
    peers: set = set()

    def do_POST(self):  # noqa: N802
        _Counting.peers.add(self.client_address)
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_two_calls_reuse_one_connection_after_each_client_closes():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Counting)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    _Counting.peers = set()
    try:
        for _ in range(3):   # one Client per call, closed each time - as the transport does
            with httpx.Client(timeout=5, transport=tr._api_transport(base)) as c:
                assert c.post(base + "/v1/chat/completions", json={}).status_code == 200
        assert len(_Counting.peers) == 1, _Counting.peers       # one TCP connection for 3 calls
        assert tr._api_transport(base) is tr._api_transport(base)  # one pool per base URL
    finally:
        srv.shutdown()


def test_every_api_client_rides_the_kept_pool():
    """Both ApiHttpxTransport clients (stream, non-stream) pass transport=_api_transport(...)."""
    tree = ast.parse(_TRANSPORT.read_text(encoding="utf-8", errors="replace"))
    api = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ApiHttpxTransport")
    clients = [n for n in ast.walk(api)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "Client"]
    assert len(clients) == 2, [c.lineno for c in clients]
    for c in clients:
        kw = {k.arg: k.value for k in c.keywords}
        assert isinstance(kw.get("transport"), ast.Call) and getattr(kw["transport"].func, "id", "") == "_api_transport", c.lineno
