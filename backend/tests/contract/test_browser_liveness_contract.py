"""Browser liveness guards (live 2026-10-02, run A5).

1. The page closed mid-task; browser_open then answered "ok" on the dead page
   in 12-36 ms and every observe failed - the agent fell back to curl. A closed
   page is NOT an available session, so the next open starts a fresh one.
2. Each observe waited the full 3 s for the vision probe while a 2-min vision
   model autoload ran. Only the call that STARTED a probe waits for it.
"""
import asyncio
import time

from backend.agent.tools import browser_tools as bt
from backend.vision.browser_session import BrowserSession


class _Page:
    def __init__(self, closed):
        self._closed = closed

    def is_closed(self):
        return self._closed


def test_a_closed_page_is_not_an_available_session():
    s = BrowserSession(job_id="j", url="https://en.wikipedia.org", goal="g")
    s._page = _Page(closed=False)
    assert s.available() is True
    s._page = _Page(closed=True)
    assert s.available() is False


def test_only_the_call_that_starts_a_vision_probe_waits_for_it(monkeypatch):
    monkeypatch.setattr(bt, "_VISION_WAIT_S", 0.4)
    monkeypatch.setattr(bt, "_vision_state", {"at": 0.0, "value": False, "probing": False})

    def _slow_probe():
        time.sleep(2.0)  # a vision model autoload in progress
        return True

    monkeypatch.setattr(bt, "_vision_live_sync", _slow_probe)

    async def _two_observes():
        t0 = time.monotonic()
        first = await bt._vision_live()
        t1 = time.monotonic()
        second = await bt._vision_live()
        t2 = time.monotonic()
        return first, t1 - t0, second, t2 - t1

    first, w1, second, w2 = asyncio.run(_two_observes())
    assert first is False and second is False
    assert w1 >= 0.35  # the first call waited (bounded)
    assert w2 < 0.15   # the second did not wait again
