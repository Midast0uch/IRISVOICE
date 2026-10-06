"""Contract tests: CT-DEI-7 No-Bypass Coverage (REQ-16 AC16.2, T20).

CT-DEI-7 — every tool-choice path (`propose()`, RespondDirect, the box) emits
an engine row (deciding or shadow); a path with zero rows fails the suite.

The RespondDirect ReAct loop runs inside a live kernel, so its seam is pinned
two ways: the kernel must really CALL the shadow recorder (an AST check — a
mention in a comment cannot satisfy it), and the recorder itself must emit a
well-formed row.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from backend.agent.decision_engine import (
    ArgsResult,
    CandidateScore,
    DecisionScore,
    EngineCounters,
)

import pytest

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the
# real enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ('tool_choice',)
pytestmark = pytest.mark.usefixtures("oracle_decides_module")

_REPO_ROOT = Path(__file__).resolve().parents[3]


class _RowBridge:
    """Captures every row the box writes through its single ledger writer."""

    def __init__(self):
        self.rows: list = []

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.rows.append((dict(meta), kind, session_id))


class _Engine:
    def __init__(self, chosen="read_file", confidence=0.91):
        self._chosen = chosen
        self._conf = confidence
        self.model_id = "bypass-stub"
        self.counters = EngineCounters()

    def decide(self, consumer_id, options, frame):
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.02)
                for o in options
            ),
            engine_latency_ms=2,
        )

    def fast_path_args(self, option, schema, frame):
        return ArgsResult(args={"query": frame.get("goal", "")}, retried=False)

    def generate_args(self, consumer_id, option, schema, frame):
        return ArgsResult(args=None, retried=False)


class _Router:
    """Minimal router: no `resolve`, so the box stays on the reasoning binding."""

    def __init__(self):
        self.calls = 0

    def generate(self, role, messages, **kwargs):
        self.calls += 1
        return ("", "", [])


def _box(engine, bridge):
    from backend.agent.tool_decision import ToolDecisionBox

    return ToolDecisionBox(
        router=_Router(),
        tool_bridge=bridge,
        get_available_tools=lambda: [
            {"name": "read_file", "category": "filesystem"},
            {"name": "run_command", "category": "shell"},
        ],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestNoBypassCoverage:
    def test_all_paths_emit_rows(self, monkeypatch):
        """CT-DEI-7: propose(), the box, and RespondDirect each emit a row."""
        monkeypatch.setattr(
            "backend.agent.tool_registry.validate_tool_call",
            lambda t, p: (True, ""),
        )
        engine = _Engine()

        # ── path 1: propose() ──────────────────────────────────────────────
        from backend.agent.explorer import propose

        propose_rows: list = []
        propose(
            goal="read the readme",
            evidence="",
            live_tools=[{"name": "read_file",
                         "parameters": {"properties": {"query": {}}}}],
            infer=lambda *a, **kw: None,
            engine=engine,
            row_sink=propose_rows.append,
        )
        assert propose_rows, "propose() emitted no engine row (CT-DEI-7)"
        assert propose_rows[0]["consumer_id"] == "tool_choice"

        # ── path 2: the box ────────────────────────────────────────────────
        # DELEGATE always escalates, so the decision lands on the route-only
        # row writer — the same single writer tool executions use.
        bridge = _RowBridge()
        box = _box(_Engine(chosen="DELEGATE", confidence=0.99), bridge)
        box.resolve(step={"description": "read the readme"})
        assert bridge.rows, "the box emitted no engine row (CT-DEI-7)"
        assert bridge.rows[0][0]["consumer_id"] == "tool_choice"

        # ── path 3: RespondDirect ──────────────────────────────────────────
        src = (_REPO_ROOT / "backend" / "agent" / "agent_kernel.py").read_text(
            encoding="utf-8", errors="replace")
        called = {
            node.func.attr
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert "record_shadow_tool_choice" in called, (
            "RespondDirect no longer CALLS the shadow recorder — that path is "
            "a blind spot for calibration (CT-DEI-7)"
        )

        rd_bridge = _RowBridge()
        rd_box = _box(engine, rd_bridge)
        row = rd_box.record_shadow_tool_choice(
            goal="what is the weather in Paris",
            observed_tool="crawler_query",
            observed_params={"query": "weather Paris"},
            session_id="conv-1",
            conversation_id="conv-1",
        )
        assert row is not None, "the RespondDirect recorder emitted no row"
        assert row["consumer_id"] == "tool_choice"
        assert row["shadow"] is True
        assert row["brain_choice"] == "crawler_query"
        assert rd_bridge.rows, "the row never reached the ledger writer"

    def test_no_engine_emits_nothing(self):
        """A missing engine must never fabricate a row (T17/T18 convention)."""
        bridge = _RowBridge()
        box = _box(None, bridge)
        assert box.record_shadow_tool_choice(
            goal="g", observed_tool="read_file") is None
        assert bridge.rows == []

    def test_async_mode_never_blocks_and_returns_none(self):
        """REQ-16 edge: the fast chat path must not pay engine latency."""
        bridge = _RowBridge()
        box = _box(_Engine(), bridge)
        assert box.record_shadow_tool_choice(
            goal="g", observed_tool="read_file", async_=True) is None
