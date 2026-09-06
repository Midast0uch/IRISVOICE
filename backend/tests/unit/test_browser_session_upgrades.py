"""Unit tests for machine-speed session upgrades (REQ-4/5/6/12, T8).

Fake Playwright surfaces (no browser): teleport order, micro-settle,
targeted screenshots, overlay dismissal + retry, popup adoption, keyring
cookie injection, and HAR redaction.
"""

import json
import sys

import pytest

from backend.crawler.crawler_engine import sanitize_har_entries
from backend.vision.action_allowlist import ActionType  # noqa: F401 (contract parity)
from backend.vision.browser_session import (
    DISMISS_SELECTORS,
    BrowserSession,
    VisionAction,
    _inject_keyring_cookies,
)


class FakeLocator:
    def __init__(self, page, selector, click_failures=0, click_error="",
                 screenshot_bytes=b"ELEM-SHOT"):
        self._page = page
        self._selector = selector
        self._click_failures = click_failures
        self._click_error = click_error
        self._shot = screenshot_bytes

    @property
    def first(self):
        return self

    async def scroll_into_view_if_needed(self, timeout=None):
        self._page.calls.append(("teleport", self._selector))

    async def bounding_box(self, timeout=None):
        return {"x": 10.0, "y": 20.0, "width": 40.0, "height": 30.0}

    async def click(self, timeout=None):
        if self._click_failures > 0:
            self._click_failures -= 1
            raise Exception(self._click_error or "click failed")
        self._page.calls.append(("click", self._selector))

    async def fill(self, value):
        self._page.calls.append(("fill", self._selector, value))

    async def screenshot(self, timeout=None):
        if self._shot is None:
            raise Exception("no such element")
        return self._shot


class FakeKeyboard:
    def __init__(self, page):
        self._page = page

    async def press(self, key):
        self._page.calls.append(("key", key))


class FakePage:
    def __init__(self, url="https://example.com/a", locators=None):
        self.url = url
        self.calls = []
        self.closed = False
        self.viewport_size = {"width": 800, "height": 600}
        self.keyboard = FakeKeyboard(self)
        self._locators = dict(locators or {})

    def locator(self, selector):
        if selector in self._locators:
            return self._locators[selector]
        loc = FakeLocator(self, selector)
        self._locators[selector] = loc
        return loc

    async def evaluate(self, js):
        self.calls.append(("evaluate", js[:40]))
        return 3

    async def wait_for_timeout(self, ms):
        self.calls.append(("settle", ms))

    async def wait_for_load_state(self, state, timeout=None):
        self.calls.append(("loadstate", state))

    async def screenshot(self, type="png"):
        return b"VIEW-SHOT"

    async def content(self):
        return "<html>fake</html>"

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self):
        self.cookies_added = None
        self.listeners = {}

    async def add_cookies(self, cookies):
        self.cookies_added = list(cookies)

    def on(self, event, handler):
        self.listeners[event] = handler


def _session(url="https://example.com/a"):
    return BrowserSession(job_id="j1", url=url, goal="probe")


# ── REQ-4: teleport + settle + targeted screenshots ──────────────────────────

async def _run_click():
    session, page = _session(), FakePage()
    await session._execute(page, VisionAction(kind="click", target="#buy"))
    return session, page


def test_click_teleports_before_acting():
    import asyncio
    _, page = asyncio.run(_run_click())
    kinds = [c[0] for c in page.calls]
    assert kinds.index("teleport") < kinds.index("click")


def test_scroll_applies_bounded_micro_settle():
    import asyncio

    async def go():
        session, page = _session(), FakePage()
        await session._execute(page, VisionAction(kind="scroll", value="400"))
        return page

    page = asyncio.run(go())
    assert ("settle", 150) in page.calls
    assert any(c[0] == "click" for c in page.calls) is False


def test_targeted_screenshot_crops_and_falls_back():
    import asyncio

    async def go():
        session = _session()
        session._page = FakePage()
        cropped = await session.screenshot("#panel")
        session._page._locators["#missing"] = FakeLocator(
            session._page, "#missing", screenshot_bytes=None)
        fallback = await session.screenshot("#missing")
        return cropped, fallback

    cropped, fallback = asyncio.run(go())
    assert cropped == b"ELEM-SHOT"
    assert fallback == b"VIEW-SHOT"


# ── REQ-5: overlay dismissal ─────────────────────────────────────────────────

def _intercepted_page():
    accept = FakeLocator(None, "accept")
    page = FakePage(locators={DISMISS_SELECTORS[0]: accept})
    accept._page = page
    buy = FakeLocator(page, "#buy", click_failures=1,
                      click_error="ElementClickInterceptedError: element intercepts pointer events")
    page._locators["#buy"] = buy
    return page


def test_intercepted_click_dismisses_and_retries_once():
    import asyncio

    async def go():
        session, page = _session(), _intercepted_page()
        await session._execute(page, VisionAction(kind="click", target="#buy"))
        return session, page

    session, page = asyncio.run(go())
    clicks = [c for c in page.calls if c[0] == "click"]
    assert len(clicks) == 2  # failed attempt + exactly one retry
    assert session.last_dismissal, "AC5.3: dismissal must be recorded"


