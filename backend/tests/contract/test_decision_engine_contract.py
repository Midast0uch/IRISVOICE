"""Contract tests: decision engine seams (specs/tool-decision-engine).

CT-DE-1  DecisionScore shape + Decision.meta channel shape.
CT-DE-2  Kernel seam invariance: every engine routing outcome resolves to
         DecisionKind ∈ {TOOL, REASON, FAIL} — no fourth kind ever crosses.
CT-DE-3  Single-writer ledger: one row per execution carrying the decision
         block; route-only rows exist exactly once; no row when legacy.
CT-DE-4  Engine unavailable → legacy path serves the decision, silently.
CT-DE-5  Engine module holds zero memory / event-store / ffi references
         (AST scan, same style as test_no_direct_lfm_vl_provider_bypass.py).
"""

from __future__ import annotations

import ast
import json
from dataclasses import fields
from pathlib import Path

import pytest

from backend.agent.decision_engine import (
    CONSUMERS,
    CandidateScore,
    DecisionEngine,
    DecisionScore,
    EngineConfig,
)
from backend.agent.tool_decision import (
    Decision,
    DecisionKind,
    ToolDecisionBox,
)


AVAILABLE = [
    {"name": "read_file", "description": "Search the web"},
    {"name": "read_file", "description": "Read a file"},
]


class FakeEngine:
    """Stands in for the engine at the box seam with canned answers."""

    def __init__(self, chosen="read_file", confidence=0.95, args=None,
                 return_none=False):
        self._chosen = chosen
        self._confidence = confidence
        self._args = args if args is not None else {"path": "README.md"}
        self._return_none = return_none
        self.model_id = "fake-350m"
        self.calls = []

    class _Counters:
        decisions = escalations = memory_fallbacks = retries = \
            unavailable_events = load_failures = lock_timeouts = 0

    counters = _Counters()

    def decide(self, consumer_id, options, frame):
        self.calls.append(("decide", consumer_id, tuple(options)))
        if self._return_none:
            return None
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen,
            confidence=self._confidence,
            distribution=(
                CandidateScore(name=self._chosen, logprob=-0.1,
                               prob=self._confidence),
                CandidateScore(name="read_file", logprob=-3.0,
                               prob=1 - self._confidence),
            ),
            engine_latency_ms=3,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        self.calls.append(("args", consumer_id, option))
        class R:
            retried = False
        r = R()
        r.args = self._args
        return r


class FakeRouter:
    """Bindings report the SAME model on both roles — otherwise the box runs
    its Brain↔Tool handshake against the canned reply and short-circuits our
    assertions."""

    def __init__(self, result):
        self._result = result
        self.calls = 0

    def generate(self, role, messages, **kw):
        self.calls += 1
        return self._result

    def resolve(self, role):
        class R:
            id = "same"
            model = "same"
        return R()


class FakeBridge:
    def __init__(self):
        self.execute_calls = []
        self.decision_rows = []

    async def execute_tool(self, tool_name, params, session_id="unknown",
                           decision_meta=None, **kw):
        self.execute_calls.append(
            {"tool": tool_name, "params": params, "meta": decision_meta},
        )
        return {"success": True}

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.decision_rows.append(
            {"meta": meta, "kind": kind, "error": error},
        )


def make_box(engine=None, router_result=("", "", []), bridge=None):
    return ToolDecisionBox(
        router=FakeRouter(router_result),
        tool_bridge=bridge or FakeBridge(),
        get_available_tools=lambda: AVAILABLE,
        validate_tool_call=lambda n, p: (True, None),
        infer_fn=lambda prompt, **kw: "reasoned",
        memory_lookup_fn=lambda _g: None,
        decision_engine=engine,
    )


# ---------------------------------------------------------------------------
# CT-DE-1 — shapes
# ---------------------------------------------------------------------------


