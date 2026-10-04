"""D1 (HANDOFF 11) - the commit and link writes never hold the answer path.

Live 2026-10-04 (r06, conv-655): a 42 s reply held a 22 s gap with no model or
tool call. The stack dumps showed _der_finalize_step inside
der_links.write_node_links -> PinStore.link, and record_commit, each waiting on
"database is locked" (busy_timeout 5 s, several writers on data/memory.db).

The contract: _der_finalize_step submits both writes to lane("memory_events")
and returns while a writer is blocked; the rows still land once the writer is
free (the lane drains in order). On the old code finalize waits for the
blocked writer, so the first assertion fails.
"""
from __future__ import annotations

import threading
import time

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem
from backend.utils.durability_queue import lane

_RELEASE = threading.Event()


class _LockedRecorder:
    """A commit writer stuck on a locked store until the test releases it."""

    calls: list = []

    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        _RELEASE.wait(20.0)
        _LockedRecorder.calls.append(kwargs)


class _Bus:
    def emit(self, *a, **kw):
        pass


def _stub_kernel() -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-d1-guard"
    k._memory_interface = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu, step_result="": []
    k._verify_step_result = (
        lambda goal, expected, result, tool=None, success=False: "FAILED")
    return k


def test_finalize_returns_while_the_commit_writer_is_blocked(monkeypatch):
    _RELEASE.clear()
    _LockedRecorder.calls = []
    monkeypatch.setattr(_ct_module, "get_trajectory_recorder", lambda mi: _LockedRecorder())
    monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _Bus())
    assert lane("memory_events").flush(10.0)

    k = _stub_kernel()

    def _run_finalize(step_id):
        item = QueueItem(
            step_id=step_id, step_number=1, description="risky action",
            tool="run_command", params={}, critical=False,
            objective_anchor="do the thing", expected_output="done",
        )
        queue = DirectorQueue(objective="do the thing", items=[item])
        queue.mode = ExecutionMode.QUICK
        k._der_finalize_step(
            item=item, step_result="it did not work", step_success=True,
            step_outputs=[], completed_items=[], _tokens_used=0,
            _token_budget=10_000, _session="sess-d1", _turn_id="t1",
            _phase=2, is_mature=False, _live_ctx=None,
            plan=type("P", (), {"original_task": "do the thing"})(),
            context_package=None, queue=queue, verdict=None,
        )

    # Warm-up with a FREE writer: the first finalize in a process loads the
    # Oracle's ONNX session (check_escalation -> decide), which in the app is
    # already warm. The timed run below must measure the write, not that load.
    _RELEASE.set()
    _run_finalize("d1-warm")
    assert lane("memory_events").flush(10.0)
    _RELEASE.clear()
    _LockedRecorder.calls = []
    done = threading.Event()

    def _finalize():
        try:
            _run_finalize("d1-step")
        finally:
            done.set()

    t0 = time.monotonic()
    threading.Thread(target=_finalize, daemon=True).start()
    try:
        # 5 s = SQLite's busy_timeout here: an inline write waits at least that.
        returned = done.wait(5.0)
        assert returned, (
            "_der_finalize_step waited for a blocked commit writer - the write "
            "is on the answer path (D1)")
        assert not _LockedRecorder.calls, "the row lands only after the writer is free"
    finally:
        _RELEASE.set()
    assert lane("memory_events").flush(10.0)
    assert len(_LockedRecorder.calls) == 1, "the commit row still lands, once"
    assert _LockedRecorder.calls[0]["verified_label"] == "FAILED"
    assert time.monotonic() - t0 < 30.0
