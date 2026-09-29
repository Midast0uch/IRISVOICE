"""Unit tests: the evidence payload's shape (REQ-28 AC28.2/AC28.8, T43).

AC28.2 — the posterior LOWER BOUND and its observation count, scoped to the
candidate's region and mediator, never a bare global score.
AC28.8 — freshness and scope travel WITH the value, so a stale or
out-of-scope posterior is identifiable rather than silently trusted.
"""

from __future__ import annotations

from backend.agent.tool_decision import _evidence_prior_component


class TestEvidenceShape:
    def test_lower_bound_count_and_scope(self):
        """AC28.2: lower bound + observation count + region/mediator scope."""
        shaped = _evidence_prior_component({
            "prior": {
                "crawler_query": {
                    "lower_bound": 0.42,
                    "observations": 37,
                    "region": "web-search",
                    "mediator": "crawler",
                    "freshness_s": 12.5,
                },
            },
        })

        entry = shaped["crawler_query"]
        assert entry["lower_bound"] == 0.42, (
            "the shape must carry the posterior LOWER BOUND, not a point score"
        )
        assert entry["observations"] == 37
        assert entry["region"] == "web-search"
        assert entry["mediator"] == "crawler"

    def test_freshness_and_scope_attached(self):
        """AC28.8: freshness and scope ride alongside the value."""
        shaped = _evidence_prior_component({
            "prior": {"read_file": {
                "lower_bound": 0.1, "observations": 3,
                "region": "fs", "mediator": "read", "freshness_s": 900.0,
            }},
        })

        entry = shaped["read_file"]
        assert entry["freshness_s"] == 900.0, (
            "a stale posterior must be identifiable, not silently trusted"
        )
        assert entry["region"] and entry["mediator"], (
            "scope (region + mediator) must travel with the value"
        )

    def test_malformed_entries_are_dropped_not_guessed(self):
        """A prior that cannot be shaped is dropped — never guessed."""
        shaped = _evidence_prior_component({
            "prior": {
                "good": {"lower_bound": 0.3},
                "no_bound": {"observations": 5},
                "not_a_dict": 0.9,
                "bool_bound": {"lower_bound": True},
            },
        })

        assert set(shaped) == {"good"}, shaped
        # the surviving entry is completed with safe defaults, not invented
        assert shaped["good"]["observations"] == 0
        assert shaped["good"]["region"] == ""

    def test_absent_and_malformed_payloads_yield_an_empty_block(self):
        """AC28.1 edge: absent evidence is `{}` — byte-identical to today."""
        assert _evidence_prior_component(None) == {}
        assert _evidence_prior_component({}) == {}
        assert _evidence_prior_component({"session_id": "s"}) == {}
        assert _evidence_prior_component({"prior": []}) == {}
        assert _evidence_prior_component({"prior": "nonsense"}) == {}

    def test_scalar_coercions_do_not_raise(self):
        """Defensive: a numeric-looking string does not become a bound."""
        shaped = _evidence_prior_component({
            "prior": {"x": {"lower_bound": "0.5", "observations": "7",
                            "freshness_s": "nope"}},
        })
        assert shaped == {}, (
            "a non-numeric lower_bound must be dropped, not coerced"
        )
