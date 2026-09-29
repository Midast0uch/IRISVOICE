"""Unit tests: decision telemetry (REQ-6 AC6.4/AC6.6, T27).

AC6.4  the full distribution is persisted per decision row.
AC6.6  a truncation that actually cuts content emits a structured event.
"""

from __future__ import annotations

import logging

from types import SimpleNamespace

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.tool_decision import ToolDecisionBox


class _DistEngine:
    def __init__(self):
        self.model_id = "telemetry-stub"
        self.counters = EngineCounters()
        self._cfg = SimpleNamespace(candidate_cap=6)

    def decide(self, consumer_id, options, frame):
        return DecisionScore(
            consumer_id=consumer_id, chosen="read_file", confidence=0.9,
            distribution=tuple(
                CandidateScore(o, -0.1 * i, 0.9 / (i + 1))
                for i, o in enumerate(options)
            ),
            engine_latency_ms=1,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        from backend.agent.decision_engine import ArgsResult

        return ArgsResult(args={"query": "x"}, retried=False)


def _box(engine, long_desc=False) -> ToolDecisionBox:
    desc = "d" * 200 if long_desc else "short desc"
    return ToolDecisionBox(
        router=SimpleNamespace(),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: [
            {"name": "read_file", "description": desc, "category": "file"},
            {"name": "speak", "description": "d", "category": "system"},
        ],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestDistributionPersistedPerRow:
    def test_distribution_persisted_per_row(self):
        """AC6.4: the full distribution rides the decision row — the
        reliability curve reads the whole menu, not just the winner."""
        engine = _DistEngine()
        box = _box(engine)
        decision = box.resolve(
            {"description": "read the file", "task_class": "full"},
            session_id="s1", conversation_id="c1",
        )
        meta = decision.meta or {}
        dist = meta.get("distribution")
        assert dist, "no distribution on the row"
        assert len(dist) == len(meta.get("candidate_names") or [])
        assert all("name" in d and "prob" in d for d in dist)


class TestTruncationEventEmitted:
    def test_truncation_event_emitted(self, caplog):
        """AC6.6: a truncation that actually cuts content emits a structured
        event (field + original length) — never decided silently."""
        engine = _DistEngine()
        box = _box(engine, long_desc=True)
        with caplog.at_level(logging.INFO):
            box.resolve(
                {"description": "x" * 300, "task_class": "full"},
                session_id="s1", conversation_id="c1",
            )
        truncs = [r.getMessage() for r in caplog.records
                  if "truncation field=" in r.getMessage()]
        assert truncs, "a silent cut happened with no event"
        assert "option_description" in truncs[0]
        assert "original_len=200" in truncs[0]

    def test_no_truncation_event_when_nothing_cut(self, caplog):
        """No cut → no event (the signal is honest in both directions)."""
        engine = _DistEngine()
        box = _box(engine, long_desc=False)
        with caplog.at_level(logging.INFO):
            box.resolve(
                {"description": "short goal", "task_class": "full"},
                session_id="s1", conversation_id="c1",
            )
        truncs = [r.getMessage() for r in caplog.records
                  if "truncation field=" in r.getMessage()]
        assert not truncs


# ── REQ-10 AC10.3 (T13): the fast path is logged with its pattern id ────────


class TestFastPathPatternLogged:
    def test_fast_path_pattern_logged(self, caplog):
        """AC10.3: `is_fast_path=true` plus the matched pattern id are emitted
        (and ride the decision meta) so calibration can join on them."""
        from backend.agent.decision_engine import (
            ArgsResult,
            DecisionEngine,
            EngineConfig,
        )
        from backend.agent.tool_registry import register_builtin_tools
        from backend.agent.tool_decision import DecisionKind

        register_builtin_tools()
        engine = DecisionEngine(config=EngineConfig())
        engine.decide = lambda consumer_id, options, frame: DecisionScore(  # type: ignore[method-assign]
            consumer_id=consumer_id, chosen="vision_detect_element",
            confidence=0.95,
            distribution=(CandidateScore("vision_detect_element", -0.05, 0.95),),
            engine_latency_ms=1,
        )

        def _boom(*a, **kw):
            raise AssertionError(
                "generate_args was reached — the vision fast path did not fire"
            )

        engine.generate_args = _boom  # type: ignore[method-assign]

        box = ToolDecisionBox(
            router=SimpleNamespace(),
            tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: [
                {"name": "vision_detect_element",
                 "description": "Detect a GUI element",
                 "category": "vision"},
                {"name": "speak", "description": "d", "category": "system"},
            ],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=engine,
        )

        with caplog.at_level(logging.INFO):
            d = box.resolve(
                {"description": 'click "Submit Order"', "task_class": "full"},
                session_id="s1", conversation_id="c1",
            )

        assert d.kind == DecisionKind.TOOL
        assert d.params == {"description": "Submit Order"}
        assert d.meta["is_fast_path"] is True
        assert d.meta["fast_path_pattern"] == "quoted_target"

        logged = [r.getMessage() for r in caplog.records
                  if "is_fast_path=true" in r.getMessage()]
        assert logged, "no is_fast_path=true log line (AC10.3)"
        assert "pattern=quoted_target" in logged[0]