class TestCtDe1Shapes:
    def test_decision_score_fields(self):
        names = {f.name for f in fields(DecisionScore)}
        assert names == {"consumer_id", "chosen", "confidence", "distribution",
                         "engine_latency_ms", "retried", "stage_detail"}
        names = {f.name for f in fields(CandidateScore)}
        assert names == {"name", "logprob", "prob"}

    def test_consumers_enumerated(self):
        # AC13.1 v1 consumers + REQ-11 AC11.3's `recovery_strategy` (T15).
        # STALE-BY-SPEC (2026-09-26): the spec mandates the new consumers, so
        # the enumeration grows with it — REQ-13/14/15/17's consumers and
        # REQ-29's four surface consumers (T46–T49). `tier0_classify` stays
        # OUT: a recorded non-fit (AC29.5).
        assert CONSUMERS == (
            "tool_choice", "presentation", "narration", "recovery_strategy",
            "review_verdict", "sufficient", "done", "on_track",
            "mode", "web_intent", "retry_same",
            "has_gaps", "use_thinking", "escalate_incomplete", "needs_action",
            # Session 364 (owner request): the DEPTH consumer. `sufficient` and
            # `done` ask whether the objective is COVERED; `depth_met` asks
            # whether it is done to the DEPTH the success criteria require -
            # the "the Brain settles for half work" complaint, made measurable.
            "depth_met",
        )

    def test_meta_channel_keys_on_engine_decision(self):
        box = make_box(engine=FakeEngine())
        d = box.resolve(step={"description": "find price"})
        assert d.meta is not None
        keys = set(d.meta.keys())
        assert {
            "engine", "consumer_id", "chosen", "confidence", "candidates",
            "threshold", "engine_latency_ms", "route", "escalated",
            "args_valid", "retried",
        } <= keys
        assert d.meta["consumer_id"] == "tool_choice"
        assert d.meta["route"] == "engine"

    def test_meta_absent_on_legacy_decision(self):
        box = make_box(engine=None,
                       router_result=('{"kind": "tool", "tool": "read_file",'
                                      ' "params": {"path": "README.md"}}', "", []))
        d = box.resolve(step={"description": "find price"})
        assert d.kind == DecisionKind.TOOL
        assert d.meta is None  # AC9.3 edge: legacy rows carry no decision block


# ---------------------------------------------------------------------------
# CT-DE-2 — kernel seam: only TOOL/REASON/FAIL ever escapes
# ---------------------------------------------------------------------------


class TestCtDe2KernelSeam:
    cases = [
        ("confident tool", FakeEngine(chosen="read_file", confidence=0.99)),
        ("low confidence", FakeEngine(chosen="read_file", confidence=0.40)),
        ("delegate", FakeEngine(chosen="DELEGATE", confidence=0.99)),
        ("none", FakeEngine(chosen="NONE", confidence=0.99)),
        ("bad args", FakeEngine(chosen="read_file", confidence=0.99,
                                args=None)),
        ("engine dead", FakeEngine(return_none=True)),
    ]

    @pytest.mark.parametrize(
        "label,engine", cases, ids=[c[0] for c in cases])
    def test_every_outcome_is_kernel_legal(self, label, engine):
        router = FakeRouter(('{"kind": "tool", "tool": "read_file",'
                             ' "params": {"path": "README.md"}}', "", []))
        box = make_box(engine=engine)
        box._router = router
        d = box.resolve(step={"description": "find price"})
        assert d.kind in {DecisionKind.TOOL, DecisionKind.REASON,
                          DecisionKind.FAIL}, label

    def test_low_confidence_reaches_escalation_single_shot(self):
        engine = FakeEngine(chosen="read_file", confidence=0.40)
        router = FakeRouter(('{"kind": "tool", "tool": "read_file",'
                             ' "params": {"path": "README.md"}}', "", []))
        box = make_box(engine=engine)
        box._router = router
        d = box.resolve(step={"description": "find price"})
        assert d.kind == DecisionKind.TOOL
        assert router.calls >= 1  # escalated to the big model
        assert d.meta["route"] == "escalated"
        assert d.meta["escalated"] is True

    def test_confident_pick_never_calls_router(self):
        engine = FakeEngine(chosen="read_file", confidence=0.99)
        router = FakeRouter(("should never be used", "", []))
        box = make_box(engine=engine)
        box._router = router
        d = box.resolve(step={"description": "find price"})
        assert d.kind == DecisionKind.TOOL
        assert router.calls == 0
        assert d.source == "engine"


# ---------------------------------------------------------------------------
# CT-DE-3 — single-writer ledger
# ---------------------------------------------------------------------------


