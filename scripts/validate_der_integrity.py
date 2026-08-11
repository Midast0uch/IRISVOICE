"""Standing CDD harness â€” DER loop integrity + display (REQ-1..9).

Replays a recorded DER trajectory through the FULL stack and asserts the
contracts + behaviors on EVERY run. This is the gap-finding instrument
from design.md Verification Strategy Tier 4: if we test correctly, we
find the gaps. Runs head-less (no live web, no TTS) and exits non-zero
on any contract/behavior break.

Coverage:
  - REQ-1: ledger records ALL labels (VERIFIED/UNVERIFIED/FAILED)
  - REQ-2: outer-loop compound gate rejects the hack
  - REQ-3: measured-token work_units debit
  - REQ-7: physics-event narration trigger (silent on ordinary step)
   - REQ-8: task:learning event carries real signal
    - REQ-9: narration log records silence + spoken, scoped by conv
    - REQ-5 (supersedes deleted REQ-10): critical failure finalizes honestly —
      marked failed, NO TASK_BLOCKED card / ask_user (the old REQ-10
      escalation was removed; the long-horizon spec replaces it with honest
      partial finalization)

Run:  python scripts/validate_der_integrity.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import sqlite3

# Make the backend importable when run from repo root or backend/.
# backend is a package under the REPO ROOT (C:\dev\IRISVOICE), so the
# repo root (not backend/) must be on sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if os.path.isdir(os.path.join(_REPO, "backend")):
    sys.path.insert(0, _REPO)

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.der_constants import (
    AVG_STEP_COST,
    DER_MAX_GRAFTS,
    debit_work_units,
    detect_physics_narration,
)
from backend.agent.event_bus import EventBus, IRISStreamEvent
from backend.agent.outer_loop import OuterTuner


class _Failures:
    def __init__(self):
        self.items = []

    def check(self, name, cond):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            self.items.append(name)


def _recorded_trajectory():
    """A small recorded DER trajectory: 3 steps, mixed labels."""
    return [
        {"step_id": "s1", "label": "VERIFIED", "tokens": 3000},
        {"step_id": "s2", "label": "UNVERIFIED", "tokens": 1500},
        {"step_id": "s3", "label": "FAILED", "tokens": 750},
    ]


def validate_req1_ledger(fail, rec):
    print("REQ-1: honest ledger records ALL labels")
    for step in _recorded_trajectory():
        rec.record_commit(
            "sess-harness", step["step_id"], "",
            f"{step['label']} step", verified_label=step["label"],
        )
    rows = rec._conn.execute(
        "SELECT verified_label FROM der_commits ORDER BY step_id"
    ).fetchall()
    labels = [r[0] for r in rows]
    fail.check("all 3 labels recorded", labels == ["VERIFIED", "UNVERIFIED", "FAILED"])
    fail.check("FAILED not dropped", "FAILED" in labels)


def validate_req2_compound_gate(fail):
    print("REQ-2: compound outer-loop gate rejects the hack")
    bus = EventBus()
    rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
    # Seed healthy held-out: 5/6 natural exits (rate ~0.833, < 1.0
    # so a +0.05 raise is a REAL improvement), all verified, low tokens.
    for i in range(6):
        rec.record_session_exit(
            f"s{i}", "general", natural_exit=(i < 5),
            verified_count=5, tokens_total=5000,
        )
    tuner = OuterTuner(recorder=rec, held_out_count=3)
    baseline = tuner._score(tuner._heldout_batch(tuner._ledger()["exits"]))
    # Hack: raise natural_exit_rate but degrade verified_fraction.
    hacked = dict(baseline)
    hacked["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.1)
    hacked["verified_fraction"] = baseline["verified_fraction"] - 0.5
    fail.check("hack rejected", tuner._compound_accepts(hacked, baseline) is False)
    # Genuine improvement accepted.
    genuine = dict(baseline)
    genuine["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.05)
    fail.check("genuine accepted", tuner._compound_accepts(genuine, baseline) is True)


def validate_req3_work_units(fail):
    print("REQ-3: measured-token work_units debit")
    fail.check("small step costs 1", debit_work_units(10, 200) == 9)
    fail.check("large step costs 3", debit_work_units(10, 3 * AVG_STEP_COST) == 7)
    fail.check("never negative", debit_work_units(0, 10**6) == 0)


def validate_req7_narration(fail):
    print("REQ-7: physics-event narration trigger")
    # Ordinary step (oscillating |u|, no children) -> silence.
    fail.check(
        "ordinary step silent",
        detect_physics_narration(0.6, 0.62, 0, False) is None,
    )
    # Split -> speaks.
    line = detect_physics_narration(0.6, 0.6, 2, False)
    fail.check("split speaks", line is not None and "sub-task" in line)
    # Oscillating -> converged transition -> speaks.
    line2 = detect_physics_narration(0.6, 0.95, 0, False)
    fail.check("conv transition speaks", line2 is not None and "answer" in line2)


def validate_req8_event(fail):
    print("REQ-8: task:learning event carries real signal")
    bus = EventBus()
    captured = []

    def _cap(payload):
        captured.append(payload.data)

    bus.subscribe(IRISStreamEvent.TASK_LEARNING, _cap)
    bus.emit(
        IRISStreamEvent.TASK_LEARNING,
        {"session_id": "s", "step_id": "x", "signal": "avoided",
         "verified_label": "FAILED"},
    )
    fail.check("event emitted + captured", len(captured) == 1)
    fail.check("real signal, not narration", captured[0]["signal"] == "avoided")


def validate_req9_log(fail):
    print("REQ-9: narration log records silence + spoken, scoped")
    from backend.agent.narration import NarrationLog

    d = tempfile.mkdtemp()
    log = NarrationLog.__new__(NarrationLog)
    log.conversation_id = "conv-harness"
    log._path = os.path.join(d, "conv-harness.jsonl")
    log._write({"conversation_id": "conv-harness", "decision": "silence",
                "signal": None, "u": 0.6, "xi": 0.1, "text": "",
                "tts_played": False})
    log._write({"conversation_id": "conv-harness", "decision": "brief",
                "signal": "retried", "u": 0.62, "xi": 0.3,
                "text": "Now moving into a sub-task.", "tts_played": True})
    import json
    with open(log._path, encoding="utf-8") as fh:
        lines = [l for l in fh if l.strip()]
    fail.check("silence + spoken both logged", len(lines) == 2)
    entries = [json.loads(l) for l in lines]
    fail.check("silence decision present", any(e["decision"] == "silence" for e in entries))
    fail.check("u/xi on structural event", entries[1]["u"] == 0.62)


def validate_req10_escalation(fail):
    """REQ-5 (long-horizon-der-execution) supersedes the deleted REQ-10.

    The old der-loop-integrity-display REQ-10 required a TASK_BLOCKED card +
    ask_user QuestionCard when a critical step failed past the graft budget.
    The long-horizon spec REMOVED that escalation (agent_kernel.py:7384-7398
    documents the supersession verbatim): "the task does NOT block on a
    TASK_BLOCKED card / ask_user QuestionCard (that escalation came from the
    deleted der-loop-integrity-display REQ-10; the long-horizon spec
    supersedes it: 'IF budget ends before completion THEN emit remaining
    nodes and their last failure class')".

    This harness section therefore pins the REQ-5 contract:
      - the critical step IS marked failed (honest partial finalization);
      - NO TASK_BLOCKED event and NO ask_user call are emitted (the old
        escalation is gone — pinned so it cannot silently return);
      - a result that classifies as a transport/envelope error is NOT split
        (REQ-5 AC2: "not split solely because a transport or envelope error
        hid usable evidence") — grafts stay bounded.
    """
    print("REQ-5: critical failure finalizes honestly, no blocking card "
          "(supersedes deleted REQ-10 escalation)")
    from types import SimpleNamespace

    from backend.agent.der_loop import DirectorQueue, QueueItem
    from backend.agent.agent_kernel import AgentKernel

    asked = []
    blocked = []

    class _StubKernel:
        def __init__(self):
            self._der_work_units = 10

        def _der_live_cad_state(self, session):
            return {"u": 0.3, "xi": 0.1}

        def _split_step(self, item, reason, cad, wu):
            return [
                QueueItem(
                    step_id=f"{item.step_id}_c{j}", step_number=item.step_number + j,
                    description=f"recovery {j}", tool=None, critical=False,
                    objective_anchor=item.objective_anchor,
                )
                for j in range(2)
            ]

        def get_ask_user_tool(self):
            fake = SimpleNamespace()

            def _ask(text, options=None, **kw):
                asked.append({"text": text, "options": list(options or [])})

            fake.ask = _ask
            return fake

    # Intercept the bus + ask_user tool so we can DETECT any escalation.
    import backend.agent.event_bus as _eb
    import backend.agent.tools.ask_user_tool as _aut

    _orig_bus = getattr(_eb, "get_event_bus", None)
    _orig_ask = getattr(_aut, "get_ask_user_tool", None)

    def _fake_bus():
        bus = SimpleNamespace()

        def _emit(event, data=None, **kw):
            _val = getattr(event, "value", str(event))
            if _val == "task:blocked":
                blocked.append(data or {})

        bus.emit = _emit
        return bus

    def _fake_ask():
        f = SimpleNamespace()

        def _ask(text, options=None, **kw):
            asked.append({"text": text, "options": list(options or [])})

        f.ask = _ask
        return f

    _eb.get_event_bus = _fake_bus
    _aut.get_ask_user_tool = _fake_ask
    try:
        kern = _StubKernel()
        queue = DirectorQueue(
            objective="complete the task",
            items=[QueueItem(
                step_id="s1", step_number=1, description="do the critical thing",
                tool="run_command", params={}, critical=True,
                objective_anchor="complete the task",
            )],
        )
        item = queue.items[0]
        for _ in range(DER_MAX_GRAFTS + 1):
            AgentKernel._der_handle_step_failure(
                kern, item, queue, plan=None,
                _session="sess-req10", _turn_id="t1", context_package=None,
            )
            if item.step_id in queue.completed_ids:
                queue.completed_ids.remove(item.step_id)

        # REQ-5: the step IS marked failed (honest partial finalization).
        fail.check("critical step marked failed", item.step_id in queue.failed_ids)
        # The old REQ-10 escalation is GONE — no blocking card, no question.
        fail.check("no TASK_BLOCKED event (REQ-10 removed)", len(blocked) == 0)
        fail.check("no ask_user call (REQ-10 removed)", len(asked) == 0)
        # REQ-5 AC2: an empty/envelope result is NOT split (grafts bounded).
        fail.check(
            "envelope-error result not split (REQ-5 AC2)",
            queue.graft_attempts == 0,
        )
    finally:
        if _orig_bus is not None:
            _eb.get_event_bus = _orig_bus
        else:
            delattr(_eb, "get_event_bus")
        if _orig_ask is not None:
            _aut.get_ask_user_tool = _orig_ask
        else:
            delattr(_aut, "get_ask_user_tool")


def validate_req18_trace(fail):
    """REQ-18: the correlated per-task trace is complete on every replay.

    Populates the trace the same way the DER kernel's hooks do (verify /
    verify_label / synthesis / revision / steering / navigation) and asserts
    every signal is present and shaped correctly — bounded, redacted,
    off the critical path.
    """
    print("REQ-18: correlated per-task trace complete")
    from backend.agent.der_trace import clear_traces, get_der_trace

    clear_traces()
    try:
        trace = get_der_trace("sess-req18")

        # AC1: scorer tag + score + verified label (T19).
        trace.record("verify", scorer_tag="semantic", score=0.91)
        trace.record("verify", scorer_tag="fallback", score=0.55)
        trace.record(
            "verify_label", verified_label="VERIFIED",
            step_id="s1", step_number=1, tool="crawler_query",
        )

        # AC2: synthesis path (T20).
        trace.record("synthesis", path="success", ran=True)
        trace.record("synthesis", path="deterministic_failure", ran=False)

        # AC3: revision origin (T23).
        trace.record("revision", origin="sub_loop_split", children=2)
        trace.record("revision", origin="user_steering", boundary_step=2)

        # AC4: steering ack + applied boundary (T25/T26).
        trace.record(
            "steering", channel="steer", message_id="m1",
            ack="considered", boundary_step=2,
        )

        # AC5: navigation surface + job_id + HAR (T27).
        trace.record(
            "navigation", tool="open_url", surface="in-app",
            url="https://example.com/x",
            job_id="job-1", har_path="data/har/job-1.har",
        )

        # All six signals present.
        for sig in ("verify", "verify_label", "synthesis", "revision",
                    "steering", "navigation"):
            fail.check(f"trace has {sig}", trace.has_signal(sig))

        # AC1 shape: scorer tags are the canonical vocabulary.
        tags = {e.get("scorer_tag") for e in trace.entries("verify")}
        fail.check("scorer tags semantic+fallback", tags == {"semantic", "fallback"})

        # AC2 shape: synthesis ran flag is boolean + path known.
        syn_paths = {e.get("path") for e in trace.entries("synthesis")}
        fail.check(
            "synthesis paths recorded",
            syn_paths == {"success", "deterministic_failure"},
        )

        # AC3 shape: both revision origins distinguished.
        origins = {e.get("origin") for e in trace.entries("revision")}
        fail.check(
            "revision origins distinguished",
            origins == {"sub_loop_split", "user_steering"},
        )

        # AC4 shape: steering carries ack + boundary.
        steer = trace.entries("steering")[-1]
        fail.check("steering acked", steer.get("ack") == "considered")
        fail.check("steering boundary present", steer.get("boundary_step") is not None)

        # AC5 shape: navigation surface in-app + job_id/HAR carried.
        nav = trace.entries("navigation")[-1]
        fail.check("nav surface in-app", nav.get("surface") == "in-app")
        fail.check("nav job_id carried", nav.get("job_id") == "job-1")
        fail.check("nav har_path carried", nav.get("har_path") == "data/har/job-1.har")

        # Bounded + redacted: a flood of long entries is capped and truncated.
        long = "z" * 5000
        for _ in range(900):
            trace.record("verify", scorer_tag="semantic", score=0.5, result=long)
        fail.check("trace bounded", trace.count() <= 500)
        fail.check(
            "trace redacted",
            all(len(e.get("result", "")) <= 313 for e in trace.entries("verify")),
        )
    finally:
        clear_traces()


def main() -> int:
    print("=" * 64)
    print("DER LOOP INTEGRITY + DISPLAY â€” STANDING CDD HARNESS")
    print("=" * 64)
    fail = _Failures()
    rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))

    validate_req1_ledger(fail, rec)
    validate_req2_compound_gate(fail)
    validate_req3_work_units(fail)
    validate_req7_narration(fail)
    validate_req8_event(fail)
    validate_req9_log(fail)
    validate_req10_escalation(fail)
    validate_req18_trace(fail)

    print("-" * 64)
    if fail.items:
        print(f"HARNESS FAILED: {len(fail.items)} check(s) broken")
        for name in fail.items:
            print(f"  - {name}")
        return 1
    print("HARNESS PASSED: all DER integrity + display contracts hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
