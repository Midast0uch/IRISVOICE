"""Ledger contract: the single-writer rule with the REAL bridge code.

Stubs ffi_ingest_event; calls the real AgentToolBridge._record_tool_event /
record_decision; asserts the decision block rides the row and route-only
rows behave. Catches double-record regressions at the interface, before any
behavioral run.
"""

from __future__ import annotations

import json
import threading

import backend.agent.tool_bridge as tb
from backend.agent.tool_bridge import AgentToolBridge


class _Capture:
    def __init__(self):
        self.rows = []
        self.done = threading.Event()

    def ingest(self, **kw):
        kw["payload_json"] = json.loads(kw["payload_json"])
        self.rows.append(kw)
        self.done.set()


def _cap(monkeypatch) -> _Capture:
    cap = _Capture()
    import backend.gateway.iris_ffi as ffi
    monkeypatch.setattr(ffi, "ffi_ingest_event", cap.ingest)
    return cap


META = {
    "engine": "bt-350m", "consumer_id": "tool_choice", "route": "engine",
    "chosen": "read_file", "confidence": 0.97, "candidates": 4,
    "threshold": 0.85, "args_valid": True, "retried": False,
    "escalated": False, "engine_latency_ms": 3, "decision_latency_ms": 11,
    "secret_blob": "must-not-survive",   # whitelist drops unknown keys
}


def test_execution_row_carries_decision_block(monkeypatch):
    cap = _cap(monkeypatch)
    bridge = AgentToolBridge()
    tb._DECISION_META.set(META)
    try:
        bridge._record_tool_event("s1", "read_file", "success",
                                  {"path": "x"}, {"success": True})
    finally:
        tb._DECISION_META.set(None)
    assert cap.done.wait(2), "ingest thread never fired"
    assert len(cap.rows) == 1
    decision = cap.rows[0]["payload_json"]["decision"]
    assert decision["route"] == "engine"
    assert decision["confidence"] == 0.97
    assert "secret_blob" not in decision          # whitelist enforced
    assert len(decision) <= 12                    # bounded field set


def test_legacy_row_has_no_decision_block(monkeypatch):
    cap = _cap(monkeypatch)
    bridge = AgentToolBridge()
    tb._DECISION_META.set(None)
    bridge._record_tool_event("s1", "read_file", "success", {}, {})
    assert cap.done.wait(2)
    assert "decision" not in cap.rows[0]["payload_json"]  # absent, not null


def test_route_only_row_once(monkeypatch):
    cap = _cap(monkeypatch)
    bridge = AgentToolBridge()
    bridge.record_decision(META, kind="reason", session_id="s1")
    assert cap.done.wait(2)
    assert len(cap.rows) == 1
    row = cap.rows[0]
    assert row["payload_json"]["tool"] == "no_tool"
    assert row["payload_json"]["result"]["success"] is None
    assert row["payload_json"]["decision"]["route"] == "engine"
    # meta hygiene: context var is cleared for the next call
    assert tb._DECISION_META.get() is None
