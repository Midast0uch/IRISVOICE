"""The shadow tool_choice row scores the menu the Brain was OFFERED (2026-10-01).

WHY THIS FILE EXISTS

The shadow scorer (`ToolDecisionBox.record_shadow_tool_choice`) pairs the
Oracle's pick with the tool the Brain actually called. Both kernel callers
passed no menu, so the scorer cut the WHOLE registry to the cap in list order -
and the registry lists the vision tools first. Measured on data/memory.db
(active engine gliner25-decide-onnx-int8): 278 of 278 shadow rows since
2026-09-29 had a menu of four vision tools + DELEGATE + NONE while the Brain
called read_file / run_command / edit_file. The Brain's tool was never on the
menu, so every row read "disagree" (accuracy 0.0) and the calibration numbers
for tool_choice measured nothing. The engine route had the same defect and was
fixed on 2026-09-29 (`_DEV_MENU_ORDER`); the shadow path never got that fix.

Pinned here:
  1. both kernel callers pass the offered tools as `candidates`;
  2. the shadow orders the menu with the engine route's ONE rule
     (`_order_engine_names`), so a coding menu leads with the coding tools;
  3. a vision tool the Brain was not offered never enters the menu.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.agent.decision_engine import CandidateScore, DecisionScore, EngineCounters

_REPO = Path(__file__).resolve().parents[3]

# Real registry order: vision tools first (the cause of the defect).
_REGISTRY = (
    [{"name": n, "category": "vision"} for n in (
        "vision_detect_element", "vision_analyze_screen",
        "vision_validate_action", "vision_get_context")]
    + [{"name": n, "category": "filesystem"} for n in (
        "read_file", "edit_file", "write_file", "grep_files", "glob_files",
        "list_directory", "create_directory", "run_command", "git_status",
        "git_diff")]
)
_NODE_TOOLS = [
    "read_file", "edit_file", "write_file", "grep_files", "glob_files",
    "list_directory", "create_directory", "run_command", "git_status", "git_diff",
]


class _Engine:
    model_id = "menu-stub"

    def __init__(self):
        self.counters = EngineCounters()
        self.menus: list = []

    def decide(self, consumer_id, options, frame):
        self.menus.append(list(options))
        return DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.5,
            distribution=tuple(CandidateScore(o, -0.1, 0.1) for o in options),
            engine_latency_ms=1,
        )


class _Bridge:
    def __init__(self):
        self.rows: list = []

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.rows.append(dict(meta))


class _Router:
    def generate(self, role, messages, **kwargs):
        return ("", "", [])


def _box(engine):
    from backend.agent.tool_decision import ToolDecisionBox

    return ToolDecisionBox(
        router=_Router(), tool_bridge=_Bridge(),
        get_available_tools=lambda: list(_REGISTRY),
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


@pytest.fixture
def developer(monkeypatch):
    monkeypatch.setattr("backend.agent.tool_decision._developer_mode", lambda: True)


def test_kernel_callers_pass_the_offered_menu():
    """Both shadow callers must pass `candidates`; without it the scorer falls
    back to the registry head (the vision tools)."""
    src = (_REPO / "backend" / "agent" / "agent_kernel.py").read_text(
        encoding="utf-8", errors="replace")
    calls = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "record_shadow_tool_choice"
    ]
    assert len(calls) == 2, f"expected the 2 known callers, found {len(calls)}"
    for c in calls:
        assert "candidates" in {k.arg for k in c.keywords}, (
            f"agent_kernel.py:{c.lineno} scores the registry head, not the "
            "menu the Brain was offered")


def test_coding_node_menu_leads_with_coding_tools(developer):
    eng = _Engine()
    row = _box(eng).record_shadow_tool_choice(
        goal="fix the off-by-one error in utils.py",
        observed_tool="read_file", candidates=_NODE_TOOLS,
    )
    menu = eng.menus[0]
    assert len(menu) == 6, "the calibrated width must not change"
    assert menu[:4] == ["read_file", "edit_file", "grep_files", "run_command"]
    assert not [n for n in menu if n.startswith("vision_")]
    assert row["brain_choice"] in menu


def test_vision_tool_not_offered_never_enters_menu():
    eng = _Engine()
    _box(eng).record_shadow_tool_choice(
        goal="take a screenshot and look at the screen",
        observed_tool="read_file", candidates=["read_file", "run_command"],
    )
    assert not [n for n in eng.menus[0] if n.startswith("vision_")]
