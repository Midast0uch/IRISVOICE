"""Unit test: the Noul envelope (REQ-14 AC14.6, T18).

A monitor judgment is P(statement true) — one calibrated probability, with NO
winner and NO separate confidence field. A two-option Choice is a different
object, and AC14.4's fail-closed semantics depend on the probability meaning
what it claims.
"""

from __future__ import annotations

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionEngine,
    DecisionScore,
    EngineConfig,
    Noul,
)
from backend.agent.monitor_shadow import register_monitor_consumers


class _StubEngine:
    """Scores yes/no with a fixed P(yes)."""

    def __init__(self, p_true=0.82):
        self._p = p_true
        self.model_id = "noul-stub"

    def decide(self, consumer_id, options, frame):
        if "yes" not in options or "no" not in options:
            return None
        return DecisionScore(
            consumer_id=consumer_id, chosen="yes", confidence=self._p,
            distribution=(
                CandidateScore("yes", -0.1, self._p),
                CandidateScore("no", -0.2, 1.0 - self._p),
            ),
            engine_latency_ms=3,
        )


def test_noul_single_calibrated_probability():
    """AC14.6: the envelope carries ONE probability of truth."""
    register_monitor_consumers()
    engine = _StubEngine(p_true=0.82)

    # A REAL engine instance with only its scoring bound to the stub, so the
    # Noul plumbing (not a fake envelope) is what is under test. Constructed
    # locally — never the module singleton, which other tests share.
    real = DecisionEngine(config=EngineConfig())
    real.decide = engine.decide  # type: ignore[method-assign]

    noul = real.noul("sufficient", "Is the evidence sufficient?",
                     {"goal": "state"})

    assert isinstance(noul, Noul)
    assert noul.consumer_id == "sufficient"
    assert abs(noul.probability - 0.82) < 1e-9
    assert noul.engine_latency_ms >= 0

    # ── the SHAPE is the point: no winner, no separate confidence ──
    fields = set(Noul.__dataclass_fields__)
    assert fields == {"consumer_id", "probability", "engine_latency_ms"}, fields
    assert not hasattr(noul, "chosen")
    assert not hasattr(noul, "confidence")

    # the probability MEANS "statement is true"
    assert noul.true(0.5) is True
    assert noul.confident(0.80) is True
    assert noul.confident(0.90) is False


def test_noul_is_none_when_the_engine_cannot_answer():
    """A missing engine / missing true-label → None, never a fabricated belief.
    Callers treat None as fail-closed (AC14.4)."""
    class _NoLabels:
        def decide(self, consumer_id, options, frame):
            return DecisionScore(
                consumer_id=consumer_id, chosen="maybe", confidence=0.9,
                distribution=(CandidateScore("maybe", 0.0, 1.0),),
                engine_latency_ms=1,
            )

    real = DecisionEngine(config=EngineConfig())
    real.decide = _NoLabels().decide  # type: ignore[method-assign]
    assert real.noul("done", "Is the objective complete?") is None

    real.decide = lambda *a, **kw: None  # type: ignore[method-assign]
    assert real.noul("done", "Is the objective complete?") is None
