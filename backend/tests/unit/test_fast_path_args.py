"""Unit tests: deterministic fast-path slot filling (REQ-2, T2).

AC2.1  single-slot query mapping.
AC2.2  generate_args autoregressive generation bypassed entirely.
AC2.3  zero token-generation time.
AC2.4  complex schemas fall back to the generation path.
"""

from __future__ import annotations

from backend.agent.decision_engine import (
    ArgsResult,
    DecisionEngine,
    EngineConfig,
)
from backend.tests.unit.test_decision_engine import FakeLlama, FakeOnnxBackend


QUERY_SCHEMA = {"properties": {"query": {"type": "string"}}, "required": ["query"]}
COMPLEX_SCHEMA = {
    "properties": {"url": {"type": "string"}, "limit": {"type": "integer"}},
    "required": ["url", "limit"],
}
FRAME = {"goal": "find the current price of a product online"}


def _engine() -> DecisionEngine:
    return DecisionEngine(
        config=EngineConfig(),
        backend_factory=lambda **kw: FakeOnnxBackend(**kw),
        llama_factory=lambda **kw: FakeLlama(**kw),
    )


class TestSingleSlotQueryMapping:
    def test_single_slot_query_mapping(self):
        """AC2.1: the goal text maps directly to the 'query' parameter."""
        e = _engine()
        r = e.fast_path_args("search", QUERY_SCHEMA, FRAME)
        assert r is not None and r.args == {"query": FRAME["goal"]}
        r = e.fast_path_args("crawler_query", QUERY_SCHEMA, FRAME)
        assert r is not None and r.args == {"query": FRAME["goal"]}


class TestBypassAutoregressiveGen:
    def test_bypass_autoregressive_gen(self):
        """AC2.2: the fast path bypasses generate_args entirely — no
        completion call is made."""
        e = _engine()
        e._load()
        r = e.fast_path_args("search", QUERY_SCHEMA, FRAME)
        assert r is not None and r.args is not None
        assert e._llm.completion_calls == [], (
            "the fast path must bypass autoregressive generation (AC2.2)"
        )


class TestZeroTokenGenerationTime:
    def test_zero_token_generation_time(self):
        """AC2.3: zero token-generation time — the mapping is deterministic."""
        import time

        e = _engine()
        t0 = time.perf_counter()
        for _ in range(100):
            e.fast_path_args("search", QUERY_SCHEMA, FRAME)
        ms = (time.perf_counter() - t0) * 1000
        assert ms < 50, f"100 fast-path mappings took {ms:.1f}ms"


class TestComplexSchemaFallback:
    def test_complex_schema_fallback(self):
        """AC2.4: a multi-arg schema falls back to the generation path —
        the fast path returns None."""
        e = _engine()
        assert e.fast_path_args("search", COMPLEX_SCHEMA, FRAME) is None
        assert e.fast_path_args("read_file", QUERY_SCHEMA, FRAME) is None

    def test_empty_goal_falls_back(self):
        """An empty/invalid goal falls back (error-handling row)."""
        e = _engine()
        assert e.fast_path_args("search", QUERY_SCHEMA, {"goal": ""}) is None
        assert e.fast_path_args("search", QUERY_SCHEMA, {"goal": "   "}) is None
