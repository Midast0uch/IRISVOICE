"""Behavioural tests: late evidence never stalls or re-decides
(REQ-28 AC28.5, T43).

AC28.5 — WHEN evidence arrives after the decision budget THEN THE SYSTEM SHALL
proceed without it and SHALL NOT stall or re-decide (the REQ-12 AC12.3
late-attach shape).

The seam is synchronous by construction: a caller either supplies the payload
with the decision request or it is absent. There is no pending/await path for a
late payload to attach to, and this suite pins that — a future "wait for
evidence" branch is exactly the stall the AC forbids.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.tool_decision import ToolDecisionBox

MENU = [
    {"name": "search", "description": "instant lookup", "category": "web"},
    {"name": "crawler_query", "description": "deep crawl", "category": "web"},
    {"name": "speak", "description": "speak", "category": "system"},
]


class _Engine:
    def __init__(self):
        self.model_id = "late-stub"
        self.counters = EngineCounters()
        self.calls = 0

    def decide(self, consumer_id, options, frame):
        self.calls += 1
        return DecisionScore(
            consumer_id=consumer_id, chosen="search", confidence=0.9,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == "search" else 0.05)
                for o in options
            ),
            engine_latency_ms=1,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        class _R:
            retried = False
            args = {"query": "x"}
        return _R()


def _box(engine):
    return ToolDecisionBox(
        router=SimpleNamespace(generate=lambda *a, **kw: ("", "", [])),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: MENU,
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestLateEvidence:
    def test_late_evidence_no_stall_no_redecide(self):
        """AC28.5: the decision is taken exactly ONCE, with or without a
        payload — there is no second pass for late evidence to join."""
        engine = _Engine()
        box = _box(engine)

        box.resolve({"description": "find the price", "task_class": "full"},
                    session_id="s1", conversation_id="c1")

        assert engine.calls == 1, (
            f"the engine was consulted {engine.calls} times for one decision — "
            "a late-attach path re-decided (AC28.5)"
        )

    def test_a_supplied_payload_is_applied_in_the_same_pass(self):
        """Evidence supplied WITH the request is blended in that one pass — it
        never queues for a later decision."""
        engine = _Engine()
        box = _box(engine)

        d = box.resolve(
            {"description": "find the price", "task_class": "full"},
            evidence={"prior": {"crawler_query": {
                "lower_bound": 1.0, "observations": 9,
                "region": "web", "mediator": "crawl", "freshness_s": 1.0,
            }}},
            session_id="s1", conversation_id="c1",
        )

        assert engine.calls == 1, "the payload forced a second decision pass"
        assert d is not None

    def test_no_pending_evidence_state_exists(self):
        """The seam holds no pending/await state for a late payload to attach
        to — structurally, not just behaviourally."""
        box = _box(_Engine())

        for attr in ("_pending_evidence", "_evidence_future",
                     "_await_evidence", "_late_evidence"):
            assert not hasattr(box, attr), (
                f"the box grew a {attr} pending state — that is the stall "
                "AC28.5 forbids"
            )

    def test_a_late_second_resolve_is_an_independent_decision(self):
        """Supplying evidence on a LATER, separate resolve is a new decision —
        it never retroactively alters the earlier one."""
        engine = _Engine()
        box = _box(engine)

        first = box.resolve(
            {"description": "find the price", "task_class": "full"},
            session_id="s1", conversation_id="c1")

        second = box.resolve(
            {"description": "find the price", "task_class": "full"},
            evidence={"prior": {"crawler_query": {
                "lower_bound": 1.0, "observations": 9,
                "region": "web", "mediator": "crawl", "freshness_s": 1.0,
            }}},
            session_id="s1", conversation_id="c1")

        assert first is not None and second is not None
        # The first decision is untouched by the later payload.
        assert first.tool == "search"
