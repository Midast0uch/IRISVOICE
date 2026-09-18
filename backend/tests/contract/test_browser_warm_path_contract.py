"""CT (REQ-18, T20): browser warm-path bound + cold-launch accounting.

Hermetic: the pool is driven directly with a fake Playwright (patched at the
same seam ``test_browser_pool_contract.py`` uses). No live browser, no network.

Pins:
  1. The acquire is CLASSIFIED cold (paid a launch) vs warm (reused a live
     browser) and the split is observable (REQ-18 AC1).
  2. A run that DECLARED it needs the browser holds the pool warm, so the
     idle-stop does NOT fire between two URLs of the same run (REQ-18 AC2).
  3. A cold launch is ANNOUNCED on the lifecycle callback channel (REQ-18 AC3).
  4. The acquire is BOUNDED and FAILS OPEN -- a wedged launch raises within the
     timeout rather than pinning the run or the start lock (REQ-18 AC4).
  5. The plan-time prewarm (``_maybe_prewarm_browser_for_discovery``) runs and
     fails open -- it currently has NO test.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.vision import browser_pool


@pytest.fixture(autouse=True)
async def _reset_pool():
    await browser_pool.shutdown_browser_pool()
    browser_pool._warm_run_holders = 0
    browser_pool._last_acquire_was_cold = False
    yield
    await browser_pool.shutdown_browser_pool()
    browser_pool._warm_run_holders = 0


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    def is_connected(self) -> bool:
        return not self.closed

    async def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, delay: float = 0.0):
        self.launches = 0
        self._delay = delay

    async def launch(self, **kwargs):
        self.launches += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return _FakeBrowser()


class _FakePW:
    def __init__(self, delay: float = 0.0):
        self.chromium = _FakeChromium(delay=delay)

    async def stop(self):
        pass


class _FakePlaywrightCtx:
    """Stand-in for ``async_playwright()`` -- awaited, then ``.start()``."""

    def __init__(self, pw):
        self._pw = pw

    async def start(self):
        return self._pw


def test_acquire_classifies_cold_then_warm():
    """REQ-18 AC1: first acquire is COLD (a launch happened); the next is WARM."""
    pw = _FakePW()
    with patch(
        "playwright.async_api.async_playwright",
        return_value=_FakePlaywrightCtx(pw),
    ):
        async def _go():
            await browser_pool.acquire_browser()
            assert browser_pool.last_acquire_was_cold() is True
            # Second acquire reuses the live browser -> warm.
            await browser_pool.acquire_browser()
            assert browser_pool.last_acquire_was_cold() is False

        asyncio.run(_go())
    assert pw.chromium.launches == 1  # exactly one launch for two acquires


def test_declared_run_holds_pool_warm_between_urls():
    """REQ-18 AC2: while a run holds warmth the idle-stop predicate is False,
    so the pool is NOT stopped between two URLs of the same run."""
    browser_pool._owned = True
    browser_pool._browser = _FakeBrowser()
    browser_pool._last_browser_use = 0.0  # long idle

    # Without a declared run, an idle owned pool WOULD stop.
    assert browser_pool.should_idle_stop_browser() is True

    browser_pool.declare_browser_run()
    try:
        assert browser_pool.has_warm_run_holder() is True
        assert browser_pool.should_idle_stop_browser() is False
    finally:
        browser_pool.release_browser_run()

    # Released -> warmth holder cleared. (release touches use, so the pool stays
    # warm for the idle window after the run — that is intended; re-age it to
    # prove the holder is what gated the stop.)
    assert browser_pool.has_warm_run_holder() is False
    browser_pool._last_browser_use = 0.0
    assert browser_pool.should_idle_stop_browser() is True


def test_cold_launch_is_announced():
    """REQ-18 AC3: a cold launch is announced on the lifecycle callback."""
    pw = _FakePW()
    seen: list = []
    browser_pool.set_browser_idle_callback(lambda *a: seen.append(a))
    try:
        with patch(
            "playwright.async_api.async_playwright",
            return_value=_FakePlaywrightCtx(pw),
        ):
            asyncio.run(browser_pool.acquire_browser())
    finally:
        browser_pool.set_browser_idle_callback(None)
    assert seen, "a cold launch emitted no lifecycle announcement"


def test_acquire_is_bounded_and_fails_open(monkeypatch):
    """REQ-18 AC4: a wedged launch raises within the bound instead of pinning
    the run (and the start lock is released by the async-with)."""
    monkeypatch.setattr(browser_pool, "_ACQUIRE_TIMEOUT_MS", 50)
    pw = _FakePW(delay=5.0)  # launch takes far longer than the bound
    with patch(
        "playwright.async_api.async_playwright",
        return_value=_FakePlaywrightCtx(pw),
    ):
        with pytest.raises(Exception):
            asyncio.run(browser_pool.acquire_browser())
    # The start lock is NOT held after the failed acquire.
    assert browser_pool._start_lock.locked() is False



def test_plan_time_prewarm_runs_and_fails_open(monkeypatch):
    """REQ-18 (T20): the plan-time prewarm has NO test today -- pin it.

    ``_maybe_prewarm_browser_for_discovery`` acquires then releases the browser
    at once (warming the pool without pinning a lease), and NEVER raises into
    ``research()`` even when the acquire fails.
    """
    from backend.crawler.orchestrator import CrawlOrchestrator

    orch = CrawlOrchestrator()

    # Brain has no sight -> prewarm proceeds.
    class _K:
        _router = None

    monkeypatch.setattr(
        "backend.agent.get_agent_kernel", lambda *_a, **_k: _K(), raising=False,
    )

    acquire_calls: list = []

    class _Lease:
        def release(self):
            acquire_calls.append("released")

    async def _fake_acquire(max_lease_ms=0):
        acquire_calls.append("acquired")
        return object(), _Lease()

    monkeypatch.setattr(browser_pool, "acquire_browser", _fake_acquire)
    asyncio.run(orch._maybe_prewarm_browser_for_discovery("job-prewarm"))
    assert "acquired" in acquire_calls and "released" in acquire_calls, (
        "prewarm did not acquire+release the browser"
    )


def test_plan_time_prewarm_never_raises_on_acquire_failure(monkeypatch):
    """REQ-18 AC4 fail-open: a failing prewarm acquire must NOT raise into the
    caller (the URL cold-starts on demand instead)."""
    from backend.crawler.orchestrator import CrawlOrchestrator

    orch = CrawlOrchestrator()

    class _K:
        _router = None

    monkeypatch.setattr(
        "backend.agent.get_agent_kernel", lambda *_a, **_k: _K(), raising=False,
    )

    async def _boom(max_lease_ms=0):
        raise RuntimeError("chromium wedged")

    monkeypatch.setattr(browser_pool, "acquire_browser", _boom)
    # Must NOT raise.
    asyncio.run(orch._maybe_prewarm_browser_for_discovery("job-prewarm-fail"))
