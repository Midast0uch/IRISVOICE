"""Contract pin: a blocked ledger write must report itself.

MEASURED LIVE 2026-09-26. The app logged
"[tool-event] meta set for crawler_query: escalated" and no row ever reached
`system_events`. Neither the ingest-failure warning nor the "returned falsy"
warning fired, because the write runs on a fire-and-forget daemon thread: a
blocked write left NO trace at all. The ledger simply stopped gaining rows
while every log line said the record was built, and the cause was NOT the
1.5 GB WAL that first looked guilty.

For a calibration ledger a silent drop is worse than a loud failure: every
number derived from it (precision, ECE, the enforcement bar) quietly loses
evidence. These tests pin the visibility, not the fix.
"""

from __future__ import annotations

import inspect
import logging
import threading

import backend.agent.tool_bridge as tb


def _spawn(target):
    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t


class TestABlockedWriteIsVisible:
    def test_a_blocked_write_is_reported(self, caplog, monkeypatch):
        """The whole point: a write that never returns must say so."""
        release = threading.Event()
        t = _spawn(lambda: release.wait(5))
        monkeypatch.setattr(tb, "_INGEST_WATCH_S", 0.05)
        try:
            with caplog.at_level(logging.WARNING):
                tb._watch_ingest(t, "crawler_query")
        finally:
            release.set()

        assert any("has not returned" in r.getMessage() for r in caplog.records), (
            "a stuck ledger write was silent again"
        )

    def test_a_finished_write_is_silent(self, caplog):
        """No crying wolf: a completed write logs no warning."""
        t = _spawn(lambda: None)
        t.join(5)
        with caplog.at_level(logging.WARNING):
            tb._watch_ingest(t, "read_file")
        assert not [
            r for r in caplog.records if "has not returned" in r.getMessage()
        ]

    def test_the_watchdog_never_raises(self):
        """An observer must never break the path it observes."""

        class _Boom:
            def join(self, timeout=None):
                raise RuntimeError("boom")

            def is_alive(self):
                return True

        tb._watch_ingest(_Boom(), "x")  # must not raise


class TestTheWatchdogIsActuallyWired:
    def test_the_writer_is_watched(self, caplog, monkeypatch):
        """A watchdog nobody starts installs no visibility. This pins the
        WIRING of `_record_tool_event` (the only writer of ledger rows).

        2026-09-29 (owner-approved change of this pin): rows moved from a
        thread per row to ONE ordered ledger lane (~90 per-row threads were
        measured contending live). The pin now drives the real lane: a row
        that never returns must still be reported."""
        import time

        src = inspect.getsource(tb.AgentToolBridge._record_tool_event)
        assert "_LEDGER_LANE.submit" in src, (
            "ledger rows no longer go through the watched ledger lane"
        )
        monkeypatch.setattr(tb, "_INGEST_WATCH_S", 0.05)
        release = threading.Event()
        try:
            with caplog.at_level(logging.WARNING):
                assert tb._LEDGER_LANE.submit("crawler_query", lambda: release.wait(5))
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not any(
                    "has not returned" in r.getMessage() for r in caplog.records
                ):
                    time.sleep(0.02)
        finally:
            release.set()

        assert any("has not returned" in r.getMessage() for r in caplog.records), (
            "the ledger write is fire-and-forget again — a blocked write "
            "would leave no trace"
        )

    def test_the_timeout_is_a_sane_bound(self):
        assert 1.0 <= tb._INGEST_WATCH_S <= 60.0, (
            "too short cries wolf on a slow store; too long hides the stall "
            "past the end of the turn"
        )
