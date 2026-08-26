"""T6/T7 — Fetch proxy + gate wiring contract (REQ-2, REQ-3, REQ-5).

Pins the proxy contract at the serving boundary:
  REQ-2 AC1: user-typed URL is fetched server-side and rendered.
  REQ-2 AC2: frame-blocking headers (X-Frame-Options, frame-ancestors) are
             stripped so the sandboxed panel iframe can render.
  REQ-2 AC3: relative refs anchored (<base>) so styles/images resolve.
  REQ-2 AC4: specific failures surfaced (status/reason), not a blank frame.
  REQ-3 AC4: served under the REQ-3 CSP; no permissive CORS to the app origin.
  REQ-3 AC5: credentials (Cookie/Authorization) never forwarded.
  REQ-5 AC1/AC2: egress guard runs on every hop — loopback/private refused,
             redirect-to-loopback refused.
  REQ-6/T7: gate closed => proxy refuses 403 BEFORE any fetch; gate open =>
             fetch proceeds. Module optional, DER unaffected.

No live web: upstream is a httpx.MockTransport serving canned HTML; the egress
guard still runs against the real resolver for hostname-class cases and against
literal IPs for loopback/private cases.
"""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.agent.tool_registry as tr
from backend.api.browser_surface import router
import backend.api.browser_auth as _ba

# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _gate_open():
    """Wire the internet gate open so the proxy is permitted (T7)."""
    tr.set_capability_providers(lambda: True, lambda: True)
    yield


# FIXTURE INPUT CHANGED — CALLED OUT EXPLICITLY (T15, 2026-08-24). No assertion
# in this file is touched and no test's load is reduced. This fixture built a
# bare app and called the proxy with NO surface credentials. Since the browser
# surface grew its two gates (backend/api/browser_auth.py:130 —
# `require_browser_surface_access`, wired at browser_surface.py:231), an
# unauthenticated request is refused with 404 BEFORE `fetch_proxy` runs, so
# every assertion in this file was measuring the auth refusal rather than the
# proxy contract it was written to pin. That silently included the REQ-5 egress
# guard cases (loopback / private / redirect-to-loopback) and the REQ-6 gate
# -closed 403 — security assertions that were reaching nothing. Verified
# pre-existing: fails identically on a clean HEAD worktree.
# The client now presents what a real local caller presents — a loopback peer
# and a valid surface token — matching the PASSING suite
# backend/tests/contract/test_browser_surface_auth.py. The auth gate stays under
# test there; here it is a precondition, not the subject.
_SURFACE_TOKEN = "test-token-surface-fixture"


@pytest.fixture()
def client(monkeypatch):
    # Starlette's default peer is the literal string "testclient", which the
    # address gate correctly refuses (an unparseable peer is not loopback), so a
    # real loopback address is presented. The token rides as a default header on
    # every request, so no call site below changes.
    monkeypatch.setenv("IRIS_BROWSER_SURFACE_TOKEN", _SURFACE_TOKEN)
    _ba.reset_token_cache_for_tests()
    app = FastAPI()
    app.include_router(router)
    with TestClient(
        app,
        client=("127.0.0.1", 50000),
        headers={_ba.HEADER_NAME: _SURFACE_TOKEN},
    ) as c:
        yield c
    _ba.reset_token_cache_for_tests()


def _mock_proxy(url: str, html: str = "<html><head><title>t</title></head><body>ok</body></html>"):
    """Run the proxy endpoint against a MockTransport serving `html`."""
    from backend.proxy import fetch_client as fc

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/html",
                "X-Frame-Options": "DENY",           # must be stripped (AC2)
                "Content-Security-Policy": "frame-ancestors 'none'",  # stripped
                "Set-Cookie": "session=evil; Path=/",  # must never reach panel
            },
            content=html.encode("utf-8"),
        )

    transport = httpx.MockTransport(handler)
    # Point the module-level transport used by the endpoint's fetch at the mock.
    fc._DEFAULT_TRANSPORT_FACTORY = lambda: transport  # type: ignore[attr-defined]
    yield
    fc._DEFAULT_TRANSPORT_FACTORY = None  # type: ignore[attr-defined]


# ── REQ-2 AC1/AC2/AC3: render, scrub, anchor ────────────────────────────────


def test_proxy_renders_and_scrubs_and_anchors(client, monkeypatch):
    """A proxied page renders (200), frame-blocking headers are stripped, and
    relative refs are anchored with <base>."""
    from backend.proxy import fetch_client as fc

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/html",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "frame-ancestors 'none'",
            },
            content=b'<html><head><link rel="stylesheet" href="/app.css"></head><body>hi</body></html>',
        )

    monkeypatch.setattr(fc, "_DEFAULT_TRANSPORT_FACTORY", lambda: httpx.MockTransport(handler))
    r = client.get("/api/browser/proxy", params={"url": "https://example.com/story"})
    assert r.status_code == 200
    # AC2: frame-blocking headers gone.
    assert "x-frame-options" not in r.headers
    assert "content-security-policy" in r.headers  # replaced by ours (AC4)
    # AC3: relative ref anchored.
    assert '<base href="https://example.com/story">' in r.text
    # AC5: no credential headers were sent upstream.
    for k in ("cookie", "authorization"):
        assert k not in captured["headers"], f"credential header forwarded: {k}"


