"""Every tool the node loop can offer declares how the Oracle chooses it (2026-10-11).

The decision model reads one short "when to choose" line beside each option
code. A tool added to the node menu without a line would be offered to the
Oracle with argument-oriented LLM text it was never shaped for - so a new tool
must declare its line here before it ships. The menu fingerprint pins that a
re-described tool is a different menu (its old evidence never carries over).
"""

from backend.agent.node_executor import NODE_SCREEN_TOOLS, NODE_TOOLS
from backend.agent.tool_decision import _menu_fingerprint
from backend.agent.tool_registry import ORACLE_HINTS, oracle_hint


def test_every_node_tool_and_control_label_has_a_decision_line():
    missing = [n for n in (*NODE_TOOLS, "DELEGATE", "NONE") if not ORACLE_HINTS.get(n)]
    assert not missing, f"tools with no Oracle decision line: {missing}"


def test_decision_lines_are_short():
    long_lines = {n: len(h) for n, h in ORACLE_HINTS.items() if len(h) > 120}
    assert not long_lines, f"decision lines over 120 chars: {long_lines}"


def test_an_undeclared_tool_falls_back_to_its_first_sentence():
    assert oracle_hint("brand_new_tool", "Do a thing. With details.") == "Do a thing"
    assert oracle_hint("brand_new_tool") == "brand new tool"
    assert set(NODE_SCREEN_TOOLS)  # the screen tools fall back until declared


def test_a_redescribed_tool_changes_the_menu_fingerprint():
    menu = ["read_file", "edit_file", "DELEGATE", "NONE"]
    a = _menu_fingerprint(menu, {"read_file": "Read a file", "edit_file": "Edit"})
    b = _menu_fingerprint(menu, {"read_file": "Read a file", "edit_file": "Edit a read file"})
    c = _menu_fingerprint(menu + ["write_file"], {"read_file": "Read a file", "edit_file": "Edit"})
    assert len({a, b, c}) == 3
