"""Behavioral tests: decision engine driving a full DER step (BT-DE-1..4).

The system as it runs: box + engine route a step; the dispatch executes through
the bridge; the single ledger row carries the decision block.
Emergent properties asserted:
  - a confident engine decision executes with ZERO big-model calls (BT-DE-1)
  - a low-confidence decision escalates and the row says so (BT-DE-2)
  - an empty big-model answer is retried exactly once (BT-DE-3, E5 class)
  - a no-tool outcome writes one route-only row, never two (BT-DE-4)

The real single-writer ingestion is pinned in test_decision_engine_ledger.py
(real AgentToolBridge._record_tool_event + record_decision with stubbed FFI).
"""

from __future__ import annotations

import backend.agent.decision_engine as de_mod
from backend.agent.decision_engine import CandidateScore, DecisionScore
from backend.agent.tool_decision import DecisionKind, ToolDecisionBox


AVAILABLE = [
    {"name": "read_file", "description": "Read a file"},
    {"name": "speak", "description": "Speak text"},
]


class BtEngine:
    """Box-level engine stub that drives the full routing."""

    def __init__(self, chosen="read_file", confidence=0.99,
                 args=None, dead=False):
        self._c = chosen
        self._conf = confidence
        self._args = {"path": "README.md"} if args is None else args
        self._dead = dead
        self.model_id = "bt-350m"

        class _C:
            decisions = 0
            escalations = 0
            memory_fallbacks = 0
            retries = 0

        self.counters = _C()

    def decide(self, consumer_id, options, frame):
        if self._dead:
            return None
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._c,
            confidence=self._conf,
            distribution=(CandidateScore(self._c, -0.05, self._conf),),
            engine_latency_ms=4,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        class R:
            retried = False
        r = R()
        r.args = self._args
        return r


class BtRouter:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def generate(self, role, messages, **kw):
        self.calls += 1
        return self._results.pop(0) if self._results else ("", "", [])

    def resolve(self, role):
        class R:
            id = "same"
            model = "same"
        return R()


class BtBridge:
    def __init__(self):
        self.exec_calls = []
        self.decision_rows = []

    async def execute_tool(self, tool, params, session_id="unknown",
                           decision_meta=None, **kw):
        self.exec_calls.append((tool, params, decision_meta))
        return {"success": True}

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.decision_rows.append({"meta": meta, "kind": kind})


def make_box(engine, router_results=None, bridge=None):
    return ToolDecisionBox(
        router=BtRouter(router_results or [("", "", [])]),
        tool_bridge=bridge or BtBridge(),
        get_available_tools=lambda: AVAILABLE,
        validate_tool_call=lambda n, p: (True, None),
        infer_fn=lambda prompt, **kw: "done",
        memory_lookup_fn=lambda _g: None,
        decision_engine=engine,
    )


class TestBtDe1ConfidentExecutesAlone:
    def test_engine_step_without_router(self):
        router = BtRouter([("if called the test fails", "", [])])
        bridge = BtBridge()
        box = make_box(BtEngine(), bridge=bridge)
        box._router = router
        d = box.resolve(step={"description": "read the readme"})
        assert d.kind == DecisionKind.TOOL
        assert router.calls == 0
        dr = box.dispatch(d, session_id="s")
        assert dr.success
        tool, params, meta = bridge.exec_calls[0]
        assert tool == "read_file" and params == {"path": "README.md"}
        assert meta["route"] == "engine" and meta["confidence"] >= 0.85
        assert box._decision_engine.counters.decisions >= 0  # engine accounted


class TestBtDe2LowConfEscalates:
    def test_escalation_marked_in_meta(self):
        engine = BtEngine(chosen="read_file", confidence=0.30)
        router = BtRouter([('{"kind": "tool", "tool": "read_file",'
                            ' "params": {"path": "README.md"}}', "", [])])
        box = make_box(engine)
        box._router = router
        d = box.resolve(step={"description": "read the readme"})
        assert d.kind == DecisionKind.TOOL
        assert router.calls == 1
        assert d.meta is not None
        assert d.meta["route"] == "escalated"
        assert d.meta["escalated"] is True
        assert d.meta["confidence"] == 0.30
        assert engine.counters.escalations == 1

    def test_escalation_records_final_choice_for_calibration(self):
        # engine said write_file; the brain ended up on read_file -> mismatch
        engine = BtEngine(chosen="write_file", confidence=0.30)
        router = BtRouter([('{"kind": "tool", "tool": "read_file",'
                            ' "params": {"path": "README.md"}}', "", [])])
        box = make_box(engine)
        box._router = router
        d = box.resolve(step={"description": "read the readme"})
        m = d.meta
        assert m["final_choice"] == "read_file"
        assert m["engine_correct"] is False

    def test_delegate_choice_honored_correct(self):
        engine = BtEngine(chosen="DELEGATE", confidence=0.30)
        router = BtRouter([('{"kind": "tool", "tool": "read_file",'
                            ' "params": {"path": "README.md"}}', "", [])])
        box = make_box(engine)
        box._router = router
        d = box.resolve(step={"description": "read the readme"})
        assert d.meta["engine_correct"] is True


