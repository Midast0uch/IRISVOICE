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
        # 10 s: the claim is 'built with no caller', not a speed; a loaded box (a
        # 27 s group run, 2026-10-02) missed a 3 s wait for the background thread.
        deadline = time.monotonic() + 10
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


def test_the_dispatcher_never_cuts_a_browser_tool_before_its_own_ceiling():
    """Live 2026-10-02: browser_open (own ceiling 120 s) died three times at the
    dispatcher's 90 s default with 'TimeoutError (no message)'."""
    from types import SimpleNamespace

    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.tools import browser_tools as bt

    ceilings = {"browser_open": bt._OPEN_TIMEOUT_S, "browser_act": bt._ACT_TIMEOUT_S,
                "browser_observe": bt._OBSERVE_TIMEOUT_S, "browser_explore": bt._EXPLORE_TIMEOUT_S + 5.0}
    for tool, own in ceilings.items():
        assert AgentKernel._der_tool_deadline(SimpleNamespace(), tool) > own, tool


class _SparePage:
    pass


class _SpareCtx:
    def __init__(self, counter):
        self.counter = counter

    async def new_page(self):
        self.counter["pages"] += 1
        return _SparePage()

    async def close(self):
        pass


class _BrowserWithContexts(_FakeBrowser):
    def __init__(self, counter):
        super().__init__()
        self.counter = counter

    async def new_context(self, **kw):
        self.counter["contexts"] += 1
        return _SpareCtx(self.counter)


def test_web_on_keeps_one_spare_page_ready_and_replaces_it(monkeypatch):
    """Run A4 (2026-10-02): with a warm Chromium and a free loop, the first open
    still spent 3.0 s on new_context + 29.9 s on new_page. While web is ON the
    pool keeps one fresh spare (context + page) ready; a session takes it once
    and a new spare is built in the background."""
    counter = {"contexts": 0, "pages": 0}
    pw = _FakePW(delay=0.05)

    async def _launch(**kwargs):
        return _BrowserWithContexts(counter)

    pw.chromium.launch = _launch
    with patch("playwright.async_api.async_playwright", return_value=_Ctx(pw)):
        browser_pool.set_web_hold(True)
        # 10 s: the claim is 'built with no caller', not a speed; a loaded box (a
        # 27 s group run, 2026-10-02) missed a 3 s wait for the background thread.
        deadline = time.monotonic() + 10
        while browser_pool._spare is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert browser_pool._spare is not None  # built with no session asking
        first = asyncio.run(browser_pool.get_browser_host().run(browser_pool.take_spare_page()))
        assert first is not None
        again = asyncio.run(browser_pool.get_browser_host().run(browser_pool.take_spare_page()))
        assert again is None or again is not first  # never handed out twice
        # 10 s: the claim is 'built with no caller', not a speed; a loaded box (a
        # 27 s group run, 2026-10-02) missed a 3 s wait for the background thread.
        deadline = time.monotonic() + 10
        while browser_pool._spare is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert browser_pool._spare is not None  # replaced in the background
    assert counter["pages"] >= 2
