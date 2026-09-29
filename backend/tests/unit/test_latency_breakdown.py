"""Unit tests: the latency breakdown (REQ-26 AC26.2/AC26.3).

AC26.2  the three latency fields are emitted on a real decision.
AC26.3  lock-wait is separated from compute.
"""

from __future__ import annotations

import logging

import pytest

from backend.agent.decision_engine import DecisionEngine, EngineConfig
from backend.tests.unit.test_decision_engine import FakeOnnxBackend


def _engine(**over):
    cfg = EngineConfig(**over)
    from backend.tests.unit.test_decision_engine import FakeLlama

    return DecisionEngine(
        config=cfg, backend_factory=lambda **kw: FakeOnnxBackend(**kw),
        llama_factory=lambda **kw: FakeLlama(**kw),
    )


class TestThreeLatencyFieldsEmitted:
    def test_three_latency_fields_emitted(self, caplog):
        """AC26.2: scoring_latency_ms / decision_latency_ms are emitted on a
        real decision (args_latency_ms on a generate_args call)."""
        e = _engine()
        with caplog.at_level(logging.INFO, logger="decision_engine"):
            e.decide("tool_choice", ["a", "b"], {"goal": "g"})
        lines = [r.getMessage() for r in caplog.records
                 if "scoring_latency_ms" in r.getMessage()]
        assert lines, "no latency breakdown emitted on a real decision"
        assert "decision_latency_ms" in lines[0]
        assert "lock_wait_ms" in lines[0]

    def test_args_latency_emitted(self, caplog):
        """AC26.2: args_latency_ms is emitted on a generate_args call."""
        e = _engine()
        e._load()
        e._llm.args_replies = ['{"url": "u"}']
        with caplog.at_level(logging.INFO, logger="decision_engine"):
            e.generate_args("tool_choice", "crawler_query",
                            {"properties": {"url": {}}, "required": []},
                            {"goal": "g"})
        lines = [r.getMessage() for r in caplog.records
                 if "args_latency_ms" in r.getMessage()]
        assert lines, "no args latency emitted"


class TestLockWaitSeparatedFromCompute:
    def test_lock_wait_separated_from_compute(self, caplog):
        """AC26.3: lock-wait is separated from compute — the log line carries
        BOTH fields, so a slow acquire is attributable to the wait, not the
        scoring."""
        e = _engine()
        with caplog.at_level(logging.INFO, logger="decision_engine"):
            e.decide("tool_choice", ["a", "b"], {"goal": "g"})
        lines = [r.getMessage() for r in caplog.records
                 if "scoring_latency_ms" in r.getMessage()]
        assert lines and "lock_wait_ms" in lines[0], (
            "lock-wait must be separated from compute in the log line"
        )


class TestFastPathArgsNearZeroPresent:
    def test_fast_path_args_near_zero_present(self):
        """AC26.5: the fast-path args latency is near-zero and present — the
        deterministic mapping carries no generation cost."""
        import time

        e = _engine()
        t0 = time.perf_counter()
        r = e.fast_path_args(
            "search",
            {"properties": {"query": {"type": "string"}}, "required": ["query"]},
            {"goal": "find the price"},
        )
        ms = (time.perf_counter() - t0) * 1000
        assert r is not None and r.args == {"query": "find the price"}
        assert ms < 5, f"the fast path took {ms:.1f}ms (must be near-zero)"
