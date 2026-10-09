"""Contract: every developer tool must be REACHABLE on the scored menu.

The measured defect (live, data/memory.db, d1, 225 tool_choice rows):
candidate_cap=6 reserved two slots for DELEGATE/NONE, so only FOUR real tools
reached the model. 224 of 225 rows scored the SAME six names and `write_file` -
a primary tool in a coding agent - was structurally unreachable. 53 rows (24%)
recorded a reference the model was never offered.

These tests FAIL at the old cap of 6.
"""
from __future__ import annotations

import pytest

from types import SimpleNamespace
from unittest.mock import patch

from backend.agent.decision_engine import CANDIDATE_CAP_DEFAULT, EngineCounters
from backend.agent.tool_decision import ToolDecisionBox, _DEV_MENU_ORDER

import pytest

# The shadow writer returns None before scoring when `decides()` says the
# consumer is enforced; bind the real chokepoint so the menu is actually built.
ORACLE_DECIDES = ("tool_choice",)
pytestmark = pytest.mark.usefixtures("oracle_decides_module")


class _MenuEngine:
    def __init__(self) -> None:
        self.model_id = "menu-stub"
        self.counters = EngineCounters()
        self._cfg = SimpleNamespace(candidate_cap=CANDIDATE_CAP_DEFAULT)
        self.menus: list[list[str]] = []

    def decide(self, consumer_id, options, frame):
        # `options` is a mix of CandidateScore and bare str (the two reserved
        # control labels); normalise both, as the real reader does.
        if consumer_id == "tool_choice":
            self.menus.append([
                o if isinstance(o, str) else getattr(o, "name", str(o))
                for o in options
            ])
        return None


def _menu(developer: bool, registry: list[dict]):
    engine = _MenuEngine()
    box = ToolDecisionBox(
        router=SimpleNamespace(generate=lambda *a, **k: ("", "", [])),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: list(registry),
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )
    with patch("backend.agent.tool_decision._developer_mode",
               return_value=developer):
        try:
            box.resolve({"description": "add a slugify helper",
                         "task_class": "full"},
                        session_id="s", conversation_id="c")
        except Exception:
            pass  # only the menu the engine was shown matters here
    assert engine.menus, "the engine was never asked"
    return engine.menus[0]


# Every developer tool the menu order names, in registry shape.
ALL_DEV = [{"name": n, "description": "d", "category": "file"}
           for n in _DEV_MENU_ORDER]


def test_every_developer_menu_order_tool_reaches_the_model():
    """The regression: at cap 6 only 4 of 9 survived the truncation."""
    menu = _menu(True, ALL_DEV)
    missing = [d["name"] for d in ALL_DEV if d["name"] not in menu]
    assert not missing, f"truncated off the scored menu: {missing}"


def test_write_file_is_reachable():
    assert "write_file" in _menu(True, ALL_DEV)


def test_the_control_labels_are_still_present():
    menu = _menu(True, ALL_DEV)
    assert "DELEGATE" in menu and "NONE" in menu


def test_the_cap_covers_the_dev_menu_plus_the_two_controls():
    assert CANDIDATE_CAP_DEFAULT >= len(_DEV_MENU_ORDER) + 2


def test_menu_width_is_unchanged_between_modes():
    """Same property as test_oracle_dev_menu_order.py: for the SAME registry the
    two modes produce the same width (the cap is a ceiling, not a fixed count)."""
    dev = _menu(True, ALL_DEV)
    plain = _menu(False, ALL_DEV)
    assert len(dev) == len(plain)