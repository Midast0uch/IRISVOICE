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
    return TestClient(app)


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
    assert "frame-ancestors 'none'" in csp
    # Never permissive toward the app origin (T7).
    assert r.headers.get("access-control-allow-origin") == "null"


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
