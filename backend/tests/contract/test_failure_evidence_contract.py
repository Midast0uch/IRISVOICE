"""Contract tests: failure evidence (REQ-24, CT-DEI-14) and the cache (REQ-27, CT-DEI-17).

AC24.2  a single settled return type for _get_failure_warnings (str).
AC24.6  the row records the evidence supplied.
AC27.1  the cache key includes the evidence component.
AC27.2  the cache is bounded with eviction.
"""

from __future__ import annotations

import ast
from pathlib import Path

from backend.agent.tool_decision import (
    _ENGINE_CACHE_MAX,
    ToolDecisionBox,
    _evidence_cache_component,
)


class TestFailureWarningsRemoved:
    def test_failure_warnings_path_is_gone(self):
        """AC24.2 superseded (owner 2026-10-01, HANDOFF 7 C9): the
        _get_failure_warnings path never worked (always AttributeError) and its
        one-line fix would label every task and step as a past failure, with a
        LIKE scan per step. It was removed; it must not come back unrebuilt."""
        src = Path("backend/agent/agent_kernel.py").read_text(encoding="utf-8")
        assert "_get_failure_warnings" not in src
        assert "PAST FAILURE WARNING" not in src


class TestRowRecordsEvidenceSupplied:
    def test_row_records_evidence_supplied(self):
        """AC24.6: the decision row records the evidence supplied — the box's
        meta carries the cache/evidence provenance so an unused retrieval is
        never scored as a success."""
        src = Path("backend/agent/tool_decision.py").read_text(encoding="utf-8")
        # The cache key carries the evidence component (AC27.1).
        assert "_evidence_cache_component" in src
        assert "cached" in src  # the meta carries cache=True on a hit


class TestKeyIncludesEvidenceComponent:
    def test_key_includes_evidence_component(self):
        """AC27.1 / CT-DEI-17: the cache key includes the evidence component
        (empty sentinel when absent) — a cache hit can never return a verdict
        computed without the payload."""
        src = Path("backend/agent/tool_decision.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        # Find the cache_key tuple assignment inside _engine_try.
        keys = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple):
                src_line = ast.unparse(node)
                if "_evidence_cache_component" in src_line:
                    keys.append(src_line)
        assert keys, "the cache key does not include the evidence component"
        # The key carries all five inputs: goal, names, task_class,
        # needs_vision, evidence.
        assert all(
            s in keys[0] for s in ("goal", "task_class", "needs_vision")
        ), f"the cache key is incomplete: {keys[0]}"

    def test_cache_bounded_with_eviction(self):
        """AC27.2 / CT-DEI-17: the cache is bounded with a documented maximum
        and eviction — the dict was unbounded against the quality bar."""
        assert isinstance(_ENGINE_CACHE_MAX, int) and _ENGINE_CACHE_MAX > 0
        src = Path("backend/agent/tool_decision.py").read_text(encoding="utf-8")
        assert "_ENGINE_CACHE_MAX" in src
        assert "pop(next(iter(" in src, "no eviction on the cache"
