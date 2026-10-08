"""CT-VETO-1: the execution-policy veto is applied WHERE THE MENU IS BUILT.

specs/phonon2-d1-model-swap REQ-10 (T4.1, B5). The measured bypass class: a
vetoed tool reached a route that never saw the set — the legacy/propose path
built the Brain's function schemas from the UNFILTERED list, so the Brain
could pick a vetoed tool and the guard fired only AFTER the wasted call.

This contract fails on the pre-fix shape: a vetoed tool in the candidate
list must never survive into any route's menu — engine composition, legacy
schemas, or the memory fallback's registry check.

Run: python -m pytest backend/tests/contract/test_veto_menu_build_contract.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = (REPO / "backend" / "agent" / "tool_decision.py").read_text(encoding="utf-8")


def _tools(*names):
    return [{"name": n, "description": f"the {n} tool"} for n in names]


class TestVetoFilterAtMenuBuild:

    def test_veto_filter_removes_vetoed_names(self):
        """The shared filter: a vetoed tool never survives composition."""
        from backend.agent.tool_decision import ToolDecisionBox

        out = ToolDecisionBox._veto_filter(
            _tools("read_file", "crawler_query", "list_directory", "web_search"),
            {"crawler_query", "web_search"},
        )
        assert [t["name"] for t in out] == ["read_file", "list_directory"]

    def test_veto_filter_empty_set_is_identity(self):
        from backend.agent.tool_decision import ToolDecisionBox

        tools = _tools("read_file", "web_search")
        assert ToolDecisionBox._veto_filter(tools, set()) == tools
        assert ToolDecisionBox._veto_filter([], {"x"}) == []

    def test_legacy_propose_schemas_are_veto_filtered(self):
        """CT-VETO-1 (source contract): the legacy/propose route filters its
        candidate list BEFORE building tool_list and to_function_schema —
        the Brain never sees a vetoed tool. Pre-fix, the schemas came from
        the unfiltered list and the guard fired only after the pick."""
        assert "_veto_filter(pre_filtered, _vetoed)" in SRC, (
            "the legacy/propose route must filter its candidates at build "
            "time (REQ-10 AC10.1), not guard the pick after the fact"
        )
        # The filter call must come BEFORE the schema build.
        i_filter = SRC.index("_veto_filter(pre_filtered, _vetoed)")
        i_schemas = SRC.index("to_function_schema(pre_filtered)")
        assert i_schemas > i_filter, (
            "the veto filter must run before to_function_schema builds the "
            "Brain's tool list"
        )

    def test_engine_menu_composition_uses_the_filter(self):
        """The engine route composes from the same filtered list (the
        session-366 line 1030 behaviour, now through the shared filter)."""
        assert SRC.count("_veto_filter(") >= 2, (
            "both menu-build sites (engine + legacy) must use the shared filter"
        )

    def test_memory_fallback_refuses_vetoed_picks(self):
        """The memory route's guard stays (defence in depth): a memory
        suggestion of a vetoed tool is refused, never returned."""
        assert "mtool and mtool in (vetoed or ())" in SRC or (
            "mtool in _vetoed" in SRC
        ), "the memory fallback must keep refusing vetoed suggestions"
