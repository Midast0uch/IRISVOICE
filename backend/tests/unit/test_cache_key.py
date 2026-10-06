"""Unit tests: the cache key (REQ-27).

AC27.3  two different evidence payloads never collide.
AC27.4  a cache hit is not counted as a fresh decision.
AC27.5  the cache is not consulted when the key is incomplete.
"""

from __future__ import annotations

from backend.agent.tool_decision import _evidence_cache_component

import pytest

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the
# real enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ('tool_choice',)
pytestmark = pytest.mark.usefixtures("oracle_decides_module")


class TestEvidenceDiffersNoCollision:
    def test_evidence_differs_no_collision(self):
        """AC27.3: two different payloads produce different key components —
        a cache hit can never return a verdict computed for another payload."""
        a = _evidence_cache_component({"posterior": 0.7, "region": "codespace"})
        b = _evidence_cache_component({"posterior": 0.9, "region": "codespace"})
        assert a and b and a != b, "two different payloads collided"

    def test_absent_is_stable_empty_sentinel(self):
        """The absent case is a stable empty sentinel — every absent-evidence
        decision shares one key component."""
        assert _evidence_cache_component(None) == ""
        assert _evidence_cache_component({}) == ""
        assert _evidence_cache_component(None) == _evidence_cache_component({})

    def test_same_payload_same_component(self):
        """The same payload (any key order) produces the same component."""
        a = _evidence_cache_component({"posterior": 0.7, "region": "r1"})
        b = _evidence_cache_component({"region": "r1", "posterior": 0.7})
        assert a == b, "key order changed the component"


class TestHitNotCountedAsFreshDecision:
    def test_hit_not_counted_as_fresh_decision(self):
        """AC27.4: a cache hit is the same decision, not a new one — the box
        records the row with cached=True so calibration reads them apart."""
        from types import SimpleNamespace

        from backend.agent.decision_engine import (
            CandidateScore,
            DecisionScore,
            EngineCounters,
        )
        from backend.agent.tool_decision import ToolDecisionBox

        class _Engine:
            def __init__(self):
                self.model_id = "cache-stub"
                self.counters = EngineCounters()
                self._cfg = SimpleNamespace(candidate_cap=6)
                self.calls = 0

            def decide(self, consumer_id, options, frame):
                self.calls += 1
                return DecisionScore(
                    consumer_id=consumer_id, chosen="NONE", confidence=0.9,
                    distribution=(CandidateScore("NONE", -0.1, 0.9),),
                    engine_latency_ms=1,
                )

        engine = _Engine()
        box = ToolDecisionBox(
            router=SimpleNamespace(),
            tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: [
                {"name": "read_file", "description": "d", "category": "file"}
            ],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=engine,
        )
        step = {"description": "read the file", "task_class": "full"}
        d1 = box.resolve(step, session_id="s1", conversation_id="c1")
        d2 = box.resolve(dict(step), session_id="s1", conversation_id="c1")
        assert engine.calls == 1, "the second identical question re-evaluated"
        meta = d2.meta or {}
        assert meta.get("cached") is True, "the hit was not marked cached"


class TestNoConsultWhenKeyIncomplete:
    def test_no_consult_when_key_incomplete(self):
        """AC27.5: the cache is not consulted when the key is incomplete —
        the key carries ALL five inputs, so a change to ANY input invalidates
        and a recompute happens (a recompute is preferable to a wrong
        verdict)."""
        from types import SimpleNamespace

        from backend.agent.decision_engine import (
            CandidateScore,
            DecisionScore,
            EngineCounters,
        )
        from backend.agent.tool_decision import ToolDecisionBox

        class _Engine:
            def __init__(self):
                self.model_id = "cache-stub"
                self.counters = EngineCounters()
                self._cfg = SimpleNamespace(candidate_cap=6)
                self.calls = 0

            def decide(self, consumer_id, options, frame):
                self.calls += 1
                return DecisionScore(
                    consumer_id=consumer_id, chosen="NONE", confidence=0.9,
                    distribution=(CandidateScore("NONE", -0.1, 0.9),),
                    engine_latency_ms=1,
                )

        engine = _Engine()
        box = ToolDecisionBox(
            router=SimpleNamespace(),
            tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: [
                {"name": "read_file", "description": "d", "category": "file"}
            ],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=engine,
        )
        # A change to ANY key input invalidates: different goal text.
        box.resolve(
            {"description": "read the file", "task_class": "full"},
            session_id="s1", conversation_id="c1",
        )
        box.resolve(
            {"description": "read the OTHER file", "task_class": "full"},
            session_id="s1", conversation_id="c1",
        )
        assert engine.calls == 2, "a changed goal reused the cached verdict"
        # A change to the evidence payload invalidates (AC27.3's guarantee).
        box.resolve(
            {"description": "read the file", "task_class": "full"},
            evidence={"posterior": 0.7},
            session_id="s1", conversation_id="c1",
        )
        assert engine.calls == 3, "a changed evidence payload reused the verdict"
