"""Contract tests for ``backend.vision.browser_pool`` (T-browser-pool).

Boundary pins for the shared Chromium browser pool that eliminates the
per-URL cold browser launch (live evidence 2026-08-10 18:16: one websearch
escalating 4 URLs paid 4 cold Playwright/Chromium launches; see
``browser_pool.py``'s module docstring and ``crawl_runner.py`` ~:40 for the
measured cold-launch cost on the sibling crawl path).

  1. Two SEQUENTIAL ``BrowserSession``s cause exactly ONE browser launch —
     the core perf claim.
  2. Two CONCURRENT sessions share the browser but get DIFFERENT contexts.
  3. Cookie/storage set in session A's context is NOT visible in session B's
     context (isolation — REQ-5 AC2 run-scoped cookie semantics).
  4. A held lease prevents idle-stop; releasing the last lease permits it.
  5. A lease with an expired hard deadline does not block idle-stop forever
     (crash-leak guard).
  6. The pool never closes a browser it did not start (ownership guard).
  7. Browser-start failure => BrowserSession degrades to unavailable, never
     raises (REQ-6 AC1 edge).

Playwright is MOCKED ENTIRELY — no live browser, no network, ever. Fakes are
intentionally lighter than ``test_browser_session_contract.py``'s (this file
is about the POOL's lifecycle, not action execution).
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from backend.vision import browser_pool
from backend.vision.browser_session import BrowserSession, SessionBounds


@pytest.fixture(autouse=True)
async def _reset_pool():
    """Process-wide singleton — reset before AND after every test so no test
    leaks a running fake browser (or lease bookkeeping) into the next one."""
    await browser_pool.shutdown_browser_pool()
    yield
    await browser_pool.shutdown_browser_pool()


# ── Fake Playwright objects (no live browser, no network) ──────────────────

class FakePage:
    def __init__(self) -> None:
        self.calls: list = []

    async def content(self) -> str:
        return "<html><body>ok</body></html>"

    async def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None) -> None:
        self.calls.append(("goto", url))

    async def close(self) -> None:
        self.calls.append(("close",))


class FakeContext:
    """Isolation unit: each context owns its OWN page + a tiny in-memory
    'cookie jar' so tests can prove one session's cookies never leak into
    another session's context."""

    def __init__(self) -> None:
        self._page = FakePage()
        self.storage: dict[str, str] = {}
        self.closed = False

    async def new_page(self) -> FakePage:
        return self._page

    def set_cookie(self, name: str, value: str) -> None:
        self.storage[name] = value

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.closed = False

    async def new_context(self) -> FakeContext:
        ctx = FakeContext()
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        self.closed = True


class FakePlaywright:
    """Stands in for the object returned by ``async_playwright().start()``.
    Tracks ``launch_count`` — the perf claim under test."""

    def __init__(self) -> None:
        self.browser = FakeBrowser()
        self.launch_count = 0
        self.stopped = False

    async def start(self) -> "FakePlaywright":
        return self

    @property
    def chromium(self) -> "FakePlaywright":
        return self

    async def launch(self, headless: bool = True) -> FakeBrowser:
        self.launch_count += 1
        return self.browser

    async def stop(self) -> None:
        self.stopped = True


class FailingPlaywright:
    """Simulates a hard chromium launch crash — start() succeeds, launch() raises."""

    def __init__(self) -> None:
        self.stop_called = False

    async def start(self) -> "FailingPlaywright":
        return self

    @property
    def chromium(self) -> "FailingPlaywright":
        return self

    async def launch(self, headless: bool = True):
        raise RuntimeError("chromium launch crashed")

    async def stop(self) -> None:
        self.stop_called = True


def _session(job_id: str, url: str = "https://example.com/x") -> BrowserSession:
    return BrowserSession(job_id=job_id, url=url, goal="extract", bounds=SessionBounds())


# ── 1. Two sequential sessions -> exactly ONE browser launch ───────────────

async def test_two_sequential_sessions_one_browser_launch():
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        s1 = _session("job-1")
        await s1.open()
        assert s1.available() is True
        await s1.close()

        s2 = _session("job-2")
        await s2.open()
        assert s2.available() is True
        await s2.close()

    assert fake_pw.launch_count == 1  # the core perf claim


# ── 2. Two concurrent sessions share the browser, different contexts ───────

async def test_two_concurrent_sessions_share_browser_different_contexts():
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        s1 = _session("job-a")
        s2 = _session("job-b")
        await s1.open()
        await s2.open()  # both open concurrently — neither closed yet

        assert fake_pw.launch_count == 1  # still one shared browser
        assert s1._context is not None and s2._context is not None
        assert s1._context is not s2._context  # different contexts

        await s1.close()
        await s2.close()


# ── 3. Cookie/storage isolation between sessions ────────────────────────────

async def test_cookie_set_in_session_a_not_visible_in_session_b():
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        s1 = _session("job-cookie-a")
        await s1.open()
        s1._context.set_cookie("session_id", "secret-a")

        s2 = _session("job-cookie-b")
        await s2.open()

        assert "session_id" not in s2._context.storage
        assert s2._context.storage == {}
        assert s1._context.storage == {"session_id": "secret-a"}

        await s1.close()
        await s2.close()


# ── 4. Held lease prevents idle-stop; release permits it ───────────────────

async def test_held_lease_prevents_idle_stop_and_release_permits_it():
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        session = _session("job-lease")
        await session.open()

        browser_pool._last_browser_use = time.monotonic() - browser_pool._IDLE_TIMEOUT - 10
        assert browser_pool.has_active_browser_lease() is True
        assert browser_pool.should_idle_stop_browser() is False  # lease overrides idle timeout

        await session.close()  # releases the lease

        assert browser_pool.has_active_browser_lease() is False
        assert browser_pool.should_idle_stop_browser() is True


# ── 5. Expired hard deadline does not block idle-stop forever ──────────────

async def test_expired_lease_does_not_block_idle_stop_forever():
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        await browser_pool.acquire_browser(max_lease_ms=1)  # 1 ms hard expiry
        assert browser_pool.has_active_browser_lease() is True

        time.sleep(0.05)
        browser_pool._last_browser_use = time.monotonic() - browser_pool._IDLE_TIMEOUT - 10

        assert browser_pool.has_active_browser_lease() is False  # lazily pruned
        assert browser_pool.should_idle_stop_browser() is True


# ── 6. Pool never closes a browser it did not start ────────────────────────

async def test_pool_never_closes_unowned_browser():
    unowned = FakeBrowser()
    browser_pool._browser = unowned
    browser_pool._pw = None
    browser_pool._owned = False  # NOT started by this module

    await browser_pool._stop_owned_browser()

    assert unowned.closed is False
    assert browser_pool._browser is unowned  # left completely alone

    # Clean up manually since this test bypassed the normal start path
    # (the autouse fixture's shutdown_browser_pool() would also refuse to
    # touch it, by the same ownership guard being tested here).
    browser_pool._browser = None


# ── 7. Browser-start failure -> session unavailable, no raise ──────────────

async def test_browser_start_failure_marks_session_unavailable_no_raise():
    failing_pw = FailingPlaywright()
    with patch("playwright.async_api.async_playwright", return_value=failing_pw):
        session = _session("job-fail")
        await session.open()  # must NOT raise

    assert session.available() is False
    assert browser_pool._browser is None  # pool left clean, not half-started
    assert failing_pw.stop_called is True  # half-started driver was cleaned up
