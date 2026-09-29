"""Behavioural tests: evidence as a WEIGHTED PRIOR (REQ-28 AC28.3/AC28.7, T45).

BT-DEI-18 — the prior reorders candidates but cannot cross the threshold on its
own, and an unused retrieval is never scored as a success.

Two properties the ACs demand together, and this suite is what keeps them
together: the model's own evidence can OUTVOTE the prior, and the prior can
never MANUFACTURE confidence.
"""

from __future__ import annotations

from backend.agent.decision_engine import CandidateScore, DecisionScore
from backend.agent.tool_decision import (
    _EVIDENCE_PRIOR_WEIGHT,
    apply_evidence_prior,
)

THRESHOLD = 0.40


def _score(chosen: str, conf: float, dist: dict) -> DecisionScore:
    return DecisionScore(
        consumer_id="tool_choice", chosen=chosen, confidence=conf,
        distribution=tuple(
            CandidateScore(n, -0.1, p) for n, p in dist.items()
        ),
        engine_latency_ms=1,
    )


def _prior(**bounds) -> dict:
    return {
        n: {"lower_bound": lb, "observations": 10,
            "region": "r", "mediator": "m", "freshness_s": 1.0}
        for n, lb in bounds.items()
    }


class TestPriorIsOutvotable:
    def test_prior_outvotable_cannot_cross_threshold(self):
        """AC28.3: the prior reorders plausible candidates and can NEVER raise
        the winner above the threshold on its own."""
        # The model is UNCONFIDENT: 0.30 < 0.40, so nothing may cross.
        ds = _score("alpha", 0.30, {"alpha": 0.30, "beta": 0.25, "gamma": 0.20})
        prior = _prior(gamma=1.0)   # a maximal, greedy prior

        out, used = apply_evidence_prior(ds, prior, THRESHOLD)

        assert out is not None
        assert out.confidence < THRESHOLD, (
            f"the prior manufactured confidence ({out.confidence} >= "
            f"{THRESHOLD}) — AC28.3 forbids it"
        )

    def test_a_weighted_prior_cannot_rescue_a_hopeless_candidate(self):
        """The prior's weight is bounded, so the model's own evidence outvotes
        it: a candidate the model scores far lower is not rescued."""
        ds = _score("alpha", 0.80, {"alpha": 0.80, "beta": 0.02})
        prior = _prior(beta=1.0)

        out, _used = apply_evidence_prior(ds, prior, THRESHOLD)

        assert out.chosen == "alpha", (
            "a maximal prior overturned a 40x-lower model score — the prior "
            "is a decider, not a weighted prior"
        )

    def test_the_weight_is_bounded(self):
        """The documented weight is what makes the previous test true."""
        assert 0.0 < _EVIDENCE_PRIOR_WEIGHT < 0.5, (
            "a prior weight at or above 0.5 would let the graph outvote the "
            "model (AC28.3)"
        )


class TestPriorReorders:
    def test_prior_reorders_plausible_candidates(self):
        """AC28.3: among candidates the model finds plausible, the prior CAN
        change the winner — otherwise it is not a prior at all."""
        ds = _score("alpha", 0.44, {"alpha": 0.44, "beta": 0.42})
        prior = _prior(beta=1.0)

        out, used = apply_evidence_prior(ds, prior, THRESHOLD)

        assert used is True
        assert out.chosen == "beta", (
            "a near-tie was not reordered by a strong prior"
        )

    def test_confidence_above_threshold_is_not_capped(self):
        """The cap only applies when the model was BELOW the threshold — a
        confident model keeps its confidence."""
        ds = _score("alpha", 0.90, {"alpha": 0.90, "beta": 0.05})
        prior = _prior(alpha=0.9)

        out, _used = apply_evidence_prior(ds, prior, THRESHOLD)

        assert out.confidence > THRESHOLD


class TestAbsentEvidenceIsInert:
    def test_absent_prior_returns_the_same_object(self):
        """AC28.1 edge: absent evidence is byte-identical — the SAME object."""
        ds = _score("alpha", 0.5, {"alpha": 0.5, "beta": 0.5})

        out, used = apply_evidence_prior(ds, None, THRESHOLD)
        assert out is ds and used is False

        out, used = apply_evidence_prior(ds, {}, THRESHOLD)
        assert out is ds and used is False

    def test_evidence_for_absent_candidates_is_ignored(self):
        """REQ-28 edge: evidence for a candidate not on the menu is ignored."""
        ds = _score("alpha", 0.5, {"alpha": 0.5, "beta": 0.5})

        out, used = apply_evidence_prior(
            ds, _prior(not_on_the_menu=1.0), THRESHOLD)

        assert out is ds and used is False

    def test_unused_retrieval_not_scored_success(self):
        """AC28.7: a retrieval that changed nothing is NOT 'used'."""
        ds = _score("alpha", 0.95, {"alpha": 0.95, "beta": 0.02})
        # Evidence that reinforces the model's existing winner at the same
        # ranking: present, retrieved, and genuinely unused.
        prior = _prior(alpha=0.95)

        out, used = apply_evidence_prior(ds, prior, THRESHOLD)

        assert used is False, (
            "a retrieval that left the decision unchanged was scored as used"
        )
        assert out is ds

    def test_a_broken_prior_never_breaks_a_decision(self):
        """The seam is defensive: a malformed prior leaves the verdict alone."""
        ds = _score("alpha", 0.5, {"alpha": 0.5, "beta": 0.5})

        out, used = apply_evidence_prior(
            ds, {"alpha": {"lower_bound": object()}}, THRESHOLD)

        assert out is ds and used is False
