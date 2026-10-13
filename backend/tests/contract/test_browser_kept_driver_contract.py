"""Contract pin (2026-10-13): the idle stop keeps the Playwright driver.

Measured live: a cold driver start (node.exe + ~400 package files on the C: HDD)
took 27.7 s and made a web-toggle relaunch 67.5 s. With the driver kept the
relaunch took 0.1 s (real Playwright). The idle stop closes Chromium (the RAM)
and keeps the small driver in ``_idle_driver`` for the next ``_start_browser()``.

Playwright is FAKED. No browser, no driver process, no network.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from backend.vision import browser_pool


class FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    def is_connected(self) -> bool:
        return not self.closed

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, driver: "FakeDriver") -> None:
        self._driver = driver

    async def launch(self, **kwargs) -> FakeBrowser:
        self._driver.launches += 1
        if self._driver.fail_launch:
            raise RuntimeError("driver is dead")
        return FakeBrowser()


class FakeDriver:
    def __init__(self) -> None:
        self.launches = 0
        self.stops = 0
        self.fail_launch = False
        self.chromium = FakeChromium(self)

    async def stop(self) -> None:
        self.stops += 1


class FakeAsyncPlaywright:
    """What ``async_playwright()`` returns: ``start()`` makes a NEW driver."""

    def __init__(self) -> None:
        self.starts = 0
        self.drivers: list[FakeDriver] = []

    async def start(self) -> FakeDriver:
        self.starts += 1
        driver = FakeDriver()
        self.drivers.append(driver)
        return driver


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    fake = FakeAsyncPlaywright()
    module = types.ModuleType("playwright.async_api")
    module.async_playwright = lambda: fake
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    monkeypatch.setattr(browser_pool, "_preread_browser_files", lambda: None)

    async def _no_spare() -> None:
        return None

    monkeypatch.setattr(browser_pool, "_drop_spare", _no_spare)
    monkeypatch.setattr(browser_pool, "_pw", None, raising=False)
    monkeypatch.setattr(browser_pool, "_browser", None, raising=False)
    monkeypatch.setattr(browser_pool, "_owned", False, raising=False)
    monkeypatch.setattr(browser_pool, "_idle_driver", None, raising=False)
    return fake


def test_idle_stop_keeps_the_driver(_fakes):
    async def scenario():
        await browser_pool._start_browser()
        driver = browser_pool._pw
        browser = browser_pool._browser
        await browser_pool._stop_owned_browser(keep_driver=True)
        return driver, browser

    driver, browser = asyncio.run(scenario())
    assert _fakes.starts == 1
    assert browser.closed is True
    assert driver.stops == 0
    assert browser_pool._idle_driver is driver
    assert browser_pool._browser is None


def test_relaunch_reuses_the_kept_driver(_fakes):
    async def scenario():
        await browser_pool._start_browser()
        driver = browser_pool._pw
        await browser_pool._stop_owned_browser(keep_driver=True)
        await browser_pool._start_browser()
        return driver

    driver = asyncio.run(scenario())
    assert _fakes.starts == 1
    assert driver.launches == 2
    assert browser_pool._pw is driver
    assert browser_pool._idle_driver is None
    assert browser_pool._browser is not None


def test_a_dead_kept_driver_falls_back_to_a_fresh_one(_fakes):
    async def scenario():
        await browser_pool._start_browser()
        dead = browser_pool._pw
        await browser_pool._stop_owned_browser(keep_driver=True)
        assert dead.stops == 0  # kept, not stopped: the stop below is the fallback's
        dead.fail_launch = True
        await browser_pool._start_browser()
        return dead

    dead = asyncio.run(scenario())
    assert dead.stops == 1
    assert _fakes.starts == 2
    assert browser_pool._pw is _fakes.drivers[1]
    assert browser_pool._idle_driver is None
    assert browser_pool._browser is not None


def test_other_stops_stop_the_kept_driver(_fakes):
    async def scenario():
        await browser_pool._start_browser()
        driver = browser_pool._pw
        await browser_pool._stop_owned_browser(keep_driver=True)
        assert driver.stops == 0  # kept before the other stop runs
        await browser_pool._stop_owned_browser()
        return driver

    driver = asyncio.run(scenario())
    assert driver.stops == 1
    assert browser_pool._idle_driver is None


def test_the_idle_watch_keeps_the_driver(_fakes, monkeypatch):
    calls: list[dict] = []
    real_stop = browser_pool._stop_owned_browser

    async def recording_stop(*args, **kwargs):
        calls.append(kwargs)
        await real_stop(*args, **kwargs)

    async def scenario():
        await browser_pool._start_browser()
        driver = browser_pool._pw
        await browser_pool._idle_watch()
        return driver

    monkeypatch.setattr(browser_pool, "_IDLE_TIMEOUT", 0)
    monkeypatch.setattr(browser_pool, "should_idle_stop_browser", lambda: True)
    monkeypatch.setattr(browser_pool, "_stop_owned_browser", recording_stop)
    monkeypatch.setattr(browser_pool, "_browser_idle_callback", None)

    driver = asyncio.run(scenario())
    assert len(calls) == 1
    assert calls[0].get("keep_driver") is True
    assert driver.stops == 0
    assert browser_pool._idle_driver is driver
