"""Unit tests: the Reviewer's split duties (REQ-13 AC13.2, T17).

AC13.2 — the engine never writes the step text. The Brain keeps verdict duty
AND all `refined`-text duty; the `review_verdict` consumer is a shadow observer.

This is the invariant that makes the Reviewer safe to shadow-score: a verdict
the engine got WRONG can cost nothing, because the engine cannot author prose.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.der_loop import QueueItem, Reviewer, ReviewVerdict

BRAIN_REFINED = "tighten step 2 and cite the source"


class _Engine:
    """Engine stub whose verdict deliberately DISAGREES with the Brain."""

    def __init__(self, chosen="pass", confidence=0.99):
        self._chosen, self._conf = chosen, confidence
        self.model_id = "reviewer-stub"
        self.counters = EngineCounters()

    def decide(self, consumer_id, options, frame):
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.03)
                for o in options
            ),
            engine_latency_ms=2,
        )


class _Adapter:
    """Brain stand-in returning a fixed REFINE verdict with refined text."""

    def __init__(self, raw=None):
        self._raw = raw or (
            '{"verdict": "refine", "refined": "' + BRAIN_REFINED + '"}'
        )
        self.calls = 0

    def infer(self, prompt, role="EXECUTION", max_tokens=200, temperature=0.0):
        self.calls += 1
        return SimpleNamespace(raw_text=self._raw)


class _Ctx:
    gradient_warnings = ""
    active_contracts = ""


def _reviewer(engine):
    r = Reviewer(_Adapter(), None)
    r.set_review_engine(engine)
    return r


def _item():
    return QueueItem(step_id="s1", step_number=1,
                     description="read the readme", objective_anchor="OBJ-1")


class TestBrainWritesRefinedText:
    def test_brain_writes_refined_text(self):
        """AC13.2: even when the engine CONFIDENTLY disagrees, the Brain's
        verdict AND its refined text are what the loop gets."""
        engine = _Engine(chosen="pass", confidence=0.99)   # engine says PASS
        reviewer = _reviewer(engine)

        verdict, out = reviewer.review(_item(), [], _Ctx(), is_mature=True)

        assert verdict == ReviewVerdict.REFINE, (
            "the engine verdict steered the loop — AC13.1 is shadow-only"
        )
        assert out == BRAIN_REFINED, (
            "the refined text did not come from the Brain — AC13.2 forbids the "
            "engine writing step text"
        )

    def test_the_engine_never_supplies_the_text(self):
        """With the engine picking REFINE, the text is STILL the Brain's — the
        engine has no channel to author prose at all."""
        engine = _Engine(chosen="refine", confidence=0.99)
        reviewer = _reviewer(engine)

        verdict, out = reviewer.review(_item(), [], _Ctx(), is_mature=True)

        assert verdict == ReviewVerdict.REFINE
        assert out == BRAIN_REFINED, (
            "the engine's own choice leaked into the step text"
        )
        # the shadow row carries only a bool/label — never text
        row = reviewer.last_shadow_verdict
        assert row is not None
        assert set(row) >= {"consumer_id", "chosen", "confidence", "shadow"}
        assert "refined" not in row and "text" not in row

    def test_no_engine_means_no_row_and_the_brain_still_writes(self):
        """The engine-unavailable path is byte-identical to today."""
        r = Reviewer(_Adapter(), None)
        r.set_review_engine(None)

        verdict, out = r.review(_item(), [], _Ctx(), is_mature=True)

        assert verdict == ReviewVerdict.REFINE
        assert out == BRAIN_REFINED
        assert r.last_shadow_verdict is None

    def test_a_pass_verdict_carries_no_refined_text(self):
        """A PASS must not smuggle the Brain's refine text through."""
        r = Reviewer(
            _Adapter('{"verdict": "pass", "refined": "' + BRAIN_REFINED + '"}'),
            None,
        )
        r.set_review_engine(_Engine())

        verdict, out = r.review(_item(), [], _Ctx(), is_mature=True)

        assert verdict == ReviewVerdict.PASS
        assert not out or out != BRAIN_REFINED
