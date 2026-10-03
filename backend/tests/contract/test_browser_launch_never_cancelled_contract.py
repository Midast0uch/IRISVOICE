"""Addendum H guard (2026-10-02): the Chromium launch is never cancelled by a
caller's bound, and the web toggle holds the browser warm.

Live run (developer mode, Wikipedia task): browser_open timed out at 90 s, the
bound CANCELLED the launch, the retry launched again from zero and timed out
again, the third call opened in 4.5 s - 180 s of a 474 s reply.
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from backend.vision import browser_pool


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    def is_connected(self) -> bool:
        return not self.closed

    async def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, delay: float):
        self.launches = 0
        self._delay = delay

    async def launch(self, **kwargs):
        self.launches += 1
        await asyncio.sleep(self._delay)
        return _FakeBrowser()


class _FakePW:
    def __init__(self, delay: float):
        self.chromium = _FakeChromium(delay)

    async def stop(self):
        pass


class _Ctx:
    def __init__(self, pw):
        self._pw = pw

    async def start(self):
        return self._pw


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    asyncio.run(browser_pool.shutdown_browser_pool())
    monkeypatch.setattr(browser_pool, "_HOLD_OPEN", False)
    yield
    browser_pool._web_hold = False
    asyncio.run(browser_pool.shutdown_browser_pool())


def test_a_timed_out_caller_leaves_the_launch_running_for_the_next(monkeypatch):
    monkeypatch.setattr(browser_pool, "_ACQUIRE_TIMEOUT_MS", 1000)  # floor: 1 s
    pw = _FakePW(delay=1.5)
    with patch("playwright.async_api.async_playwright", return_value=_Ctx(pw)):
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(browser_pool.acquire_browser())
        time.sleep(0.8)  # the launch finishes in the background
        browser, lease = asyncio.run(browser_pool.acquire_browser())
        lease.release()
    assert browser is not None
    assert pw.chromium.launches == 1  # joined, not launched again


def test_web_toggle_on_warms_the_browser_and_holds_it(monkeypatch):
    pw = _FakePW(delay=0.1)
    with patch("playwright.async_api.async_playwright", return_value=_Ctx(pw)):
        browser_pool.set_web_hold(True)
        deadline = time.monotonic() + 3
        while browser_pool._browser is None and time.monotonic() < deadline:
            time.sleep(0.05)
    assert browser_pool._browser is not None  # warmed with no acquire call
    monkeypatch.setattr(browser_pool, "_IDLE_TIMEOUT", 0.0)
    assert browser_pool.should_idle_stop_browser() is False  # held while ON
    browser_pool.set_web_hold(False)
    assert browser_pool.should_idle_stop_browser() is True  # idle rules again


def test_the_keyring_read_never_blocks_the_browser_loop(monkeypatch):
    """Measured 2026-10-02: the first `import keyring` + backend discovery took
    9.5 s ON the browser host loop, inside the first browser_open (86 s with a
    warm Chromium). The read runs on a worker thread; the loop keeps ticking."""
    from backend.vision import browser_session

    def _slow_read(host):
        time.sleep(0.6)
        return None

    monkeypatch.setattr(browser_session, "_keyring_read", _slow_read)

    class _Ctx:
        async def add_cookies(self, cookies):
            pass

    async def _main():
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        t = asyncio.create_task(_ticker())
        await browser_session._inject_keyring_cookies(_Ctx(), "https://en.wikipedia.org", "j")
        t.cancel()
        return ticks

    assert asyncio.run(_main()) >= 5  # the loop ran during the 0.6 s read
