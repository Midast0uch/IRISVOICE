"""Unit tests: the failure triage stays counter-owned (REQ-17 AC17.2, T21).

AC17.2 — heuristic counters SHALL remain the deciders until the consumer passes
its calibration bar; the engine only records. So the triage row is always a
SHADOW PAIR (engine verdict vs counter decision), and the deterministic
double-failure escalate keeps paying no model call at all (AC11.4).
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.tool_decision import ToolDecisionBox


class _Engine:
    def __init__(self, chosen, conf=0.99):
        self._chosen, self._conf = chosen, conf
        self.model_id = "triage-stub"
        self.counters = EngineCounters()
        self.calls = 0

    def decide(self, consumer_id, options, frame):
        self.calls += 1
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.02)
                for o in options
            ),
            engine_latency_ms=1,
        )


class _Bridge:
    def __init__(self):
        self.rows: list = []

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.rows.append((dict(meta), kind))


def _box(engine):
    return ToolDecisionBox(
        router=SimpleNamespace(generate=lambda *a, **kw: ("", "", [])),
        tool_bridge=_Bridge(),
        get_available_tools=lambda: [],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestCountersStillDecide:
    def test_counters_still_decide(self):
        """AC17.2: a confident engine `retry_same` is recorded, never returned."""
        engine = _Engine("retry_same")
        box = _box(engine)

        out = box.recovery_strategy(
            failed_tool="crawler_query", objective="OBJ-1")

        assert out["strategy"] != "retry_same", (
            "the engine routed a retry the counters own (AC17.2)"
        )
        assert out["strategy"] == "delegate"
        assert box.last_triage_shadow["chosen"] == "retry_same"
        assert box.last_triage_shadow["counter_choice"] == "delegate"

    def test_double_failure_escalates_without_a_model_call(self):
        """AC11.4 + AC17.2: the deterministic escalate stays model-free, so the
        counters own it and no row is fabricated."""
        engine = _Engine("retry_different_tool")
        box = _box(engine)

        box.recovery_strategy(failed_tool="crawler_query", objective="OBJ-2")
        assert engine.calls == 1

        out = box.recovery_strategy(failed_tool="crawler_query", objective="OBJ-2")

        assert out["strategy"] == "escalate"
        assert engine.calls == 1, "a repeat must not spend a model call (AC11.4)"
        assert box.last_triage_shadow is None

    def test_engine_still_steers_the_three_legacy_strategies(self):
        """T15 is preserved: a confident retry_different_tool / decompose /
        escalate still returns (AC11.3)."""
        engine = _Engine("decompose")
        box = _box(engine)

        out = box.recovery_strategy(failed_tool="search", objective="OBJ-3")

        assert out["strategy"] == "decompose" and out["delegate"] is False
        assert box.last_triage_shadow["chosen"] == "decompose"
        assert box.last_triage_shadow["counter_choice"] == "decompose"

    def test_no_engine_records_no_row(self):
        """No engine → no row (a shadow must never fabricate one)."""
        box = _box(None)
        out = box.recovery_strategy(failed_tool="search", objective="OBJ-4")
        assert out["delegate"] is True
        assert box.last_triage_shadow is None
