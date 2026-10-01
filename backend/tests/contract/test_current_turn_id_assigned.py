"""`AgentKernel._current_turn_id` has a writer at the turn entry (2026-10-01).

13 sites in agent_kernel.py and tool_bridge.py read `_current_turn_id` (with a
getattr default) - render_document's card turn, tool-bridge rows, card
snapshots. Nothing assigned it, so every read returned None and a card
rendered by the tool never joined its live turn (HANDOFF 6 finding). A read
with a silent default and no writer is the hidden-failure shape: the code
runs, the tests are green, the value is always None.
"""
from __future__ import annotations

import ast
from pathlib import Path

_KERNEL = Path(__file__).resolve().parents[2] / "agent" / "agent_kernel.py"


def _assigns_current_turn_id(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and t.attr == "_current_turn_id"
                        and isinstance(t.value, ast.Name) and t.value.id == "self"):
                    return True
    return False


def test_turn_entry_assigns_current_turn_id():
    tree = ast.parse(_KERNEL.read_text(encoding="utf-8", errors="replace"))
    entry = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "process_text_message"
    ]
    assert len(entry) == 1, "the turn entry point moved - update this guard"
    assert _assigns_current_turn_id(entry[0]), (
        "process_text_message must set self._current_turn_id: its readers "
        "otherwise always see None")


def test_turn_id_reaches_the_attribute():
    """Run the assignment's own lines: the value read is the turn id passed in."""
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    # Executing the whole entry point needs a live kernel; the assignment is
    # pinned structurally above and by value here through a minimal call that
    # stops right after it (the first collaborator the entry touches raises).
    class _Stop(Exception):
        pass

    def _boom(*a, **kw):
        raise _Stop

    k.clear_turn_trust_flag = lambda: None
    k.session_id = "s"
    import backend.agent.event_oracle as eo

    orig = eo.observe_user_message
    eo.observe_user_message = lambda *a, **kw: None
    import backend.agent.agent_kernel as ak

    orig_metrics = ak.TurnMetrics
    ak.TurnMetrics = _boom
    try:
        try:
            k.process_text_message("hi", session_id="s", conversation_id="c",
                                   turn_id="turn-42")
        except _Stop:
            pass
    finally:
        eo.observe_user_message = orig
        ak.TurnMetrics = orig_metrics
    assert k._current_turn_id == "turn-42"
