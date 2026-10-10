"""The Oracle's frame must render the evidence its consumers carry (2026-10-10).

WHY THIS FILE EXISTS

Measured live (data/memory.db, d1-3b-ad-q4_k_m, after the research + coding
groups of 2026-10-10): web_intent 88.5% parity, user_feedback 100%, while
presentation sat at 0/5, narration 43%, tool_choice ~50%. The difference is not
the model - it is WHAT THE MODEL WAS ALLOWED TO READ. ``job_input`` renders
ONLY the job's DECLARED fields; every other frame key is silently dropped.

Three defects of that class, each pinned here:

1. PRESENTATION RENDERED AN EMPTY STATE. Its frame carries content_chars,
   has_structure, card_already_rendered, zone, mode - but the `shape` job
   declared only ``goal``, which the frame never had. d1 answered "which
   surface" with ZERO evidence (0/5 parity).
2. NARRATION'S REFERENCE-DETERMINING NUMBERS WERE INVISIBLE. The reference is
   "speak_all iff beats" and the frame carried beats_authored/beats_admitted -
   undeclared, so never rendered.
3. THE ROUTE JOB DROPPED ITS CONSUMERS' EVIDENCE. tool_choice's resolve frame
   (task_class, previous_chosen/outcome, step_index, vision fields) and
   recovery_strategy's frame (ruled_out, error_snippet - the most predictive
   signal for a recovery choice) never reached the model.

Plus the async-boundary defect that killed the tc-frame-v2 fix before it ever
fired: ``record_shadow_tool_choice(async_=True)`` re-invoked itself on a thread
WITHOUT ``last_result`` in the kwargs - and async is the only mode both live
callers use - so every "v2" row measured the BLIND frame under the enriched
stamp. And the mode row-path defect: the lane job only EXPOSED the row on
``last_mode_shadow`` for a kernel forward that ran before the lane did, so in
a one-turn conversation the row was never written (1,109 gliner rows end
2026-10-06, zero since).
"""

from __future__ import annotations

import time

import pytest

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
    job_input,
)


class _Engine:
    model_id = "frame-stub"

    def __init__(self):
        self.counters = EngineCounters()
        self.frames: list = []

    def decide(self, consumer_id, options, frame):
        self.frames.append(dict(frame))
        return DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.5,
            distribution=tuple(CandidateScore(o, -0.1, 0.1) for o in options),
            engine_latency_ms=1,
        )


class _Bridge:
    def __init__(self):
        self.rows: list = []

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.rows.append(dict(meta))


class _Router:
    def generate(self, role, messages, **kwargs):
        return ("", "", [])


def _box(engine):
    from backend.agent.tool_decision import ToolDecisionBox

    return ToolDecisionBox(
        router=_Router(), tool_bridge=_Bridge(),
        get_available_tools=lambda: [
            {"name": n, "category": "filesystem"} for n in (
                "read_file", "edit_file", "write_file", "grep_files",
                "run_command")
        ],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


# ── 1. the async boundary must preserve last_result ──────────────────────


def test_async_shadow_passes_last_result():
    """async_=True is the ONLY mode both live callers use; the thread kwargs
    must carry last_result or the enriched frame never fires (the tc-frame-v2
    defect: every v2 row measured the blind frame)."""
    eng = _Engine()
    _box(eng).record_shadow_tool_choice(
        goal="fix the failing test in utils.py",
        observed_tool="edit_file",
        candidates=["read_file", "edit_file", "run_command"],
        last_result="pytest: 1 failed - AssertionError at line 42",
        async_=True,
    )
    deadline = time.monotonic() + 5.0
    while not eng.frames and time.monotonic() < deadline:
        time.sleep(0.02)
    assert eng.frames, "the async shadow never ran"
    assert eng.frames[0].get("last_result") == (
        "pytest: 1 failed - AssertionError at line 42"), (
        "last_result was dropped at the async boundary - the engine scored "
        "the blind frame")


def test_sync_shadow_row_carries_frame_v3_stamp():
    """The stamp separates the genuinely-enriched frame (v3) from the v2 rows
    that measured the blind frame; never blend cohorts."""
    eng = _Engine()
    row = _box(eng).record_shadow_tool_choice(
        goal="fix the failing test in utils.py",
        observed_tool="edit_file",
        candidates=["read_file", "edit_file", "run_command"],
        last_result="pytest output",
    )
    assert row is not None
    assert row["criteria_version"] == "tc-frame-v3"


# ── 2. the shape job must render its consumers' evidence ─────────────────


def test_presentation_frame_renders_summary_evidence():
    """The kernel's presentation frame has NO goal - before the fix this
    rendered to an EMPTY state and d1 answered with zero evidence (0/5)."""
    state = job_input("presentation", {
        "content_chars": "medium",
        "has_structure": True,
        "card_already_rendered": False,
        "zone": "chat",
        "mode": "personal",
    })
    assert "content_chars: medium" in state.text
    assert "has_structure: True" in state.text
    assert state.text, "presentation rendered an empty state"


def test_narration_frame_renders_beat_counts():
    """The reference is speak_all iff beats; the beat counts decide it, so the
    model must see them."""
    state = job_input("narration", {
        "goal": "NARRATE: fix the login bug",
        "steps": 3,
        "beats_authored": 2,
        "beats_admitted": 2,
        "multi_segment": True,
    })
    assert "beats_authored: 2" in state.text
    assert "beats_admitted: 2" in state.text


# ── 3. the route job must render its consumers' evidence ──────────────────


def test_route_frame_renders_recovery_evidence():
    """error_snippet is the most predictive signal for a recovery choice."""
    state = job_input("recovery_strategy", {
        "goal": "recover from run_command failure",
        "ruled_out": ["run_command"],
        "error_snippet": "exit code 1: file not found",
    })
    assert "error_snippet: exit code 1: file not found" in state.text
    assert "ruled_out" in state.text


def test_route_frame_renders_tool_choice_history():
    """The resolve frame's task_class and previous outcome must reach the
    model, not die in the frame."""
    state = job_input("tool_choice", {
        "goal": "fix the off-by-one error",
        "task_class": "coding",
        "previous_chosen": "read_file",
        "previous_outcome": "success",
        "step_index": 2,
        "needs_vision": False,
    })
    assert "task_class: coding" in state.text
    assert "previous_outcome: success" in state.text


# ── 4. the mode lane job must WRITE the row, not only expose it ────────────


def test_mode_lane_row_reaches_sink(monkeypatch):
    """The lane job used to only set last_mode_shadow for a kernel forward
    that runs BEFORE the lane - in a one-turn conversation the row was never
    written (measured: zero mode rows after 2026-10-06)."""
    from backend.agent.mode_detector import ModeDetector

    md = ModeDetector()
    md.set_mode_engine(_ModeEngine())
    sink_rows: list = []
    md.set_row_sink(sink_rows.append)
    md._shadow_mode_async("research the websocket rfc", _kw_mode("research"))
    from backend.utils.durability_queue import lane

    lane("oracle_shadow").flush(10.0)
    assert sink_rows, (
        "the lane job did not write the row through the sink - it was only "
        "exposed for a forward that already ran")
    assert sink_rows[0]["consumer_id"] == "mode"


def _kw_mode(value):
    from backend.agent.mode_detector import AgentMode

    return AgentMode(value)


class _ModeEngine:
    model_id = "mode-stub"

    def decide(self, consumer_id, options, frame):
        return DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.9,
            distribution=tuple(CandidateScore(o, -0.1, 0.1) for o in options),
            engine_latency_ms=1,
        )
