"""Node-ripple audit (2026-10-01): one source for "what did this step do".

Since 2026-09-29 a DER step runs a node loop with many tool calls and its
QueueItem has no tool/params. Seven readers still took item.tool: episodes
stored tool "none", skill capture could never fire, footprints were empty,
memory_events typed every node step "none:" (a coding node's test run never
counted as a test command), the failure context said "TOOL: None".
"""

from pathlib import Path

from backend.agent import agent_kernel as ak
from backend.agent.der_loop import QueueItem

_SRC = Path("backend/agent/agent_kernel.py").read_text(encoding="utf-8", errors="replace")


def _node(calls):
    it = QueueItem(step_id="s1", step_number=1, description="fix and test")
    it.node_call_log = calls
    return it


def test_a_node_step_reports_the_calls_it_made():
    calls = [
        {"tool": "read_file", "target": "m.py", "ok": True, "args": {"path": "m.py"}},
        {"tool": "edit_file", "target": "m.py", "ok": True, "args": {"path": "m.py"}},
        {"tool": "run_command", "target": "pytest -q", "ok": True, "args": {"command": "pytest -q"}},
    ]
    it = _node(calls)
    assert [c["tool"] for c in ak._step_calls(it)] == ["read_file", "edit_file", "run_command"]
    # the decisive call is the last one: memory_events sees a test command
    assert ak._step_decisive_call(it)["args"] == {"command": "pytest -q"}
    assert ak._step_tool(it) == "run_command"


def test_the_decisive_call_of_a_failed_node_is_its_failed_call():
    it = _node([
        {"tool": "edit_file", "target": "m.py", "ok": False, "args": {"path": "m.py"}},
        {"tool": "read_file", "target": "m.py", "ok": True, "args": {"path": "m.py"}},
    ])
    assert ak._step_tool(it) == "edit_file"


def test_a_direct_step_is_its_one_tool_and_an_unrun_node_has_none():
    direct = QueueItem(step_id="d", step_number=1, description="search",
                       tool="crawler_query", params={"query": "x", "max_pages": 3})
    assert ak._step_calls(direct) == [
        {"tool": "crawler_query", "target": "x", "ok": True, "args": {"query": "x"}}]
    pending = QueueItem(step_id="p", step_number=2, description="later")
    assert ak._step_calls(pending) == [] and ak._step_tool(pending) is None


def test_no_reader_writes_none_for_a_node_steps_tool():
    assert '"tool": ci.tool or "none"' not in _SRC
    assert 'f"TOOL: {failed_item.tool}' not in _SRC
    assert '"toolName": it.tool' not in _SRC
    assert 'item.node_call_log = ' in _SRC, "_der_run_node no longer records the calls"
