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
stamp. (The mode row-path defect of the same class - the lane job only EXPOSED
the row for a kernel forward that ran before the lane did - was pinned here
until the `mode` consumer was REMOVED 2026-10-10, owner; its test went with
the consumer. STALE-BY-SPEC.)
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


def test_sync_shadow_row_carries_the_frame_stamp():
    """The stamp separates the genuinely-enriched frames from every earlier
    cohort (v2 was accidentally blind; v3 added last_result; v4 adds the
    option-line descriptions); never blend cohorts."""
    eng = _Engine()
    row = _box(eng).record_shadow_tool_choice(
        goal="fix the failing test in utils.py",
        observed_tool="edit_file",
        candidates=["read_file", "edit_file", "run_command"],
        last_result="pytest output",
    )
    assert row is not None
    # STALE-BY-SPEC update (2026-10-11): v5 added the step's own calls and
    # done-when; v6 makes the option lines the tools' decision lines - each a
    # new cohort. The row also carries the replay keys and the menu fingerprint.
    # v7 (2026-10-11): + step_facts (files named: exists / read / changed).
    # v8: + files seen in the last result, + paged-read counts.
    assert row["criteria_version"] == "tc-frame-v8"
    assert row["state"].startswith("fix the failing test in utils.py")
    assert isinstance(row["menu_fp"], str) and len(row["menu_fp"]) == 10


def test_async_shadow_carries_the_steps_own_calls_and_done_when():
    """tc-frame-v5 (2026-10-11): the step's own calls so far and its done-when
    must survive the async boundary (the v2 lesson: a parameter not on the
    thread kwargs is silently dropped) AND render into the route state."""
    eng = _Engine()
    _box(eng).record_shadow_tool_choice(
        goal="fix the failing test in utils.py",
        observed_tool="run_command",
        candidates=["read_file", "edit_file", "run_command"],
        last_result="edit applied",
        calls_this_step="read_file utils.py ok; edit_file utils.py ok",
        done_when="pytest passes",
        source="der_node",
        async_=True,
    )
    deadline = time.monotonic() + 5.0
    while not eng.frames and time.monotonic() < deadline:
        time.sleep(0.02)
    assert eng.frames, "the async shadow never ran"
    f = eng.frames[0]
    assert f.get("calls_this_step") == "read_file utils.py ok; edit_file utils.py ok"
    assert f.get("done_when") == "pytest passes"
    assert f.get("source") == "der_node"
    text = job_input("tool_choice", f).text
    for needle in ("calls_this_step: read_file utils.py ok", "done_when: pytest passes",
                   "last_result: edit applied"):
        assert needle in text, f"declared route field not rendered: {needle}"


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


def test_dynamic_menu_criteria_travel_but_never_render_into_the_state():
    """A dynamic menu's option descriptions (tool_choice's varies per turn)
    ride the OracleState and NEVER render into the state text - the backend
    puts them in the OPTION LINES, beside the codes (measured live: 5/5
    tool questions with descriptions, 5/6 with bare names)."""
    state = job_input("tool_choice", {
        "goal": "fix the failing test",
        "option_criteria": {
            "read_file": "Read a file's contents",
            "run_command": "Run a shell command",
        },
    })
    assert "Read a file's contents" not in state.text, (
        "option criteria leaked into the state text")
    assert state.option_criteria == (
        ("read_file", "Read a file's contents"),
        ("run_command", "Run a shell command"),
    )


def test_dynamic_menu_criteria_render_into_the_option_lines():
    """The backend renders the state's option_criteria beside the codes,
    overriding the (empty) static declaration for this question only —
    exactly as decide() passes them."""
    from backend.agent.decision_backend_d1 import D1Backend
    from backend.agent.decision_engine import OracleState

    st = OracleState(job="route", fields=("goal",), text="fix the failing test",
                     budget_ids=256,
                     option_criteria=(("read_file", "Read a file's contents"),))
    out = D1Backend._question_choice(
        st, "Which tool should handle this step?",
        dict(st.option_criteria) or None,
        ["read_file", "edit_file"])
    assert "A Read a file's contents" in out
    assert "B edit file" in out  # no description: the label as text


def test_async_shadow_passes_option_criteria():
    """The v2 lesson, applied by construction: EVERY parameter rides the async
    hand-off or the async path silently drops it.

    STALE-BY-SPEC update (2026-10-11): the hand-off moved from a Thread per
    row to the `oracle_shadow` lane (one ordered writer - CLAUDE.md "lanes,
    never a thread per row"); it forwards the `_kw` dict built inside
    record_shadow_tool_choice. The guard is STRONGER now: `_kw` must carry
    EVERY parameter of the function (not only last_result/option_criteria),
    with async_ pinned False."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "backend" / "agent"
           / "tool_decision.py").read_text(encoding="utf-8")
    found = False
    for fn in ast.walk(ast.parse(src)):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "record_shadow_tool_choice"):
            continue
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs} - {"self"}
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                    and any(isinstance(t, ast.Name) and t.id == "_kw" for t in node.targets)):
                continue
            keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
            assert params <= keys, f"the async hand-off drops: {sorted(params - keys)}"
            found = True
    assert found, "the async shadow hand-off (_kw) was not found"
