"""Regression (execution audit B3, 2026-09-29): the conversation-wide repeat
guard must not block local tools.

Re-running the same test command after an edit, or re-reading a file after
writing it, is the coding loop itself. The old guard blocked any identical
tool+params for the whole conversation and rerouted to get_rendered_documents.
Web fetches keep the guard (CT-10). The local-tool tests fail on the old code.
"""

from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel
from backend.agent.tool_envelope import params_digest


def _kernel_that_already_ran(tool, params):
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "c1"
    k._der_seen_dispatches = {"c1": {params_digest(tool, params): "s1"}}
    k._der_envelope_registry = {}
    return k


def _item(tool, params):
    return SimpleNamespace(step_id="s2", tool=tool, params=dict(params))


def test_rerunning_a_test_command_is_allowed():
    params = {"command": "python -m pytest -q"}
    k = _kernel_that_already_ran("run_command", params)
    assert k._der_pre_dispatch_guard(_item("run_command", params)) is None


def test_rereading_a_file_is_allowed():
    params = {"path": "mathutils.py"}
    k = _kernel_that_already_ran("read_file", params)
    assert k._der_pre_dispatch_guard(_item("read_file", params)) is None


def test_web_repeat_is_still_blocked():
    params = {"query": "streaming stt"}
    k = _kernel_that_already_ran("crawler_query", params)
    verdict = k._der_pre_dispatch_guard(_item("crawler_query", params))
    assert verdict is not None and verdict["reroute_tool"] == "get_rendered_documents"
