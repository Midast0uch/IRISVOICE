"""Regression (execution audit, 2026-09-29): in developer mode the Oracle's
tool menu carries the coding tools, ripgrep search included.

The menu is cut to the candidate cap in LIST order and the registry lists
vision/web tools first, so a coding step was scored against tools it could
never need while read_file / grep_files never reached the scorer. The first
test fails on that code.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.agent.decision_engine import CandidateScore, DecisionScore, EngineCounters
from backend.agent.tool_decision import ToolDecisionBox

import pytest

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the
# real enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ('tool_choice',)
pytestmark = pytest.mark.usefixtures("oracle_decides_module")

REGISTRY_ORDER = [
    {"name": "vision_detect_element", "description": "d", "category": "vision"},
    {"name": "vision_analyze_screen", "description": "d", "category": "vision"},
    {"name": "take_screenshot", "description": "d", "category": "vision"},
    {"name": "open_url", "description": "d", "category": "web"},
    {"name": "read_file", "description": "d", "category": "file"},
    {"name": "grep_files", "description": "d", "category": "file"},
    {"name": "write_file", "description": "d", "category": "file"},
    {"name": "run_command", "description": "d", "category": "shell"},
]


class _MenuEngine:
    def __init__(self):
        self.model_id = "menu-stub"
        self.counters = EngineCounters()
        self._cfg = SimpleNamespace(candidate_cap=6)
        self.menus = []

    def decide(self, consumer_id, options, frame):
        if consumer_id == "tool_choice":
            self.menus.append(list(options))
        return DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.1,
            distribution=tuple(CandidateScore(o, -1.0, 0.1) for o in options),
            engine_latency_ms=1,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        from backend.agent.decision_engine import ArgsResult

        return ArgsResult(args={}, retried=False)


def _menu(developer: bool):
    engine = _MenuEngine()
    box = ToolDecisionBox(
        router=SimpleNamespace(generate=lambda *a, **k: ("", "", [])),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: list(REGISTRY_ORDER),
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )
    with patch("backend.agent.tool_decision._developer_mode", return_value=developer):
        try:
            box.resolve({"description": "find where parse_duration is defined",
                         "task_class": "full"}, session_id="s", conversation_id="c")
        except Exception:
            pass  # only the menu the engine was shown matters here
    assert engine.menus, "the engine was never asked"
    return engine.menus[0]


def test_developer_menu_offers_read_and_ripgrep():
    menu = _menu(developer=True)
    assert "read_file" in menu and "grep_files" in menu
    assert "vision_detect_element" not in menu


def test_menu_width_is_unchanged():
    assert len(_menu(developer=True)) == len(_menu(developer=False))
