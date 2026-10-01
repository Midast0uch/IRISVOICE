"""Every transport HTTP client reuses the shared TLS context (2026-10-01).

Measured (coding eval, in-process stack dumps): OllamaTransport.generate built
`httpx.Client(timeout=...)` with no `verify=`, so httpx created a new
ssl.create_default_context() - a Windows cert-store read - on EVERY Brain
call: 14 dumps (~56 s) of one eval turn. The other four transports already
passed `verify=get_ssl_context()` (the process-wide context).
"""
from __future__ import annotations

import ast
from pathlib import Path

_TRANSPORT = Path(__file__).resolve().parents[2] / "agent" / "inference" / "transport.py"


def test_every_client_passes_the_shared_context():
    tree = ast.parse(_TRANSPORT.read_text(encoding="utf-8", errors="replace"))
    clients = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Client"
    ]
    assert clients, "no httpx.Client construction found - update this guard"
    missing = [
        c.lineno for c in clients
        if not any(
            k.arg == "verify" and isinstance(k.value, ast.Call)
            and getattr(k.value.func, "id", "") == "get_ssl_context"
            for k in c.keywords
        )
    ]
    assert not missing, f"httpx.Client without verify=get_ssl_context() at lines {missing}"
