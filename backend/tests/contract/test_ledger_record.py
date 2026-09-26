"""Contract test for AC5.3: async ledger event recording.

specs/tool-decision-engine-improvements REQ-5 AC5.3:
    THE SYSTEM SHALL record the shared image buffer to the event ledger
    asynchronously off the critical thread.

The _record_tool_event method already runs its FFI ingest on a daemon thread
(tool_bridge.py:2204-2206). This test proves the async behavior:
  1. _record_tool_event returns immediately (does not block the caller)
  2. The FFI call happens on a separate daemon thread
  3. The screenshot_blob is forwarded correctly
"""

from __future__ import annotations

import json
import threading
import time

import backend.agent.tool_bridge as tb
from backend.agent.tool_bridge import AgentToolBridge


class _Capture:
    def __init__(self):
        self.rows = []
        self.done = threading.Event()
        self.thread_id = None

    def ingest(self, **kw):
        self.thread_id = threading.current_thread().ident
        kw["payload_json"] = json.loads(kw["payload_json"])
        self.rows.append(kw)
        self.done.set()


def _cap(monkeypatch) -> _Capture:
    cap = _Capture()
    import backend.gateway.iris_ffi as ffi
    monkeypatch.setattr(ffi, "ffi_ingest_event", cap.ingest)
    return cap


def test_async_ledger_event_record(monkeypatch):
    """AC5.3: _record_tool_event must not block the calling thread.

    The method returns immediately after spawning a daemon thread for the
    FFI ingest. The caller (tool execution path) never waits for SQLite.
    """
    cap = _cap(monkeypatch)
    bridge = AgentToolBridge()

    caller_thread = threading.current_thread().ident
    start = time.monotonic()
    bridge._record_tool_event(
        "s1", "take_screenshot", "success",
        {"x": 1}, {"success": True}, screenshot_blob=b"ASYNC_SHOT",
    )
    elapsed_ms = (time.monotonic() - start) * 1000

    # The call must return near-instantly — it must NOT wait for FFI.
    # A synchronous FFI call would take >10ms; async spawn is <1ms.
    assert elapsed_ms < 50, (
        f"_record_tool_event blocked for {elapsed_ms:.1f}ms — "
        "it must return immediately, not wait for FFI"
    )

    # The ingest DOES happen, just on a different thread.
    assert cap.done.wait(2), "ingest thread never fired"
    assert len(cap.rows) == 1

    # The ingest ran on a DIFFERENT thread than the caller.
    assert cap.thread_id != caller_thread, (
        "ingest ran on the caller's thread — it must be off the critical path"
    )

    # The screenshot_blob was forwarded.
    row = cap.rows[0]
    assert row["screenshot_blob"] == b"ASYNC_SHOT"
    assert row["event_type"] == "tool_execution"
    assert row["outcome"] == "success"