def test_non_interception_errors_propagate_without_dismissal():
    import asyncio

    async def go():
        session = _session()
        page = FakePage()
        page._locators["#gone"] = FakeLocator(
            page, "#gone", click_failures=9, click_error="Timeout: waiting for selector")
        with pytest.raises(Exception, match="waiting for selector"):
            await session._execute(page, VisionAction(kind="click", target="#gone"))
        return session

    session = asyncio.run(go())
    assert session.last_dismissal is None


def test_js_hide_fallback_when_no_control_answers():
    import asyncio

    async def go():
        session = _session()
        session._page = FakePage()  # default locators "succeed" only if clicked...
        # ...so make every DISMISS control raise: dismissal must reach JS-hide.
        for sel in DISMISS_SELECTORS:
            session._page._locators[sel] = FakeLocator(
                session._page, sel, click_failures=99, click_error="Timeout")
        assert await session._dismiss_overlays(session._page) is True
        return session

    session = asyncio.run(go())
    assert "JS" in (session.last_dismissal or "")


# ── REQ-6: popup adoption ────────────────────────────────────────────────────

def test_external_popup_adopted_and_old_tab_closed(monkeypatch):
    import asyncio

    async def go():
        session = _session(url="https://example.com/a")
        old = FakePage(url="https://example.com/a")
        session._page = old
        # Bypass the capture store: stub _publish_frame to record only.
        published = []
        orig_publish = BrowserSession._publish_frame

        async def fake_publish(self):
            published.append(self._page_number)
            return "html"

        monkeypatch.setattr(BrowserSession, "_publish_frame", fake_publish)
        new = FakePage(url="https://auth.example.net/login")
        await session._adopt_popup(new)
        assert session._page is new
        assert session.url == "https://auth.example.net/login"
        assert old.closed  # external bounce: prior tab closed
        assert session.pop_adopted_pages() == ["https://auth.example.net/login"]
        assert session.pop_adopted_pages() == []  # drain is one-shot
        monkeypatch.setattr(BrowserSession, "_publish_frame", orig_publish)
        return session

    asyncio.run(go())


def test_same_host_popup_keeps_old_tab(monkeypatch):
    import asyncio

    async def go():
        session = _session(url="https://example.com/a")
        old = FakePage(url="https://example.com/a")
        session._page = old

        async def fake_publish(self):
            return "html"

        monkeypatch.setattr(BrowserSession, "_publish_frame", fake_publish)
        new = FakePage(url="https://example.com/help")
        await session._adopt_popup(new)
        assert session._page is new
        assert not old.closed  # same host: prior tab kept
        return session

    asyncio.run(go())


# ── REQ-12: keyring injection + HAR redaction ────────────────────────────────

def test_keyring_cookies_injected_without_logging_values(monkeypatch):
    import asyncio

    payload = json.dumps([{"name": "sid", "value": "s3cret", "domain": "example.com"},
                          {"name": "", "value": "junk"},
                          "not-a-dict"])

    class _Keyring:
        @staticmethod
        def get_password(service, account):
            assert service == "iris_voice_sessions" and account == "example.com"
            return payload

    monkeypatch.setitem(sys.modules, "keyring", _Keyring)
    ctx = FakeContext()

    async def go():
        return await _inject_keyring_cookies(ctx, "https://example.com/a", "j1")

    assert asyncio.run(go()) == 1  # only the well-formed cookie
    assert ctx.cookies_added == [{"name": "sid", "value": "s3cret",
                                  "domain": "example.com"}]


def test_keyring_miss_or_malformed_is_anonymous(monkeypatch):
    import asyncio

    class _Empty:
        @staticmethod
        def get_password(service, account):
            return None

    class _Bad:
        @staticmethod
        def get_password(service, account):
            return "{not json"

    async def go(impl):
        monkeypatch.setitem(sys.modules, "keyring", impl)
        return await _inject_keyring_cookies(FakeContext(), "https://example.com/", "j1")

    assert asyncio.run(go(_Empty)) == 0
    assert asyncio.run(go(_Bad)) == 0


def test_har_redaction_strips_tokens_and_preserves_shape():
    entries = [{
        "url": "https://example.com/",
        "response_headers": {"Content-Type": "text/html",
                             "Set-Cookie": "sid=s3cret",
                             "X-Auth-Token": "tok"},
        "request_headers": {"Cookie": "a=b", "User-Agent": "iris"},
    }]
    clean = sanitize_har_entries(entries)
    headers = clean[0]["response_headers"]
    assert headers["Set-Cookie"] == "[REDACTED]"
    assert headers["X-Auth-Token"] == "[REDACTED]"
    assert headers["Content-Type"] == "text/html"
    assert clean[0]["request_headers"]["Cookie"] == "[REDACTED]"
    assert clean[0]["request_headers"]["User-Agent"] == "iris"
    # Caller's in-memory entries (penalty scoring) are never mutated.
    assert entries[0]["response_headers"]["Set-Cookie"] == "sid=s3cret"
