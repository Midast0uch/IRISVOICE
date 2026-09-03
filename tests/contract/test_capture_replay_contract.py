"""T5 — Capture replay store + endpoint contract (REQ-1).

Pins the REQ-1 contract at the serving boundary:
  AC1: captured HTML available keyed by job_id + page_number.
  AC2: rendered from the capture — the endpoint issues NO network request.
  AC3: missing capture => explicit "capture unavailable" (404), never a live
       fallback.
  AC4: provenance (url, fetched_at, job_id) in the served headers.
  AC5: bounded retention (count + bytes) with oldest-first eviction, and
       eviction never fails an in-flight task (save() never raises).

The store is isolated to a temp dir; the endpoint is exercised through
FastAPI's TestClient. No live web anywhere in this test.
"""

import os
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api.browser_surface import router
import os as _os_surface  # noqa: F401 (env for the surface token)
import backend.api.browser_auth as _ba

_SURFACE_TOKEN = "test-token-surface-fixture"


# FIXTURE INPUT CHANGED — CALLED OUT EXPLICITLY (T15, 2026-08-24). No assertion
# in this file is touched and no test's load is reduced. These tests build a bare
# app and called the endpoints with NO surface credentials. Since the browser
# surface grew its two gates (backend/api/browser_auth.py:130 —
# `require_browser_surface_access`, wired at browser_surface.py:132/:231), an
# unauthenticated request is refused with 404 BEFORE the handler runs, so every
# assertion below was measuring the auth refusal instead of the behavior it was
# written to pin — including the SSRF/egress guard cases and the gate-closed 403.
# Verified pre-existing: fails identically on a clean HEAD worktree.
# The client now presents what a real local caller presents — a loopback peer and
# a valid surface token — which is exactly the fixture the PASSING suite
# backend/tests/contract/test_browser_surface_auth.py already uses. The auth gate
# itself stays under test there; here it is a precondition, not the subject.
def _surface_client(app):
    """TestClient that satisfies BOTH browser-surface gates.

    Starlette's default peer is the literal string "testclient", which the
    address gate correctly refuses (an unparseable peer is not loopback), so a
    real loopback address is presented. The token rides as a default header on
    every request, so no call site below changes.
    """
    _os_surface.environ["IRIS_BROWSER_SURFACE_TOKEN"] = _SURFACE_TOKEN
    _ba.reset_token_cache_for_tests()
    return TestClient(
        app,
        client=("127.0.0.1", 50000),
        headers={_ba.HEADER_NAME: _SURFACE_TOKEN},
    )


from backend.crawler import capture_store as cs
from backend.crawler.capture_store import (
    MAX_CAPTURE_BYTES,
    MAX_CAPTURE_PAGES,
    CaptureStore,
)


def _make_isolated_store():
    root = tempfile.mkdtemp(prefix="capture_test_")
    store = CaptureStore(root=root)
    # Swap the module singleton so the endpoint reads the same isolated store.
    cs._store = store
    return store


def _app() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return _surface_client(app)


# ── AC1/AC2: served from capture, keyed by job_id+page_number ──────────────


def test_replay_serves_captured_bytes_with_provenance():
    store = _make_isolated_store()
    store.save("job_a", 1, "https://example.com", "<html><body>hello</body></html>")
    c = _app()
    r = c.get("/api/browser/capture/job_a/1")
    assert r.status_code == 200
    # REQ-1 AC2: the served bytes ARE the captured bytes (never a live fetch).
    # Since T9 landed, the endpoint also injects the view-agent (REQ-4 AC1) so
    # the sandboxed frame can speak OUT. The transformation is exact and
    # deterministic: captured bytes split at </body>, view-agent inserted, rest
    # untouched. (Assertion updated when T9 made injection part of the contract.)
    assert r.text.startswith("<html><body>hello")
    assert r.text.endswith("</body></html>")
    assert "__iris_view_agent_v1__" in r.text
    assert r.text.count("hello") == 1
    # AC4 provenance in panel chrome.
    assert r.headers.get("x-capture-url") == "https://example.com"
    assert r.headers.get("x-capture-job-id") == "job_a"
    assert r.headers.get("x-capture-page-number") == "1"
    assert r.headers.get("x-capture-status") == "available"
    assert r.headers.get("x-capture-fetched-at")


def test_replay_missing_capture_is_explicit_404_never_live_fallback():
    store = _make_isolated_store()
    store.save("job_a", 1, "https://example.com", "<html>one</html>")
    c = _app()
    r = c.get("/api/browser/capture/job_a/2")  # exists as 1, not 2
    assert r.status_code == 404
    assert r.text == "capture unavailable"
    assert r.headers.get("x-capture-status") == "unavailable"


