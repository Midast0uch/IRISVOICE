"""A step that FAILS is typed: its case, BUG/OBSTACLE, DEAD_END and RECALL_MISLED reach the store.

Hidden failure (measured 2026-11-15 on the live store, read-only): memory_events holds 61,230 rows and
NONE of BUG, OBSTACLE, DEAD_END, FIX, ATTEMPT, RESOLUTION or RECALL_MISLED; memory_cases has never had a
row. Not the encryption, not the native writer, not logging: record_step has ONE caller, inside
`_der_finalize_step`, and a step that fails after its retry leaves through `_der_handle_step_failure`,
which SKIPS finalize (finalize.py: "the shared helper is only reached for successful steps"). The
failure road never typed anything; the failure labels existed only in a test that called record_step
by hand.

Pinned here: both roads settle a step through the ONE helper `_der_record_step_event` (kernel/base.py),
the failure road really calls it with success False / verified FAILED / the error text, and the typed
rows land through the live path (event_emit lane job -> lane connection on an ENCRYPTED temp store ->
record_step). Also pinned: records from backend.memory.* loggers reach a root handler, because the
live log looked silent for the wrong reason (no failure ever ran, so no warning was ever logged).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from backend.tests._kernel_source import kernel_function_source

ERR = "step stopped: only 13 of 24 shard files read\n\nActions:\n- read_file kv/shard-01.kv -> FAILED"


def _item(tool="read_file", step_id="s1", trace="rt-aaaa"):
    return SimpleNamespace(
        step_id=step_id, step_number=1, description="read the shards", tool=None, params=None,
        node_call_log=[{"tool": tool, "target": "kv/shard-01.kv", "ok": False,
                        "args": {"path": "kv/shard-01.kv"}}],
        recall_trace_ids=[trace], error_type="", is_subloop=False, expected_output="")


# -- the structural cause: both roads use the one helper ------------------------------------------

def test_the_finalize_road_and_the_failure_road_both_type_through_the_one_helper():
    fin = kernel_function_source("_der_finalize_step")
    fail = kernel_function_source("_der_handle_step_failure")
    assert "_der_record_step_event(" in fin
    assert "_der_record_step_event(" in fail, "the failure road must type the failed step"
    assert '"record_step"' not in fin and '"record_step"' not in fail, \
        "the call is built in ONE place (kernel/base.py _der_record_step_event)"


def test_the_failure_road_calls_record_step_with_the_failure(monkeypatch):
    import backend.agent.kernel.base as base
    from backend.agent.agent_kernel import AgentKernel

    seen = []
    monkeypatch.setattr(base, "_memory_events_submit", lambda owner, fn, **kw: seen.append((fn, kw)))

    class Queue:
        def mark_failed(self, step_id):
            pass

        def abort_descendants(self, step_id):
            return []

    standin = SimpleNamespace()
    try:
        AgentKernel._der_handle_step_failure(standin, _item(), Queue(), SimpleNamespace(), "sess", "turn",
                                             None, step_result=ERR)
    except Exception:  # noqa: BLE001 - the recovery after the typing needs a real kernel
        pass
    assert len(seen) == 1, "the failed step must be typed exactly once"
    fn, kw = seen[0]
    assert fn == "record_step"
    assert kw["success"] is False and kw["verified"] == "FAILED"
    assert kw["tool"] == "read_file" and kw["params"] == {"path": "kv/shard-01.kv"}
    assert kw["thread_id"] == "sess" and kw["task_id"] == "sess:turn" and kw["step_id"] == "s1"
    assert kw["error_text"] == ERR and kw["recall_trace_ids"] == ["rt-aaaa"]


# -- the live path: lane job -> lane connection on an encrypted store -> record_step -----------------

def test_a_failed_step_writes_its_case_and_its_failure_labels_through_the_live_path(tmp_path):
    pytest.importorskip("sqlcipher3")
    from backend.agent import event_emit
    from backend.agent.kernel.base import _der_record_step_event
    from backend.core.biometric import set_session_memory_key
    from backend.memory import memory_events as me
    from backend.memory.db import open_encrypted_memory
    from backend.utils.durability_queue import lane

    key = b"\x05" * 32
    set_session_memory_key(key)          # what the running app holds: the lane opens its own connection
    try:
        db = str(tmp_path / "memory.db")
        conn = open_encrypted_memory(db, key)
        me.ensure_schema(conn)
        owner = SimpleNamespace(conversation_id="conv-1", session_id="s1", _turn_session_id=None,
                                _memory_interface=SimpleNamespace(_mycelium=SimpleNamespace(conn=conn)))
        _der_record_step_event(owner, _item("run_command", "s1", "rt-1"), ERR, False, "FAILED", "s1", "turnA")
        _der_record_step_event(owner, _item("read_file", "s2", "rt-2"), ERR, False, "FAILED", "s1", "turnB")
        assert lane("memory_events").flush(120.0)
        check = open_encrypted_memory(db, key)
        labels = {r[0]: r[1] for r in check.execute("SELECT label, COUNT(*) FROM memory_events GROUP BY label")}
        cases = check.execute("SELECT tool, status, open_task FROM memory_cases ORDER BY tool").fetchall()
    finally:
        set_session_memory_key(None)
    assert labels.get("BUG") == 1 and labels.get("OBSTACLE") == 1, labels   # a coding tool says BUG
    assert labels.get("RECALL_MISLED") == 2, labels                          # one per delivered recall (a trace is credited once)
    assert [c[0] for c in cases] == ["read_file", "run_command"] and {c[1] for c in cases} == {"open"}


# -- logging: backend.memory.* reaches a root handler ---------------------------------------------------

def test_backend_memory_loggers_reach_the_root_handler_that_feeds_iris_log():
    """The live log (logs/iris.log) is fed by LogManagerHandler on the ROOT logger. Records from the
    memory_events logger must pass through it at WARNING and INFO, with root's level as set by
    LogManager.attach_to_root (DEBUG)."""
    from backend.monitor.logs import LogManagerHandler

    got = []
    handler = LogManagerHandler(SimpleNamespace(log=lambda level, source, msg: got.append((level, msg))))
    root = logging.getLogger()
    old = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        lg = logging.getLogger("backend.memory.memory_events")
        lg.warning("[memory_events] probe warning %s", 1)
        lg.info("[memory_events] probe info")
    finally:
        root.removeHandler(handler)
        root.setLevel(old)
    assert ("WARNING", "[memory_events] probe warning 1") in got
    assert ("INFO", "[memory_events] probe info") in got
