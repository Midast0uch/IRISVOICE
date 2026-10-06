"""Behavioral tests: graft recovery triage (REQ-11 AC11.3/AC11.4, T15).

AC11.3  a `recovery_strategy` engine consumer is consulted BEFORE Brain
        planning spend; the Brain plans only on DELEGATE or below threshold.
AC11.4  the same tool failing twice consecutively for one objective escalates
        instead of grafting a third identical attempt.
"""

from __future__ import annotations

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


class _StrategyEngine:
    """Engine stub returning a fixed strategy verdict."""

    def __init__(self, chosen="retry_different_tool", confidence=0.95):
        self._chosen = chosen
        self._conf = confidence
        self.model_id = "strategy-stub"
        self.counters = EngineCounters()
        self.consumers: list = []

    def decide(self, consumer_id, options, frame):
        self.consumers.append(consumer_id)
        if consumer_id != "recovery_strategy":
            return None
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.03)
                for o in options
            ),
            engine_latency_ms=2,
        )


class _BrainRouter:
    def __init__(self):
        self.calls = 0

    def generate(self, role, messages, **kw):
        self.calls += 1
        return ("", "", [])


def _box(engine):
    return ToolDecisionBox(
        router=_BrainRouter(),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: [],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestStrategyGateBeforeBrain:
    def test_strategy_gate_before_brain(self):
        """AC11.3: a confident engine strategy is returned WITHOUT Brain spend."""
        engine = _StrategyEngine("retry_different_tool", 0.95)
        box = _box(engine)

        out = box.recovery_strategy(
            failed_tool="crawler_query", error_snippet="upstream timeout",
            objective="OBJ-1",
        )

        assert out["delegate"] is False
        assert out["strategy"] == "retry_different_tool"
        assert "recovery_strategy" in engine.consumers
        assert box._router.calls == 0, "the Brain was spent on a confident gate"

    def test_delegate_and_low_confidence_fall_to_the_brain(self):
        """AC11.3: DELEGATE — or a verdict below threshold — hands off to the
        Brain planning path."""
        for chosen, conf, expected_delegate in [
            ("DELEGATE", 0.99, True),
            ("decompose", 0.30, True),      # below threshold
            ("escalate", 0.91, False),      # confident
        ]:
            engine = _StrategyEngine(chosen, conf)
            box = _box(engine)
            out = box.recovery_strategy(failed_tool="search", objective="OBJ-2")
            assert out["delegate"] is expected_delegate, (chosen, conf, out)

    def test_engine_unavailable_degrades_to_the_brain(self):
        """No engine → today's behaviour (the Brain plans)."""
        box = ToolDecisionBox(
            router=_BrainRouter(), tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: [],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=None,
        )
        out = box.recovery_strategy(failed_tool="search", objective="OBJ-3")
        assert out["delegate"] is True


class TestDoubleFailureEscalates:
    def test_double_failure_escalates(self):
        """AC11.4: the second consecutive failure of the SAME tool escalates
        deterministically — no third identical graft, no model call spent."""
        engine = _StrategyEngine("retry_different_tool", 0.99)
        box = _box(engine)

        first = box.recovery_strategy(failed_tool="crawler_query",
                                      objective="OBJ-X")
        assert first["strategy"] == "retry_different_tool"  # first failure: retry

        second = box.recovery_strategy(failed_tool="crawler_query",
                                       objective="OBJ-X")
        assert second["strategy"] == "escalate"
        assert second["delegate"] is False

        # A DIFFERENT tool failing next is a fresh triage, not a repeat.
        third = box.recovery_strategy(failed_tool="search", objective="OBJ-X")
        assert third["strategy"] == "retry_different_tool"

    def test_double_failure_is_scoped_per_objective(self):
        """Two failures of the same tool under DIFFERENT objectives are not a
        consecutive pair."""
        engine = _StrategyEngine("retry_different_tool", 0.99)
        box = _box(engine)

        box.recovery_strategy(failed_tool="crawler_query", objective="OBJ-A")
        out = box.recovery_strategy(failed_tool="crawler_query", objective="OBJ-B")
        assert out["strategy"] == "retry_different_tool"