def test_replay_unknown_job_is_404():
    _make_isolated_store()
    c = _app()
    r = c.get("/api/browser/capture/never_existed/1")
    assert r.status_code == 404
    assert r.text == "capture unavailable"


# ── REQ-3 AC4: served content carries CSP + no permissive CORS ─────────────


def test_replay_response_carries_csp_and_null_cors():
    store = _make_isolated_store()
    store.save("job_c", 1, "https://example.com", "<html>csp</html>")
    c = _app()
    r = c.get("/api/browser/capture/job_c/1")
    assert "Content-Security-Policy" in r.headers
    csp = r.headers["content-security-policy"]
    assert "connect-src 'none'" in csp
    # ASSERTION CORRECTED (T15, 2026-08-24): this said `frame-ancestors 'none'`,
    # which is X-Frame-Options: DENY by another name — it makes every served
    # page UNFRAMEABLE, the exact failure this feature exists to fix
    # (browser_surface.py:51-54). That was a shipped bug, and
    # backend/tests/contract/test_browser_surface_headers.py:45 pins the fix
    # ("frame-ancestors must not be 'none' — that is the bug this file pins")
    # and passes today. This assertion was pinning the defect. It now pins the
    # fixed contract, and is STRICTER than the old one in the direction that
    # matters: the directive must be present (an OMITTED frame-ancestors allows
    # ANY embedder) and must not be a wildcard.
    _fa = [d for d in csp.split(";") if d.strip().startswith("frame-ancestors")]
    assert _fa, f"frame-ancestors must be present — omitting it allows any embedder. Got {csp!r}"
    _fa = _fa[0]
    assert "'none'" not in _fa, (
        f"frame-ancestors 'none' makes the capture unframeable by the panel. Got {_fa!r}"
    )
    assert "'self'" in _fa, f"the app itself must be able to frame it. Got {_fa!r}"
    assert "*" not in _fa, f"never a wildcard embedder. Got {_fa!r}"
    # ASSERTION CORRECTED (T15, 2026-08-24): required
    # `Access-Control-Allow-Origin: null`. "null" IS the opaque origin a
    # sandboxed document presents, so sending it grants read access to exactly
    # the reader the sandbox excludes (browser_surface.py:108-111). The correct
    # value is NO header, pinned by the passing guard
    # backend/tests/contract/test_browser_surface_headers.py:103. This
    # assertion was requiring the vulnerability; it now pins the fix and is
    # STRICTER — no access-control-* header of any kind.
    assert not [k for k in r.headers if k.lower().startswith("access-control-")], (
        f"no CORS grant may be issued to the sandboxed reader. Got {dict(r.headers)!r}"
    )


# ── AC5: bounded retention + oldest-first eviction ─────────────────────────


def test_eviction_enforces_page_count_bound():
    store = _make_isolated_store()
    for i in range(MAX_CAPTURE_PAGES + 5):
        ok = store.save("job_evict", i + 1, f"https://u{i}.example", "<html>x</html>")
        assert ok is True  # save never fails even while evicting (AC5)
    assert store.stats()["pages"] <= MAX_CAPTURE_PAGES
    # Oldest-first: page 1 gone, newest present.
    assert store.load("job_evict", 1) is None
    assert store.load("job_evict", MAX_CAPTURE_PAGES + 5) is not None


def test_eviction_enforces_byte_bound():
    store = _make_isolated_store()
    # Each page ~ (MAX_CAPTURE_BYTES / 5 + 1) bytes => 5 pages exceed the bound.
    chunk = "x" * (MAX_CAPTURE_BYTES // 5 + 1)
    for i in range(5):
        store.save("job_bytes", i + 1, f"https://b{i}.example", chunk)
    assert store.stats()["bytes"] <= MAX_CAPTURE_BYTES
    assert store.load("job_bytes", 1) is None  # oldest evicted
    assert store.load("job_bytes", 5) is not None


def test_save_never_raises_on_bad_input():
    store = _make_isolated_store()
    # Empty html -> False, no raise.
    assert store.save("job_bad", 1, "https://x.example", "") is False
    # Path traversal attempts are sanitized, not an error.
    assert store.save("../evil", 1, "https://x.example", "<html>y</html>") is True
    # And nothing escaped the store root.
    parent = os.path.dirname(store._root)
    assert not os.path.exists(os.path.join(parent, "evil"))
