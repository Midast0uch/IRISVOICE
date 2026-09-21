"""BT-4 (vision-goal-directed-search T25, REQ-6 AC6.1/AC6.2): popup / new
window adoption through the Playwright session.

Split from the modal-dismissal suite so the two resilience modes fail
independently. The hooks under test are the same (`_handle_popup_page`
schedules adoption; `_adopt_popup` performs it) — this file asserts the
listener-level contract with a REAL event loop standing in for Playwright's
`context.on("page")` callback.
"""
from __future__ import annotations

import asyncio

from backend.vision.browser_session import BrowserSession


class _Page:
    def __init__(self, url: str):
        self.url = url
        self.closed = False

    async def wait_for_load_state(self, *_a, **_k):
        return None

    async def close(self):
        self.closed = True

    async def content(self):
        return "<html>page</html>"


def _session(old: _Page) -> BrowserSession:
    s = BrowserSession(job_id="j-popup", url=old.url, goal="g")
    s._page = old

    async def _noop_publish():
        return None

    s._publish_frame = _noop_publish  # type: ignore[assignment]
    return s


def test_listener_schedules_adoption_on_a_live_loop():
    """AC6.1: `context.on("page", ...)` is a SYNC listener; it MUST schedule
    the async adoption instead of awaiting inline. We invoke it exactly as
    Playwright would (from inside the loop) and let the scheduled task run."""
    session = _session(_Page("https://list.example"))
    new_page = _Page("https://checkout.example")

    async def _drive():
        session._handle_popup_page(new_page)
        # Let the scheduled task land: two yields is plenty for create_task.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_drive())

    assert session._page is new_page
    assert session.url == "https://checkout.example"
    assert new_page.closed is False


def test_listener_never_raises_when_no_loop_is_running():
    """A sync listener with no running loop cannot schedule; it must log and
    drop rather than crash the page event that fired it."""
    session = _session(_Page("https://list.example"))
    # No event loop here: _handle_popup_page must survive.
    session._handle_popup_page(_Page("https://popped.example"))
    assert session._page.url == "https://list.example"  # unchanged, no crash
