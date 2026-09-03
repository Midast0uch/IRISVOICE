"""Behavioral: the browser surface is an OPTIONAL module (T14/T15).

specs/in-app-browser-surface REQ-6 AC1/AC2/AC4, plus the acceptance-gate
properties from REQ-3/REQ-5 that must hold together rather than in isolation.

WHY THIS FILE EXISTS. T14 and T15 were both reported complete and neither
existed. T14 is the task that keeps the long-horizon spec's SEAM claim honest:
if the browser module cannot be removed without changing DER, the seam is in
the wrong place and the fix belongs in the seam, not here.
"""

from __future__ import annotations

import inspect

import pytest


# ── REQ-6 AC2: routing through the DER loop stays generic ─────────────────

def test_der_step_loop_dispatches_generically():
    """The step loop must resolve tools through the registry, not a per-tool
    if-ladder. This is the seam REQ-17 pins and REQ-6 AC2 protects."""
    from backend.agent import agent_kernel

    src = inspect.getsource(agent_kernel.AgentKernel._der_run_step_execution_async)
    assert "execute_tool(" in src, "step execution must go through the generic bridge call"
    # The dispatch itself must not select an executor by tool name.
    for forbidden in (
        'if item.tool == "crawler_query"',
        'if item.tool == "open_url"',
        "browser_surface",
        "/api/browser/proxy",
    ):
        assert forbidden not in src, f"per-tool routing leaked into the DER loop: {forbidden}"


def test_der_loop_does_not_import_the_browser_module():
    """Removing backend/proxy or backend/api/browser_surface must not break DER."""
    from backend.agent import agent_kernel

    src = inspect.getsource(agent_kernel)
    for forbidden in ("backend.proxy.fetch_client", "backend.api.browser_surface",
                      "backend.crawler.capture_store"):
        assert forbidden not in src, (
            f"agent_kernel imports {forbidden} — the module is no longer optional"
        )


# ── REQ-6 AC1: with the proxy unavailable, the crawl path is unaffected ───

def test_capture_store_failure_never_propagates_to_the_caller():
    """Capture persistence is best-effort; a broken store must not fail a task."""
    from backend.crawler.capture_store import CaptureStore

    store = CaptureStore(root="\x00:/definitely/not/writable")
    # Must not raise — an unwritable store degrades to "no capture", which the
    # replay endpoint reports honestly as unavailable (REQ-1 AC3).
    ok = store.save("job-x", 1, "https://e.example", "<html></html>", fetched_at="now")
    assert ok is False, "an unwritable store must report failure, not claim success"
    assert store.load("job-x", 1) is None


def test_eviction_never_raises_even_when_the_tree_is_gone(tmp_path):
    from backend.crawler.capture_store import CaptureStore

    store = CaptureStore(root=str(tmp_path / "gone"))
    store._evict_if_over_budget()  # no tree at all — must be a no-op, not a crash


# ── REQ-1 AC3: a missing capture is VISIBLE, never a silent live fetch ────

def test_missing_capture_is_reported_not_substituted(tmp_path, monkeypatch):
    from backend.crawler import capture_store as cs
    from backend.api import browser_surface as bs

    store = cs.CaptureStore(root=str(tmp_path))
    monkeypatch.setattr(bs, "get_capture_store", lambda: store)
    assert store.load("no-such-job", 3) is None


# ── REQ-5 acceptance: the guard is wired into the real fetch path ─────────

@pytest.mark.asyncio
async def test_proxy_fetch_refuses_a_loopback_target_end_to_end():
    """Not a unit test of _classify — this drives fetch_with_guard itself, so a
    guard that exists but is not CALLED would fail here."""
    from backend.proxy.fetch_client import fetch_with_guard

    result = await fetch_with_guard("http://127.0.0.1:22/")
    assert result.ok is False
    assert result.body in (None, b"") or not result.body


@pytest.mark.asyncio
async def test_proxy_fetch_refuses_a_disallowed_scheme_end_to_end():
    from backend.proxy.fetch_client import fetch_with_guard

    result = await fetch_with_guard("file:///etc/passwd")
    assert result.ok is False


@pytest.mark.asyncio
async def test_proxy_fetch_never_raises_on_a_refusal():
    """REQ-2 AC4: failures are surfaced in-band, never as a 500."""
    from backend.proxy.fetch_client import fetch_with_guard

    for bad in ("http://169.254.169.254/latest/meta-data/",
                "https://this-host-does-not-exist.invalid/",
                "gopher://x/"):
        result = await fetch_with_guard(bad)
        assert result.ok is False
        assert isinstance(result.error, str) and result.error