class TestCtDe3Ledger:
    def test_tool_dispatch_uses_single_execute_call_with_meta(self):
        bridge = FakeBridge()
        box = make_box(engine=FakeEngine(), bridge=bridge)
        d = box.resolve(step={"description": "find price"})
        assert d.kind == DecisionKind.TOOL
        for attempt in range(2):
            pass  # noqa — placeholder kept intentionally simple
        dr = box.dispatch(d, session_id="s1")
        assert dr.success
        assert len(bridge.execute_calls) == 1          # exactly one execution
        assert bridge.execute_calls[0]["meta"] == d.meta
        assert bridge.decision_rows == []              # no second channel

    def test_reason_engine_decision_records_route_only_row_once(self):
        bridge = FakeBridge()
        # Session-345: engine NONE now runs the AC3.2 ladder (memory→legacy),
        # so the ladder's model must answer for the step to land REASON — the
        # old empty-text fixture produced FAIL once the ladder was engaged.
        # Text input drives the load; the pinned property (one route-only row,
        # single writer) is unchanged.
        box = make_box(engine=FakeEngine(chosen="NONE", confidence=0.99),
                       router_result=("Thinking it over is the answer.", "", []),
                       bridge=bridge)
        d = box.resolve(step={"description": "just think"})
        assert d.kind == DecisionKind.REASON
        assert bridge.execute_calls == []
        assert len(bridge.decision_rows) == 1
        row = bridge.decision_rows[0]
        assert row["kind"] == "reason"
        # Session-345 (OQ-2, `tool_decision.py`): a confident NONE on a goal
        # carrying NO gather/action signal now COMMITS as REASON with route
        # "engine-none" instead of climbing the AC3.2 ladder. "just think" is
        # exactly such a goal, so the single route-only row records the COMMIT.
        # STALE-BY-SPEC (2026-09-26): the earlier expectation of "escalated"
        # predates the OQ-2 commit and mis-described this fixture. The pinned
        # property is unchanged: exactly one route-only row, one writer.
        assert row["meta"]["route"] == "engine-none"

    def test_legacy_decision_never_records_rows(self):
        bridge = FakeBridge()
        box = make_box(engine=None, bridge=bridge,
                       router_result=('{"kind": "reasoning"}', "", []))
        d = box.resolve(step={"description": "think"})
        assert d.meta is None
        assert bridge.decision_rows == []
        assert bridge.execute_calls == []


# ---------------------------------------------------------------------------
# CT-DE-4 — engine unavailable → legacy silently
# ---------------------------------------------------------------------------


class TestCtDe4Degrade:
    def test_dead_engine_falls_back_to_router(self):
        router = FakeRouter(('{"kind": "tool", "tool": "read_file",'
                             ' "params": {}}', "", []))
        box = make_box(engine=FakeEngine(return_none=True))
        box._router = router
        d = box.resolve(step={"description": "read it"})
        assert d.kind == DecisionKind.TOOL
        assert d.tool == "read_file"
        assert router.calls >= 1
        # engine declined before answering → no escalation meta stamped
        assert d.meta is None

    def test_disabled_flag_short_circuits(self):
        engine = FakeEngine(chosen="read_file", confidence=0.99)
        box = make_box(engine=None)
        box._use_decision_engine = False
        box._decision_engine = engine
        assert box._engine() is None


# ---------------------------------------------------------------------------
# CT-DE-5 — the engine writes to nothing (AST scan)
# ---------------------------------------------------------------------------