def test_proxy_specific_failure_surfaced(client, monkeypatch):
    """REQ-2 AC4: an upstream 404 surfaces its status, not a blank frame."""
    from backend.proxy import fetch_client as fc

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"Content-Type": "text/html"}, content=b"not found")

    monkeypatch.setattr(fc, "_DEFAULT_TRANSPORT_FACTORY", lambda: httpx.MockTransport(handler))
    r = client.get("/api/browser/proxy", params={"url": "https://example.com/missing"})
    assert r.status_code == 404
    assert "X-Proxy-Error" in r.headers


def test_proxy_refuses_loopback_target(client):
    """REQ-5 AC1: loopback target refused before any fetch."""
    r = client.get("/api/browser/proxy", params={"url": "http://127.0.0.1:9000/admin"})
    assert r.status_code == 502
    assert "refused (loopback)" in r.text


def test_proxy_refuses_private_target(client):
    """REQ-5 AC1: private (RFC1918) target refused."""
    r = client.get("/api/browser/proxy", params={"url": "http://192.168.1.1/admin"})
    assert r.status_code == 502
    assert "refused (private)" in r.text


def test_proxy_refuses_bad_scheme(client):
    """REQ-5 AC3: non-http(s) scheme refused."""
    r = client.get("/api/browser/proxy", params={"url": "file:///etc/passwd"})
    assert r.status_code == 502
    assert "refused (scheme)" in r.text


def test_proxy_refuses_redirect_to_loopback(client, monkeypatch):
    """REQ-5 AC2: a public page redirecting to 127.0.0.1 is refused at the hop.

    The initial URL resolves public (real resolver); the redirect Location is a
    literal loopback — per-hop re-check must refuse it (T4). If the per-hop
    check were removed, the fetch would follow to the loopback and return 200.
    """
    from backend.proxy import fetch_client as fc

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1:9000/private"},
            content=b"",
        )

    monkeypatch.setattr(fc, "_DEFAULT_TRANSPORT_FACTORY", lambda: httpx.MockTransport(handler))
    r = client.get("/api/browser/proxy", params={"url": "https://example.com/start"})
    assert r.status_code == 502
    assert "refused (loopback)" in r.text


def test_proxy_csp_and_null_cors(client, monkeypatch):
    """REQ-3 AC4 + T7: served under our CSP; no permissive CORS to app origin."""
    from backend.proxy import fetch_client as fc

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<html>ok</html>")

    monkeypatch.setattr(fc, "_DEFAULT_TRANSPORT_FACTORY", lambda: httpx.MockTransport(handler))
    r = client.get("/api/browser/proxy", params={"url": "https://example.com/"})
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    # ASSERTION CORRECTED (T15, 2026-08-24): this said `script-src 'none'`,
    # which is one of the three directives browser_surface.py:44-59 documents as
    # LOAD-BEARING IN THE OPPOSITE DIRECTION — `script-src 'none'` stops the
    # injected view-agent from ever running, so no scroll/ready message reaches
    # the parent and REQ-4 is dead. That was a shipped bug, and
    # backend/tests/contract/test_browser_surface_headers.py exists to pin the
    # fix (it passes today). This assertion was pinning the defect. It now pins
    # the fixed contract, and is STRICTER than a bare presence check: the
    # directive must exist, must not be 'none', and must be nonce-based rather
    # than a blanket allow.
    _script = [d for d in csp.split(";") if d.strip().startswith("script-src")]
    assert _script, f"script-src must be present, got {csp!r}"
    _script = _script[0]
    assert "'none'" not in _script, (
        f"script-src 'none' kills the injected view-agent (REQ-4). Got {_script!r}"
    )
    assert "nonce-" in _script, (
        f"script-src must be nonce-scoped, not a blanket allow. Got {_script!r}"
    )
    assert "'unsafe-eval'" not in _script and "*" not in _script
    # ASSERTION CORRECTED (T15, 2026-08-24): this required
    # `Access-Control-Allow-Origin: null`, calling it "the ONLY legitimate CORS
    # value here". That is the third shipped bug of this family: "null" IS the
    # opaque origin a sandboxed document presents, so sending it grants read
    # access to precisely the reader the sandbox exists to exclude
    # (browser_surface.py:108-111). The correct value is NO header at all, which
    # is what the code now does and what the passing guard
    # backend/tests/contract/test_browser_surface_headers.py:103
    # (`test_no_cors_header_at_all`) pins. This assertion was requiring the
    # vulnerability. It now pins the fix, and is STRICTER: no access-control-*
    # header of ANY kind may be present, not merely a constrained origin value.
    assert not [k for k in r.headers if k.lower().startswith("access-control-")], (
        f"no CORS grant may be issued to the sandboxed reader. Got {dict(r.headers)!r}"
    )


# ── REQ-6/T7: gate wiring ───────────────────────────────────────────────────


def test_proxy_refused_when_gate_closed(client, monkeypatch):
    """REQ-6/T7: with the internet gate closed, the proxy refuses 403 BEFORE
    any fetch happens — the module is optional and cannot be reached."""
    tr.set_capability_providers(lambda: False, lambda: True)
    from backend.proxy import fetch_client as fc

    hit = []

    async def handler(request: httpx.Request) -> httpx.Response:
        hit.append(request.url)
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<html>ok</html>")

    monkeypatch.setattr(fc, "_DEFAULT_TRANSPORT_FACTORY", lambda: httpx.MockTransport(handler))
    r = client.get("/api/browser/proxy", params={"url": "https://example.com/"})
    assert r.status_code == 403
    assert "internet" in r.text.lower()
    assert hit == [], "a fetch happened while the gate was closed"
