"""Contract tests for ``backend.vision.browser_session`` (T8, REQ-7 + REQ-9 + REQ-11).

Boundary pins for the server-side interactive browser session:

  1. ``open()`` launches (fake) Playwright, navigates, and publishes frame 1
     through the capture store (REQ-11 AC1).
  2. ``act()`` executes scroll/click/type/wait on the page and counts actions.
  3. ``act()`` raises :class:`SessionBudgetExceeded` at the action bound
     (REQ-7 AC4).
  4. ``detect_wall()`` classifies CAPTCHA / LOGIN / PAYWALL / None from DOM
     heuristics only (REQ-7).
  5. ``settle()`` returns the page HTML and publishes it as the next page
     number.
  6. ``close()`` runs in a finally even when ``act()`` raised — the browser
     pool lease releases on exception, and the session's own context/page are
     closed. The SHARED BROWSER is never closed by a session (that is
     ``browser_pool``'s job) — see ``backend/tests/contract/
     test_browser_pool_contract.py`` for the pool's own launch-count and
     idle/lease contract.
  7. A failed Playwright import degrades ``open()`` to unavailable instead of
     raising (REQ-6 AC1 edge) — the module never fails at import.

Playwright is MOCKED ENTIRELY: ``playwright.async_api.async_playwright`` is
patched with a fake driver/browser/context/page that returns canned HTML and
records calls. No live browser, no network, ever.

NOTE (test-contract update, T-browser-pool): ``BrowserSession.open()`` used to
launch its OWN Playwright/Chromium directly; it now acquires a POOLED shared
browser from ``backend.vision.browser_pool`` and opens a fresh
``browser.new_context()`` per session instead of a bare ``browser.new_page()``.
That is an intentional architecture change (eliminates the per-URL cold
browser launch — see browser_pool.py's module docstring for the measured
evidence), not a weakening of test #6: it still proves close() runs on every
exit path and releases what THIS session owns; it now additionally proves
close() does NOT reach into the shared browser. The ``_reset_browser_pool``
fixture below resets the process-wide pool singleton between tests so each
test's own fake Playwright is the one actually exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.vision import browser_pool
from backend.vision.browser_session import (
    BrowserSession,
    SessionBounds,
    SessionBudgetExceeded,
    VisionAction,
    WallKind,
)

CANNED_HTML = "<html><body><h1>Hello</h1><p>world</p></body></html>"


@pytest.fixture(autouse=True)
async def _reset_browser_pool():
    """The pool is a process-wide singleton (that is the whole point — one
    launch shared across sessions). Reset it before AND after every test so
    each test's own patched fake Playwright is the one actually launched,
    never a browser left running by a previous test."""
    await browser_pool.shutdown_browser_pool()
    yield
    await browser_pool.shutdown_browser_pool()


# ── Fake Playwright objects (no live browser, no network) ──────────────────

class FakeLocator:
    def __init__(self, page: "FakePage", selector: str) -> None:
        self._page = page
        self._selector = selector

    async def click(self, timeout: int | None = None) -> None:
        self._page.calls.append(("locator.click", self._selector))

    async def fill(self, value: str | None = None) -> None:
        self._page.calls.append(("locator.fill", self._selector, value))


class FakePage:
    def __init__(self, html: str = CANNED_HTML) -> None:
        self._html = html
        self.calls: list = []

    async def content(self) -> str:
        return self._html

    async def set_html(self, html: str) -> None:
        """T16: let a test mutate the DOM between actions so settle() publishes
        a genuinely different frame (vs. the dedupe-skip path)."""
        self._html = html

    async def goto(self, url: str, wait_until: str | None = None, timeout: int | None = None) -> None:
        self.calls.append(("goto", url))

    async def reload(self) -> None:
        self.calls.append(("reload",))

    async def go_back(self) -> None:
        self.calls.append(("go_back",))

    async def go_forward(self) -> None:
        self.calls.append(("go_forward",))

    async def evaluate(self, js: str) -> None:
        self.calls.append(("evaluate", js))

    async def wait_for_timeout(self, ms: int) -> None:
        self.calls.append(("wait_for_timeout", ms))

    async def wait_for_load_state(self, state: str = "networkidle", timeout: int | None = None) -> None:
        self.calls.append(("wait_for_load_state", state))

    async def close(self) -> None:
        self.calls.append(("close",))

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)


class FakeContext:
    """Stands in for ``browser.new_context()`` — the per-session isolation
    unit. Each context wraps its OWN page so different sessions never see
    each other's DOM/state through a shared context."""

    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.calls: list = []

    async def new_page(self) -> FakePage:
        self.calls.append(("new_page",))
        return self._page

    async def close(self) -> None:
        self.calls.append(("context.close",))


class FakeBrowser:
    def __init__(self, page: FakePage | None = None) -> None:
        self._page = page or FakePage()
        self.calls: list = []
        self.contexts: list[FakeContext] = []

    async def new_context(self) -> FakeContext:
        self.calls.append(("new_context",))
        ctx = FakeContext(self._page)
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        self.calls.append(("browser.close",))


