"""Contract tests: recovery evidence shape (REQ-11 AC11.1/AC11.5, T14).

CT-DEI-5 — Recovery Evidence Shape: the graft failure evidence
(``failed_tool``, ``error_snippet``) reaches the engine frame as ``ruled_out``,
and the decision meta carries the recovery join keys.

T14 REMAINDER (session 357): the box-side seam above was landed, but nothing in
the DER ever CALLED it — `grep -rn "resolve(" backend/agent/*.py | grep -i
failure` returned zero hits. The tests at the bottom of this file pin the
CALLER side, which lives in ``_der_handle_step_failure`` (the one failure-triage
seam). Without them T14 and REQ-17 are inert and the rows never accumulate.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.tool_decision import ToolDecisionBox

import pytest

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the
# real enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ('tool_choice', 'recovery_strategy')
pytestmark = pytest.mark.usefixtures("oracle_decides_module")

_REPO_ROOT = Path(__file__).resolve().parents[3]


MENU = [
    {"name": "search", "description": "instant lookup", "category": "web"},
    {"name": "crawler_query", "description": "deep crawl", "category": "web"},
    {"name": "speak", "description": "speak", "category": "system"},
]


class _RecordingEngine:
    """Records the frame it was asked to score."""

    def __init__(self, chosen="search", confidence=0.95):
        self._chosen = chosen
        self._conf = confidence
        self.model_id = "rec-stub"
        self.counters = EngineCounters()
        self.frames: list = []

    def decide(self, consumer_id, options, frame):
        self.frames.append(dict(frame))
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.05)
                for o in options
            ),
            engine_latency_ms=2,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        class _R:
            retried = False
            args = {"query": "x"}
        return _R()


def _box(engine) -> ToolDecisionBox:
    return ToolDecisionBox(
        router=SimpleNamespace(),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: MENU,
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestRuledOutInFrame:
    def test_ruled_out_in_frame(self):
        """AC11.1: the failure evidence rides the engine frame as `ruled_out`."""
        engine = _RecordingEngine()
        box = _box(engine)

        box.resolve(
            {"description": "recover the price lookup", "task_class": "full"},
            session_id="s1", conversation_id="c1",
            failure={"failed_tool": "crawler_query",
                     "error_snippet": "upstream timeout"},
        )

        assert engine.frames, "the engine was never asked to score"
        frame = engine.frames[0]
        assert frame["ruled_out"] == ["crawler_query"], frame.get("ruled_out")

    def test_no_failure_evidence_means_an_empty_veto(self):
        """REQ-11 edge: a normal step is byte-identical to today — empty veto."""
        engine = _RecordingEngine()
        box = _box(engine)

        box.resolve({"description": "just a normal step", "task_class": "full"},
                    session_id="s1", conversation_id="c1")

        assert engine.frames[0]["ruled_out"] == []

    def test_veto_survives_reset_failure_counters(self):
        """AC11.2: the DER calls reset_failure_counters() on every _split_step —
        a veto that a split erases is how recovery re-picks the failed tool."""
        engine = _RecordingEngine()
        box = _box(engine)

        box.resolve(
            {"description": "recover the lookup", "objective_anchor": "OBJ-1"},
            session_id="s1", conversation_id="c1",
            failure={"failed_tool": "crawler_query"},
        )
        box.reset_failure_counters()
        engine.frames.clear()

        # The graft step resolves WITHOUT re-reporting the failure. Its goal
        # differs (a graft has its own description), so the engine cache misses
        # and the frame is rebuilt from the surviving seed veto.
        d = box.resolve(
            {"description": "recover the lookup by another route",
             "objective_anchor": "OBJ-1"},
            session_id="s1", conversation_id="c1",
        )

        assert engine.frames, "the graft step never reached the scorer"
        assert engine.frames[0]["ruled_out"] == ["crawler_query"], (
            "the veto was lost by reset_failure_counters — recovery can "
            "re-pick the tool that just failed"
        )
        # and it did not win
        assert d.tool == "search"


class TestMetaCarriesRecoveryFields:
    def test_meta_carries_recovery_fields(self):
        """AC11.5: `failed_tool` and `recovery_strategy` are recorded on the
        decision meta so calibration can join them."""
        engine = _RecordingEngine(chosen="search")
        box = _box(engine)

        d = box.resolve(
            {"description": "recover the lookup", "task_class": "full"},
            session_id="s1", conversation_id="c1",
            failure={"failed_tool": "crawler_query",
                     "error_snippet": "upstream timeout"},
        )

        assert d.meta["failed_tool"] == "crawler_query"
        assert "recovery_strategy" in d.meta
        assert d.meta["ruled_out"] == ["crawler_query"]
        # the vetoed tool did not win
        assert d.tool == "search"


# ── T14 remainder (session 357): the CALLER side must be wired ─────────────


def _kernel_source() -> str:
    return (_REPO_ROOT / "backend" / "agent" / "agent_kernel.py").read_text(
        encoding="utf-8", errors="replace")


def _attr_calls_in(tree: ast.AST, func_name: str) -> set:
    """Every attribute-call name made anywhere inside the named function."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return {
                n.func.attr
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
    return set()


class TestFailureTriageSeamWired:
    def test_note_failure_seeds_the_veto_for_a_graft_child(self):
        """AC11.1/AC11.2: the DER's failure handler seeds the veto through
        `note_failure` — a path that never calls `resolve(failure=...)` — and
        the veto survives the split that follows a failure."""
        engine = _RecordingEngine()
        box = _box(engine)

        box.note_failure(objective="OBJ-GRAFT", failed_tool="crawler_query")
        box.reset_failure_counters()   # the DER calls this on every split

        d = box.resolve(
            {"description": "recover the lookup by another route",
             "objective_anchor": "OBJ-GRAFT"},
            session_id="s1", conversation_id="c1",
        )

        assert engine.frames, "the graft step never reached the scorer"
        assert engine.frames[0]["ruled_out"] == ["crawler_query"], (
            "a veto seeded by note_failure did not reach the frame — the "
            "graft can re-pick the tool that just failed"
        )
        assert d.tool == "search"

    def test_note_failure_is_a_noop_without_a_tool_or_objective(self):
        """A half-specified failure must not create an unreachable veto key."""
        engine = _RecordingEngine()
        box = _box(engine)

        box.note_failure(objective="OBJ-NOOP", failed_tool="")
        box.note_failure(objective="", failed_tool="crawler_query")

        box.resolve({"description": "a normal step",
                     "objective_anchor": "OBJ-NOOP"},
                    session_id="s1", conversation_id="c1")

        assert engine.frames[0]["ruled_out"] == []

    def test_the_der_failure_seam_calls_the_box(self):
        """The seam must be WIRED, not merely implemented.

        `_der_handle_step_failure` is the ONE failure-triage point (called from
        both loop sites), so this is the only place that needs the consult. The
        resolve() call site must also carry the veto key, or a veto seeded by
        the parent's failure is unreachable for the graft child.
        """
        calls = _attr_calls_in(ast.parse(_kernel_source()),
                               "_der_handle_step_failure")

        assert "note_failure" in calls, (
            "the DER failure handler never seeds the veto — T14 is inert"
        )
        assert "recovery_strategy" in calls, (
            "the DER failure handler never consults the triage consumer — "
            "REQ-17 AC17.1's 'each failure triage point' is unmet"
        )
        assert '"objective_anchor": getattr(' in _kernel_source(), (
            "the resolve() call site does not pass the veto key, so a veto "
            "seeded by the parent's failure is unreachable for the graft child"
        )