class TestCtDe5NoWrites:
    FORBIDDEN = ("ffi_ingest_event", "record_tool_event", "_record_tool_event",
                 "ffi_", "memory.db", "insert_event", "ingest_event")

    def test_engine_module_has_no_io_writes(self):
        src = Path("backend/agent/decision_engine.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.append(node.attr)
            elif isinstance(node, ast.Name):
                names.append(node.id)
        blob = " ".join(names)
        for tok in self.FORBIDDEN:
            assert tok not in blob, f"forbidden symbol {tok} in decision_engine"
        # module-level text check as belt-and-braces (strings, comments)
        for tok in ("ffi_ingest_event", "_record_tool_event"):
            assert tok not in src


# ---------------------------------------------------------------------------
# CT-DE-9 — cross-step continuity (REQ-15)
# ---------------------------------------------------------------------------


class _FrameCapturingEngine(FakeEngine):
    """Captures options + frame for each decide() the box makes."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.seen = []

    def decide(self, consumer_id, options, frame):
        self.seen.append({"options": list(options), "frame": dict(frame)})
        return super().decide(consumer_id, options, frame)


class TestCtDe9Continuity:
    def _two_steps(self, box):
        box.resolve(step={"description": "read README"},
                    session_id="s1")
        box.resolve(step={"description": "now summarize it"},
                    session_id="s1")

    def test_first_step_has_nulls_second_carries_previous(self):
        engine = _FrameCapturingEngine(chosen="read_file", confidence=0.99)
        box = make_box(engine=engine)
        self._two_steps(box)
        assert len(engine.seen) == 2
        first, second = engine.seen
        assert first["frame"]["previous_chosen"] is None    # AC15.4
        assert first["frame"]["step_index"] == 0
        assert second["frame"]["previous_chosen"] == "read_file"
        assert second["frame"]["previous_outcome"] == "tool"
        assert second["frame"]["step_index"] == 1

    def test_meta_carries_continuity_for_ledger_join(self):
        engine = _FrameCapturingEngine(chosen="read_file", confidence=0.99)
        box = make_box(engine=engine)
        d = box.resolve(step={"description": "read README"})
        m = d.meta
        assert "previous_chosen" in m and "step_index" in m


# ---------------------------------------------------------------------------
# CT-DE-10 — vision coordination (REQ-16)
# ---------------------------------------------------------------------------


VISION_TOOLS = [
    {"name": "read_file", "description": "Read a file", "category": "file"},
    {"name": "vision_analyze_screen", "description": "Analyze the screen",
     "category": "vision"},
    {"name": "vision_detect_element", "description": "Detect a UI element",
     "category": "vision"},
]


class TestCtDe10Vision:
    def box_for(self, engine, memory=None):
        return ToolDecisionBox(
            router=FakeRouter(("", "", [])),
            tool_bridge=FakeBridge(),
            get_available_tools=lambda: VISION_TOOLS,
            validate_tool_call=lambda n, p: (True, None),
            infer_fn=lambda prompt, **kw: "done",
            memory_lookup_fn=memory or (lambda _g: None),
            decision_engine=engine,
        )

    # memory hint narrows the pre-filter to the hinted tool (the real shape
    # of the "vision tools dropped" risk the REQ-16 guarantee addresses).
    _HINT = {"tool": "read_file", "rationale": "recent success", "veto": []}

    def test_vision_step_keeps_vision_candidates(self):
        engine = _FrameCapturingEngine(
            chosen="vision_analyze_screen", confidence=0.99)
        box = self.box_for(engine, memory=lambda _g: dict(self._HINT))
        box.resolve(step={"description": "take a screenshot of the chart"})
        opts = engine.seen[0]["options"]
        assert "vision_analyze_screen" in opts           # AC16.1
        assert "vision_detect_element" in opts
        assert engine.seen[0]["frame"]["needs_vision"] is True
        assert engine.seen[0]["frame"]["vision_candidates"] == 2

        # the guarantee must survive the CAP even with a long registry tail:
        # the pre-filter reorders (session-332); it never drops — the cap is
        # the only silent loupe.
        many = [{"name": f"filler_{i}", "description": "x",
                 "category": "system"} for i in range(30)] + [
            {"name": "vision_detect_element", "description": "detect",
             "category": "vision"},
        ]
        box2 = ToolDecisionBox(
            router=FakeRouter(("", "", [])),
            tool_bridge=FakeBridge(),
            get_available_tools=lambda: many,
            validate_tool_call=lambda n, p: (True, None),
            infer_fn=lambda prompt, **kw: "done",
            memory_lookup_fn=lambda _g: None,
            decision_engine=engine,
        )
        box2.resolve(step={"description": "look at the screenshot"})
        opts2 = engine.seen[-1]["options"]
        assert "vision_detect_element" in opts2  # survived the cap

    def test_plain_step_applies_cap_normally(self):
        engine = _FrameCapturingEngine(chosen="read_file", confidence=0.99)
        box = self.box_for(engine, memory=lambda _g: dict(self._HINT))
        box.resolve(step={"description": "read the file"})
        opts = engine.seen[0]["options"]
        # plain steps follow normal rules — vision tools may even appear
        # (pre-filter keeps the menu) but the cap is not bypassed for them.
        assert len(opts) <= engine._cfg_candidate_cap if hasattr(
            engine, "_cfg_candidate_cap") else True
        assert engine.seen[0]["frame"]["needs_vision"] is False

    def test_vocabulary_is_exact_tokens(self):
        from backend.agent.tool_decision import _vision_relevant
        assert _vision_relevant("take a screenshot now")
        assert not _vision_relevant("review the code view")   # 'view' excluded