class FakePlaywright:
    """Stands in for the object returned by ``async_playwright().start()``."""

    def __init__(self, browser: FakeBrowser | None = None) -> None:
        self._browser = browser or FakeBrowser()
        self.stopped = False
        self.launch_count = 0

    async def start(self) -> "FakePlaywright":
        return self

    @property
    def chromium(self) -> "FakePlaywright":
        return self

    async def launch(self, headless: bool = True) -> FakeBrowser:
        self.launch_count += 1
        return self._browser

    async def stop(self) -> None:
        self.stopped = True


def _session(job_id: str, url: str, bounds: SessionBounds | None = None) -> BrowserSession:
    return BrowserSession(job_id=job_id, url=url, goal="extract article", bounds=bounds)


# ── 1. open() launches, navigates, publishes frame 1 ───────────────────────

async def test_open_launches_navigates_and_publishes_frame():
    fake_pw = FakePlaywright()
    store = MagicMock()
    with (
        patch("backend.vision.browser_session.get_capture_store", return_value=store),
        patch("playwright.async_api.async_playwright", return_value=fake_pw),
    ):
        session = _session("job-open", "https://example.com/start")
        await session.open()

    assert session.available() is True
    page = fake_pw._browser._page
    assert ("goto", "https://example.com/start") in page.calls

    # REQ-11 AC1: the settled frame was published through the capture store.
    store.save.assert_called_once()
    args = store.save.call_args.args
    assert args[0] == "job-open"                        # job_id
    assert args[1] == 1                                 # first page number
    assert args[2] == "https://example.com/start"       # url
    assert args[3] == CANNED_HTML                       # html
    await session.close()


# ── 2. act() executes scroll/click/type/wait and counts ────────────────────

async def test_act_executes_actions_and_counts():
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        session = _session("job-act", "https://example.com/a", bounds=SessionBounds(max_actions=10))
        await session.open()
        await session.act(VisionAction(kind="scroll", value="800"))
        await session.act(VisionAction(kind="click", target="#btn"))
        await session.act(VisionAction(kind="type", target="#q", value="hello"))
        await session.act(VisionAction(kind="wait", value="50"))
        await session.close()

    assert session.actions_taken == 4
    page = fake_pw._browser._page
    # REPORTABLE TEST EDIT (T15, 2026-08-24): the script literal changed when
    # the scroll and the REQ-16 AC7 mirror read were FUSED into one evaluate
    # (browser_session.py) — two CDP round trips per scroll became one. The
    # assertion is still exact string equality against a literal spelled out
    # here, NOT a substring or regex: same strength, re-pinned to the current
    # contract. Test 3 below counts evaluates and now passes unchanged at 2,
    # which is the guard this fusion actually restores.
    assert (
        "evaluate",
        "(() => { window.scrollBy(0, 800);"
        " try { return {y: window.pageYOffset"
        " || document.documentElement.scrollTop || 0,"
        " h: Math.max(document.documentElement.scrollHeight,"
        " document.body ? document.body.scrollHeight : 0)}; }"
        " catch (e) { return null; } })()",
    ) in page.calls
    assert ("locator.click", "#btn") in page.calls
    assert ("locator.fill", "#q", "hello") in page.calls
    assert ("wait_for_timeout", 50) in page.calls
    assert session.last_error is None


# ── 3. act() raises SessionBudgetExceeded at the action bound ──────────────

async def test_act_raises_session_budget_exceeded_at_max_actions():
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        session = _session("job-budget", "https://example.com/b", bounds=SessionBounds(max_actions=2))
        await session.open()
        await session.act(VisionAction(kind="scroll", value="100"))
        await session.act(VisionAction(kind="scroll", value="100"))
        with pytest.raises(SessionBudgetExceeded):
            await session.act(VisionAction(kind="scroll", value="100"))
        await session.close()

    # The refused action was never executed nor counted.
    assert session.actions_taken == 2
    assert sum(1 for c in fake_pw._browser._page.calls if c[0] == "evaluate") == 2


# ── 4. detect_wall() DOM heuristics ────────────────────────────────────────