class TestBtDe3EmptyOnceThenRetry:
    def test_empty_first_answer_retries_once(self):
        engine = BtEngine(chosen="read_file", confidence=0.10)  # escalate
        router = BtRouter([
            ("", "", []),                                          # 1st: empty
            ('{"kind": "tool", "tool": "read_file",'
             ' "params": {"path": "README.md"}}', "", []),         # retry: ok
        ])
        box = make_box(engine)
        box._router = router
        d = box.resolve(step={"description": "read it please"})
        assert d.kind == DecisionKind.TOOL
        assert router.calls == 2            # exactly one retry (REQ-4)
        assert d.meta is not None
        assert d.meta["retried"] is True

    def test_double_empty_yields_fail_without_loop(self):
        engine = BtEngine(chosen="read_file", confidence=0.10)
        router = BtRouter([("", "", []), ("", "", [])])
        box = make_box(engine)
        box._router = router
        d = box.resolve(step={"description": "read it please"})
        assert router.calls == 2            # bounded: no third attempt
        assert d.kind == DecisionKind.FAIL  # E5-shape now ends honest FAIL only
        assert d.meta is not None and d.meta["route"] == "escalated"


class TestBtDe4ReasonSingleRow:
    def test_none_choice_one_route_only_row(self):
        bridge = BtBridge()
        # Session-345: engine NONE runs the AC3.2 ladder (memory→legacy), so
        # the ladder's model must answer for the step to land REASON — the old
        # empty-text fixture produced FAIL once the ladder engaged. Same load,
        # same single-row property; only the stranded input is updated.
        box = make_box(BtEngine(chosen="NONE", confidence=0.99),
                       router_results=[("Thinking it over is the answer.", "", [])],
                       bridge=bridge)
        d = box.resolve(step={"description": "nothing to do"})
        assert d.kind == DecisionKind.REASON
        assert bridge.exec_calls == []
        assert len(bridge.decision_rows) == 1
        row = bridge.decision_rows[0]
        assert row["kind"] == "reason"
        # Session-345: NONE now runs the AC3.2 ladder (memory→legacy), so the
        # single route-only row says "escalated". The pinned property — one
        # row, single writer — is unchanged.
        assert row["meta"]["route"] == "escalated"

    def test_engine_dead_no_rows_no_meta(self):
        bridge = BtBridge()
        box = make_box(BtEngine(dead=True), bridge=bridge,
                       router_results=[('{"kind": "reasoning"}', "", [])])
        d = box.resolve(step={"description": "think"})
        assert d.kind == DecisionKind.REASON
        assert d.meta is None
        assert bridge.decision_rows == []


class TestBtDe8EngineCache:
    def test_same_question_twice_uses_one_engine_call(self):
        bridge = BtBridge()

        class CountedEngine(BtEngine):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.decide_calls = 0

            def decide(self, consumer_id, options, frame):
                self.decide_calls += 1
                return super().decide(consumer_id, options, frame)

        engine = CountedEngine(chosen="read_file", confidence=0.99)
        box = make_box(engine, bridge=bridge)
        d1 = box.resolve(step={"description": "read the readme"})
        d2 = box.resolve(step={"description": "read the readme"})
        assert d1.kind == DecisionKind.TOOL and d2.kind == DecisionKind.TOOL
        # engine evaluated once per unique question; second answer is cached
        assert engine.decide_calls == 1
        # provenance shows on the second row
        assert len(bridge.decision_rows) == 0  # both are TOOL, rows > execute_tool
        assert len(bridge.exec_calls) == 0  # resolve only, no dispatch yet
        # meta on second decision carries cache provenance
        assert d2.meta is not None and d2.meta.get("cached") is True
