"""Unit tests: the recovery veto (REQ-11 AC11.2, T14).

A vetoed tool must score ZERO probability in the recorded distribution, and
when every candidate is vetoed the engine must decline (the caller escalates
with the veto set attached) rather than force-pick a vetoed tool.
"""

from __future__ import annotations

from backend.agent.decision_engine import CandidateScore, DecisionScore
from backend.agent.tool_decision import apply_ruled_out


def _ds(chosen: str, dist) -> DecisionScore:
    return DecisionScore(
        consumer_id="tool_choice", chosen=chosen,
        confidence=dict(dist)[chosen], distribution=tuple(
            CandidateScore(n, p, p) for n, p in dist
        ),
        engine_latency_ms=1,
    )


class TestVetoedToolZeroProbability:
    def test_vetoed_tool_zero_probability(self):
        """AC11.2: the vetoed tool carries prob 0.0 and cannot win."""
        ds = _ds("crawler_query", [
            ("crawler_query", 0.80), ("search", 0.15), ("speak", 0.05),
        ])
        out = apply_ruled_out(ds, {"crawler_query"})

        assert out is not None
        probs = {c.name: c.prob for c in out.distribution}
        assert probs["crawler_query"] == 0.0, "the vetoed tool still has mass"
        assert out.chosen == "search", "the best SURVIVING candidate must win"
        assert out.confidence == probs["search"]

    def test_all_candidates_vetoed_declines(self):
        """REQ-11 edge: never force-pick a vetoed tool — decline so the caller
        escalates to the Brain with the veto set."""
        ds = _ds("search", [("search", 0.6), ("speak", 0.4)])
        assert apply_ruled_out(ds, {"search", "speak"}) is None

    def test_no_veto_is_a_no_op(self):
        """REQ-11 edge: no failure evidence → identical to today."""
        ds = _ds("search", [("search", 0.9), ("speak", 0.1)])
        out = apply_ruled_out(ds, set())
        assert out is ds, "an empty veto must not rebuild the verdict"
        assert apply_ruled_out(None, {"search"}) is None

    def test_veto_of_an_absent_name_is_a_no_op(self):
        """A veto for a tool that is not on the menu changes nothing."""
        ds = _ds("search", [("search", 0.9), ("speak", 0.1)])
        out = apply_ruled_out(ds, {"not_on_the_menu"})
        assert out.chosen == "search"
        assert {c.prob for c in out.distribution} == {0.9, 0.1}
