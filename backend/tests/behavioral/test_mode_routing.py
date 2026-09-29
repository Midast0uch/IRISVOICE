"""Behavioral tests: mode routing (REQ-15 AC15.1, T19).

Slash-command overrides are DETERMINISTIC and always win — the engine shadow
never touches them. The engine's own mode pick is recorded, never applied,
until AC15.4's measured bar is met.
"""

from __future__ import annotations

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
)
from backend.agent.mode_detector import AgentMode, ModeDetector


class _ModeEngine:
    """Scores the `mode` consumer; its own pick DISAGREES with the keywords."""

    def __init__(self, chosen="research"):
        self._chosen = chosen
        self.calls: list = []

    def decide(self, consumer_id, options, frame):
        self.calls.append((consumer_id, list(options)))
        dist = {
            o: (0.95 if o == self._chosen else 0.01) for o in options
        }
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=0.95,
            distribution=tuple(
                CandidateScore(n, -0.1, p) for n, p in dist.items()
            ),
            engine_latency_ms=2,
        )


def _detector(engine=None) -> ModeDetector:
    d = ModeDetector()
    if engine is not None:
        d.set_mode_engine(engine)
    return d


class TestSlashOverridesWin:
    def test_slash_overrides_win(self):
        """AC15.1: a slash command routes deterministically and the engine is
        NEVER consulted on that branch."""
        engine = _ModeEngine(chosen="research")
        d = _detector(engine)

        for text, expected in [
            ("/spec design the ingest pipeline", AgentMode.SPEC),
            ("/implement build the endpoint", AgentMode.IMPLEMENT),
            ("/debug the collector crashes", AgentMode.DEBUG),
            ("/test the queue", AgentMode.TEST),
            ("/review the diff", AgentMode.REVIEW),
            ("/ask what should we build", AgentMode.IMPLEMENT),
        ]:
            result = d.detect(text)
            assert result.mode == expected, (text, result.mode)
            assert result.trigger == "slash_command"
            assert result.confidence == 1.0
            assert result.needs_clarification == (expected == AgentMode.IMPLEMENT
                                                  and text.startswith("/ask"))

        assert engine.calls == [], (
            "the engine was consulted on the deterministic slash branch"
        )

    def test_inference_is_shadowed_not_replaced(self):
        """AC15.1: on the keyword branch the engine's own pick is RECORDED but
        the keyword mode still decides."""
        engine = _ModeEngine(chosen="research")
        d = _detector(engine)

        result = d.detect("please write the code for the upload handler")

        # the keyword branch decides IMPLEMENT ("write", "code")
        assert result.mode == AgentMode.IMPLEMENT, (
            "the engine's pick replaced the keyword mode — T19 is shadow"
        )
        assert result.trigger == "inference"
        # and the disagreement is recorded for parity
        assert d.last_mode_shadow is not None
        assert d.last_mode_shadow["engine_mode"] == "research"
        assert d.last_mode_shadow["keyword_mode"] == "implement"
        assert d.last_mode_shadow["shadow"] is True

    def test_no_engine_leaves_routing_untouched(self):
        """Edge case: engine unavailable → keyword branch unchanged, no row."""
        d = _detector(None)
        result = d.detect("fix the broken collector")
        assert result.mode == AgentMode.DEBUG
        assert result.trigger == "inference"
        assert d.last_mode_shadow is None
        assert result.confidence == d._infer_mode(
            "fix the broken collector")[1]