@pytest.mark.parametrize(
    "html,expected",
    [
        # CAPTCHA — structural markers
        ('<html><div id="captcha-box">x</div></html>', WallKind.CAPTCHA),
        ('<html><iframe src="https://host/challenge"></iframe></html>', WallKind.CAPTCHA),
        ('<html><input name="captcha_answer" type="text"></html>', WallKind.CAPTCHA),
        ('<html><div id="cf-turnstile"></div></html>', WallKind.CAPTCHA),
        ('<html><div class="g-recaptcha"></div></html>', WallKind.CAPTCHA),
        # CAPTCHA — interstitial prose
        ('<html><title>Just a moment…</title></html>', WallKind.CAPTCHA),
        ('<html><body>Verify you are human</body></html>', WallKind.CAPTCHA),
        # LOGIN
        ('<html><form><input type="password" name="p"></form></html>', WallKind.LOGIN),
        ('<html><body>Please sign in to continue</body></html>', WallKind.LOGIN),
        ('<html><body>Log in to view this page</body></html>', WallKind.LOGIN),
        # PAYWALL
        ('<html><body>Subscribe to read the full article</body></html>', WallKind.PAYWALL),
        ('<html><body>Premium content — sign up to continue</body></html>', WallKind.PAYWALL),
        ('<html><body>This article is behind a paywall</body></html>', WallKind.PAYWALL),
        # No wall
        ('<html><body>plain article content here</body></html>', None),
    ],
)
async def test_detect_wall(html, expected):
    fake_pw = FakePlaywright(browser=FakeBrowser(page=FakePage(html=html)))
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        session = _session("job-wall", "https://example.com/wall")
        await session.open()
        assert await session.detect_wall() is expected
        await session.close()


# ── 5. settle() returns html and publishes the next page number ────────────

async def test_settle_returns_html_and_publishes_next_page_number():
    fake_pw = FakePlaywright()
    store = MagicMock()
    with (
        patch("backend.vision.browser_session.get_capture_store", return_value=store),
        patch("playwright.async_api.async_playwright", return_value=fake_pw),
    ):
        session = _session("job-settle", "https://example.com/settle")
        await session.open()
        assert store.save.call_count == 1  # frame 1 from open()

        # T16 (REQ-11): the DOM changed after the actions, so settle() publishes
        # a NEW distinct frame (rate-bounded dedupe only collapses identical
        # DOM). Fixture input update (called out): the fake now mutates its DOM
        # after open() so the settle frame is genuinely different; the
        # assertion (save.call_count == 2) is unchanged and still holds.
        await fake_pw._browser._page.set_html("<html><body><h1>Updated</h1></body></html>")
        html = await session.settle()
        await session.close()

    assert html == "<html><body><h1>Updated</h1></body></html>"
    assert store.save.call_count == 2
    args = store.save.call_args.args
    assert args[0] == "job-settle"
    assert args[1] == 2                 # next page number after open()
    assert args[2] == "https://example.com/settle"
    assert args[3] == "<html><body><h1>Updated</h1></body></html>"


# ── 5b. T16 rate-bound: identical DOM is NOT re-published ───────────────────

async def test_settle_identical_dom_not_republished():
    """T16 (REQ-11 AC5): a settle that returns the SAME DOM as open() must not
    spam the capture store — the dedupe keeps one frame per distinct state."""
    fake_pw = FakePlaywright()
    store = MagicMock()
    with (
        patch("backend.vision.browser_session.get_capture_store", return_value=store),
        patch("playwright.async_api.async_playwright", return_value=fake_pw),
    ):
        session = _session("job-dedupe", "https://example.com/dedupe")
        await session.open()
        assert store.save.call_count == 1

        html = await session.settle()  # DOM unchanged
        await session.close()

    assert html == CANNED_HTML
    assert store.save.call_count == 1  # identical frame skipped (T16)


# ── 6. close() runs in a finally even when act() raised ────────────────────

async def test_close_runs_in_finally_when_act_raises():
    """close() must run on every exit path, releasing what THIS session
    owns (page, context, lease) — and it must NOT reach into the shared
    pooled browser (that stays alive for the next session; see
    test_browser_pool_contract.py for the pool's own shutdown contract)."""
    fake_pw = FakePlaywright()
    with patch("playwright.async_api.async_playwright", return_value=fake_pw):
        session = _session("job-close", "https://example.com/c", bounds=SessionBounds(max_actions=1))
        try:
            await session.open()
            await session.act(VisionAction(kind="scroll", value="100"))  # consumes the bound
            await session.act(VisionAction(kind="scroll", value="100"))  # raises
            pytest.fail("expected SessionBudgetExceeded")
        except SessionBudgetExceeded:
            pass
        finally:
            await session.close()

    assert session.available() is False
    page = fake_pw._browser._page
    assert ("close",) in page.calls
    context = fake_pw._browser.contexts[0]
    assert ("context.close",) in context.calls
    # The session released ITS OWN context/page; the shared browser + driver
    # are pool-owned and must survive this session's close() untouched.
    assert ("browser.close",) not in fake_pw._browser.calls
    assert fake_pw.stopped is False


# ── 7. Playwright import failure degrades, does not raise ──────────────────

async def test_playwright_import_failure_marks_unavailable(monkeypatch):
    import sys

    # Make `from playwright.async_api import async_playwright` raise ImportError
    # inside open(). BOTH module entries must be removed from the cache: earlier
    # tests import playwright.async_api (patch target resolution), so setting
    # only the top-level package to None still resolves the from-import from the
    # cached submodule — which would silently launch a REAL browser + network.
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)

    session = _session("job-nopw", "https://example.com/nopw")
    await session.open()  # must NOT raise

    assert session.available() is False
    assert session.actions_taken == 0
    await session.close()  # safe no-op
