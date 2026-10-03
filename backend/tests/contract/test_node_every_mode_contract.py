"""V10 guard (owner 2026-10-03): nodes are universal, not developer-only.

Before: `_der_run_step_execution` sent a tool-less step to the node loop
(run_node) only when the launcher mode was "developer". Personal mode got ONE
tool picked by the decision box per step - no retry of a failed call, and the
browser's marked screenshot never reached a model.

Now:
  1. a tool-less step runs as a node in BOTH modes;
  2. the node's menu is one rule in both modes (NODE_TOOLS, screen tools only
     for a screen goal); the mode's capability filter lives in the tool
     bridge's list, not here;
  3. every node call gets the per-call bookkeeping a direct step gets (the
     web search acceptance test pins the result capture end to end).
"""

from types import SimpleNamespace

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import QueueItem

_REGISTRY = ("read_file", "run_command", "search", "crawler_query", "launch_app",
             "gui_click", "take_screenshot", "speak", "improve_self", "vision_get_context")


def _kernel(menus):
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-v10"

    def _generate(role, messages, tools=None, **kw):
        menus.append(sorted(t["function"]["name"] for t in tools or []))
        return ("Done.\nSTATUS: done", "", [])

    k._router = SimpleNamespace(generate=_generate)
    k._tool_bridge = SimpleNamespace(get_available_tools=lambda: [
        {"name": n, "description": n, "parameters": {}} for n in _REGISTRY])
    return k


@pytest.mark.parametrize("mode", ["personal", "developer"])
def test_a_toolless_step_runs_as_a_node_in_every_mode(monkeypatch, mode):
    from backend.capabilities import CapabilitySet

    monkeypatch.setattr(CapabilitySet, "get_mode", classmethod(lambda cls: mode))
    menus = []
    k = _kernel(menus)
    item = QueueItem(step_id="s1", step_number=1, description="fix the failing test")
    result, ok = AgentKernel._der_run_step_execution(k, item, None, "sess", "t", None)
    assert ok is True and result.startswith("Done.")
    assert len(menus) == 1, "the node's model was called (the one-tool box was not)"
    assert item.node_call_log == []


def test_the_node_menu_is_one_rule_and_screen_tools_need_a_screen_goal():
    menus = []
    k = _kernel(menus)
    for goal in ("fix the failing test", "click OK on the screen"):
        AgentKernel._der_run_step_execution(
            k, QueueItem(step_id="s", step_number=1, description=goal), None, "sess", "t", None)
    coding, screen = menus
    assert coding == ["crawler_query", "launch_app", "read_file", "run_command", "search"]
    assert screen == sorted(coding + ["gui_click", "take_screenshot"])
    # Never on a node menu: talking to the user, self-modification, legacy vision.
    for never in ("speak", "improve_self", "vision_get_context"):
        assert never not in screen
