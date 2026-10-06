"""Contract tests: CT-DEI-17 — the engine result cache (REQ-27, T37).

AC27.1  the cache key includes EVERY input that can change the verdict,
        including the evidence payload — present from day one even while that
        payload is always empty.
AC27.2  the cache is bounded, with a documented maximum and an eviction policy.

AC27.3/27.4/27.5 are pinned by `tests/unit/test_cache_key.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import backend.agent.tool_decision as td
from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)

import pytest

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the
# real enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ('tool_choice',)
pytestmark = pytest.mark.usefixtures("oracle_decides_module")

MENU = [
    {"name": "search", "description": "instant lookup", "category": "web"},
    {"name": "crawler_query", "description": "deep crawl", "category": "web"},
    {"name": "speak", "description": "speak", "category": "system"},
]


class _CountingEngine:
    def __init__(self, chosen="search", confidence=0.95):
        self._chosen, self._conf = chosen, confidence
        self.model_id = "cache-stub"
        self.counters = EngineCounters()
        self.calls = 0

    def decide(self, consumer_id, options, frame):
        self.calls += 1
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.05)
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
    return td.ToolDecisionBox(
        router=SimpleNamespace(generate=lambda *a, **kw: ("", "", [])),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: MENU,
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestKeyIncludesEvidence:
    def test_key_includes_evidence_component(self):
        """AC27.1/AC27.3: two different evidence payloads must NOT share a
        cached verdict — the engine is asked twice."""
        engine = _CountingEngine()
        box = _box(engine)

        step = {"description": "find the price", "task_class": "full"}
        box.resolve(step, evidence={"prior": {"lower_bound": 0.1}},
                    session_id="s1", conversation_id="c1")
        first = engine.calls
        box.resolve(step, evidence={"prior": {"lower_bound": 0.8}},
                    session_id="s1", conversation_id="c1")

        assert first == 1
        assert engine.calls == 2, (
            "the second payload reused the first payload's cached verdict — "
            "the evidence component is missing from the cache key (AC27.1)"
        )

    def test_identical_inputs_still_hit_the_cache(self):
        """The evidence component must not defeat caching entirely."""
        engine = _CountingEngine()
        box = _box(engine)

        step = {"description": "find the price", "task_class": "full"}
        box.resolve(step, session_id="s1", conversation_id="c1")
        box.resolve(step, session_id="s1", conversation_id="c1")

        assert engine.calls == 1, "the identical question was re-scored"

    def test_empty_evidence_sentinel_is_stable(self):
        """AC27.1 edge: the absent-evidence sentinel is stable, so the cache
        still functions while the payload is always empty."""
        assert td._evidence_cache_component(None) == ""
        assert td._evidence_cache_component({}) == ""
        assert td._evidence_cache_component({"a": 1}) != ""


class TestCacheBounded:
    def test_cache_bounded_with_eviction(self, monkeypatch):
        """AC27.2: a documented maximum with LRU eviction — memory bounded."""
        monkeypatch.setattr(td, "_ENGINE_CACHE_MAX", 4)
        engine = _CountingEngine()
        box = _box(engine)

        for i in range(12):
            box.resolve(
                {"description": f"distinct goal number {i}", "task_class": "full"},
                session_id="s1", conversation_id="c1",
            )

        assert len(box._engine_cache) <= 4, (
            f"the engine cache grew to {len(box._engine_cache)} entries — "
            "unbounded (AC27.2, AGENTS.md quality bar)"
        )
        assert len(box._engine_cache) > 0

    def test_eviction_is_lru_not_fifo(self, monkeypatch):
        """AC27.2: the documented policy is LRU — a re-asked question stays hot
        and does not cost a second model call."""
        monkeypatch.setattr(td, "_ENGINE_CACHE_MAX", 2)
        engine = _CountingEngine()
        box = _box(engine)

        step_a = {"description": "goal A", "task_class": "full"}
        box.resolve(step_a, session_id="s1", conversation_id="c1")   # A (call 1)
        box.resolve({"description": "goal B", "task_class": "full"},
                    session_id="s1", conversation_id="c1")           # B (call 2)
        box.resolve(step_a, session_id="s1", conversation_id="c1")   # A re-hit
        calls_after_rehit = engine.calls

        assert calls_after_rehit == 2, (
            "re-asking a question did not hit the cache"
        )
        # C evicts the least-recently-used entry (B, not the re-hit A)
        box.resolve({"description": "goal C", "task_class": "full"},
                    session_id="s1", conversation_id="c1")
        box.resolve(step_a, session_id="s1", conversation_id="c1")

        assert engine.calls == 3, (
            "the re-asked A was evicted — the policy is FIFO, not LRU (AC27.2)"
        )
