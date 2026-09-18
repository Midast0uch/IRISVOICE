"""CT-5 (REQ-11 AC2/AC3/AC4): session-level corpse self-heal.

REQ-11 verified the POOL-level corpse detection exists (`browser_pool.py`,
pinned by `test_browser_pool_contract.py::test_crashed_browser_is_restarted_
on_next_acquire`), but the SESSION-level `new_context()` corpse reset+retry
(`browser_session.py`) had NO contract test. This pins it:

  - AC2: WHEN `new_context()` raises the corpse signature (`'NoneType' object
    has no attribute 'send'`) THEN the session SHALL force-reset the pool,
    re-acquire, and retry EXACTLY ONCE. Any other error propagates.
  - AC3: IF the retry ALSO fails THEN the session SHALL mark itself unavailable
    and degrade — never raise into the run.
  - AC4: corpse detection + self-heal is logged, scoped by job id.

Hermetic: the pool's acquire/reset are monkeypatched; no real browser.
"""

from __future__ import annotations

import asyncio
import logging

from backend.vision import browser_pool
from backend.vision.browser_session import BrowserSession, SessionBounds

_CORPSE = "'NoneType' object has no attribute 'send'"


class DeadCtxBrowser:
    """A browser whose FIRST new_context() raises the corpse signature, then
    succeeds (the pool was reset in between)."""

    def __init__(self):
        self.contexts = 0

    async def new_context(self, **_k):
        self.contexts += 1
        if self.contexts == 1:
            raise RuntimeError(_CORPSE)
        return _OkContext()


class _OkContext:
    async def new_page(self):
        return _OkPage()

    async def close(self):
        pass

    def on(self, *_a):
        pass


class _OkPage:
    async def goto(self, *_a, **_k):
        pass

    async def content(self):
        return "<html><body>ok</body></html>"

    async def close(self):
        pass


class AlwaysDeadBrowser:
    async def new_context(self, **_k):
        raise RuntimeError(_CORPSE)


class _Lease:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True

    def renew(self, *_a, **_k):
        pass


def _run(coro):
    return asyncio.run(coro)


def test_corpse_signature_triggers_reset_reacquire_and_one_retry(monkeypatch):
    """REQ-11 AC2: the corpse signature -> reset, re-acquire, retry ONCE."""
    resets: list = []
    acquires: list = []

    class _HealthyBrowser:
        async def new_context(self, **_k):
            return _OkContext()

    async def _acquire(max_lease_ms=0):
        acquires.append(1)
        # First acquire: a browser whose new_context raises the corpse sig.
        # Second acquire (after reset): a healthy browser.
        return (DeadCtxBrowser() if len(acquires) == 1 else _HealthyBrowser()), _Lease()

    async def _reset():
        resets.append(1)

    monkeypatch.setattr(browser_pool, "acquire_browser", _acquire)
    monkeypatch.setattr(browser_pool, "reset_browser_pool", _reset)
    monkeypatch.setattr(browser_pool, "last_acquire_was_cold", lambda: True)

    sess = BrowserSession("job-corpse", "https://a.example/", "read")
    _run(sess.open())

    assert resets, "the corpse signature did not trigger a pool reset (REQ-11 AC2)"
    assert len(acquires) == 2, "the session did not re-acquire after the reset (AC2)"
    assert sess.available() is True


def test_retry_also_fails_marks_unavailable_never_raises(monkeypatch):
    """REQ-11 AC3: if the retry ALSO fails, the session degrades — never raises."""
    async def _acquire(max_lease_ms=0):
        return AlwaysDeadBrowser(), _Lease()

    async def _reset():
        pass

    monkeypatch.setattr(browser_pool, "acquire_browser", _acquire)
    monkeypatch.setattr(browser_pool, "reset_browser_pool", _reset)
    monkeypatch.setattr(browser_pool, "last_acquire_was_cold", lambda: True)

    sess = BrowserSession("job-corpse2", "https://a.example/", "read")
    # Must NOT raise out of open().
    _run(sess.open())
    assert sess.available() is False, "a doubly-corpse browser must degrade (REQ-11 AC3)"


def test_corpse_self_heal_is_logged_with_job_id(monkeypatch, caplog):
    """REQ-11 AC4: corpse detection + self-heal is logged scoped by job id."""
    async def _acquire(max_lease_ms=0):
        return DeadCtxBrowser(), _Lease()

    async def _reset():
        pass

    monkeypatch.setattr(browser_pool, "acquire_browser", _acquire)
    monkeypatch.setattr(browser_pool, "reset_browser_pool", _reset)
    monkeypatch.setattr(browser_pool, "last_acquire_was_cold", lambda: True)

    sess = BrowserSession("job-corpse3", "https://a.example/", "read")
    with caplog.at_level(logging.WARNING, logger="backend.vision.browser_session"):
        _run(sess.open())
    assert any("corpse" in r.getMessage() and "job-corpse3" in r.getMessage()
               for r in caplog.records), (
        "corpse detection was not logged with the job id (REQ-11 AC4)"
    )
