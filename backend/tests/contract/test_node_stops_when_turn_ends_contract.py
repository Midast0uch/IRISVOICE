"""Contract: a node does no work after its turn ends.

Derived from eval C c04 (2026-10-02, conv-622): the 600 s turn budget sent the
reply while a recovery node was starting in a batch thread. The turn's finally
made the router's choke check inert, and the node kept making model calls and
tool calls (write_file, run_command) for 3 minutes, into the next task.

Drives the REAL ``AgentKernel._der_run_node`` adapter and the REAL
``run_node`` loop with a stand-in router and tool box.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel

_TOOLS = [{"type": "function", "function": {
    "name": "run_command", "description": "run", "parameters": {"type": "object", "properties": {}}}}]
_CALL = [{"id": "c1", "function": {"name": "run_command",
                                   "arguments": '{"command": "python -m pytest -q"}'}}]


def _kernel(on_generate=None):
    gen_calls, dispatched = [], []
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-node-turn"
    k._tool_bridge = None
    k._der_turn_id = "turn-1"
    k._der_turn_active = True
    k._der_stop_requested = False

    class _Router:
        last_usage = None

        def generate(self, role, messages, **kw):
            gen_calls.append(role)
            if on_generate:
                on_generate(k, len(gen_calls))
            if len(gen_calls) == 1:
                return "", "", _CALL
            return "STATUS: done", "", []

        def resolve(self, role):
            return SimpleNamespace(id="same-model")

    class _Box:
        def dispatch(self, decision, **kw):
            dispatched.append(decision.tool)
            return SimpleNamespace(result={"success": True, "result": "1 passed"}, error="")

        def record_shadow_tool_choice(self, **kw):
            pass

    k._router = _Router()
    k._get_tool_box = lambda: _Box()
    k._get_openai_tools = lambda: _TOOLS
    k._accrue_tokens = lambda *a, **kw: None
    k._der_tool_deadline = lambda name: 30.0
    k._format_tool_result_for_step = lambda raw, name: str(raw)
    return k, gen_calls, dispatched


def _item():
    return SimpleNamespace(description="run the tests", objective_anchor="",
                           expected_output="", parent_description="", review_feedback="")


def test_a_node_in_a_live_turn_works():
    k, gen_calls, dispatched = _kernel()
    _text, ok = k._der_run_node(_item(), "sess", "turn-1", [])
    assert ok and dispatched == ["run_command"] and len(gen_calls) == 2


def test_a_node_after_the_turn_ended_makes_no_call():
    k, gen_calls, dispatched = _kernel()
    k._der_turn_active = False                      # the reply was sent
    _text, ok = k._der_run_node(_item(), "sess", "turn-1", [])
    assert not ok and gen_calls == [] and dispatched == []


def test_a_node_of_a_stopped_turn_makes_no_call():
    k, gen_calls, dispatched = _kernel()
    k._der_stop_requested = True                    # budget exhausted / user stop
    _text, ok = k._der_run_node(_item(), "sess", "turn-1", [])
    assert not ok and gen_calls == [] and dispatched == []


def test_a_node_of_an_older_turn_makes_no_call():
    k, gen_calls, dispatched = _kernel()
    k._der_turn_id = "turn-2"                       # the next task already started
    _text, ok = k._der_run_node(_item(), "sess", "turn-1", [])
    assert not ok and gen_calls == [] and dispatched == []


def test_the_turn_ends_while_the_node_runs():
    """c04 shape: the model asked for a tool, then the turn ended - the tool
    does not run and no further model call is made."""
    def _end_turn(k, n):
        if n == 1:
            k._der_turn_active = False
    k, gen_calls, dispatched = _kernel(_end_turn)
    _text, ok = k._der_run_node(_item(), "sess", "turn-1", [])
    assert not ok
    assert dispatched == []
    assert len(gen_calls) == 1
