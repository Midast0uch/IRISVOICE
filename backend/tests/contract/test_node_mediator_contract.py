"""A node step's mediator is the call that decided it, never "none".

HANDOFF 11 B2 / HANDOFF 12 C4: _der_mediator_for read item.tool, which a node
step (tool=None since 2026-09-29) never has, so every node step recorded
mediator "none" and the (region, mediator) edge scoring (REQ-23/REQ-26)
returned before any write - the learning was dead for all node work.
"""
from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel


def _node(calls):
    return SimpleNamespace(tool=None, params={}, node_call_log=calls)


def test_a_node_step_mediator_is_its_decisive_call():
    item = _node([
        {"tool": "search", "target": "a", "ok": True, "args": {"query": "a"}},
        {"tool": "read_url", "target": "u", "ok": True, "args": {"url": "u"}},
    ])
    mediator, source = AgentKernel._der_mediator_for(item)
    assert mediator.startswith("read_url:") and source == "explicit"


def test_a_failed_call_decides_the_node():
    item = _node([
        {"tool": "edit_file", "target": "a.py", "ok": False, "args": {"path": "a.py"}},
        {"tool": "read_file", "target": "a.py", "ok": True, "args": {"path": "a.py"}},
    ])
    assert AgentKernel._der_mediator_for(item)[0].startswith("edit_file:")


def test_other_args_give_another_mediator_and_no_call_gives_none():
    a = AgentKernel._der_mediator_for(_node([{"tool": "search", "ok": True, "args": {"query": "a"}}]))
    b = AgentKernel._der_mediator_for(_node([{"tool": "search", "ok": True, "args": {"query": "b"}}]))
    assert a[0] != b[0]
    assert AgentKernel._der_mediator_for(_node([])) == ("none", "none")


def test_a_direct_step_keeps_its_tool_and_full_params_hash():
    item = SimpleNamespace(tool="search", params={"query": "x", "limit": 3})
    mediator, source = AgentKernel._der_mediator_for(item)
    assert mediator.startswith("search:") and source == "explicit"
    assert AgentKernel._der_mediator_for(SimpleNamespace(tool=None, params={})) == ("none", "none")
