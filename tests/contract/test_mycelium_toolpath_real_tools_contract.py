"""Contract: the toolpath space learns the tools a step ACTUALLY called.

Measured on the live store (2026-10-24): 73 of 154 toolpath nodes were labelled
"tool_none" and almost every toolpath claim traversed "tool_none > tool_none > ...",
while the episodes of the same turns recorded real tools (list_directory > read_file).
Cause: the settled-step path called ``mycelium_ingest_tool_call(tool_name=item.tool or
"none")``. ``item.tool`` is the PLANNED tool; a node step has none, because the tool
model picks its tools while the step runs. The actual calls live in
``_step_calls(item)`` (the node's ``node_call_log``) - the same source the episode's
tool list is built from.

Driven through the REAL ``AgentKernel._der_finalize_step`` (harness pattern of
backend/tests/behavioral/test_der_step_edge_scoring.py). The assertion is on the
ingest calls the memory interface RECEIVES.
"""
from __future__ import annotations

import pytest

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem


class _RecordingMemory:
    """The memory-interface surface _der_finalize_step touches; records ingests."""

    def __init__(self) -> None:
        self._mycelium = None
        self.session_id = "kernel-default-session"
        self.ingested: list[dict] = []

    def mycelium_ingest_tool_call(self, **kw):
        self.ingested.append(kw)

    def append_to_session(self, *a, **kw):
        pass

    def store_episode(self, episode) -> str:
        return "ep-1"


class _NoOpRecorder:
    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        pass


class _NoOpBus:
    def emit(self, *a, **kw):
        pass


@pytest.fixture(autouse=True)
def _patch_side_lanes(monkeypatch):
    monkeypatch.setattr(_ct_module, "CaduceanTrajectoryRecorder", _NoOpRecorder)
    monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _NoOpBus())


def _finalize(item: QueueItem, step_success: bool = True) -> _RecordingMemory:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-toolpath"
    k.session_id = "sess-toolpath"
    k._memory_interface = mem = _RecordingMemory()
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu, step_result="": []
    k._verify_step_result = lambda goal, expected, result, tool=None, success=False: "VERIFIED"
    queue = DirectorQueue(objective="look around", items=[item])
    queue.mode = ExecutionMode.QUICK
    k._der_finalize_step(
        item=item, step_result="step output text long enough", step_success=step_success,
        step_outputs=[], completed_items=[], _tokens_used=0, _token_budget=10_000,
        _session="sess-toolpath", _turn_id="t1", _phase=2, is_mature=False,
        _live_ctx=None, plan=type("P", (), {"original_task": "look around"})(),
        context_package=None, queue=queue, verdict=None,
    )
    return mem


def _item(tool: str = "", step_number: int = 3) -> QueueItem:
    return QueueItem(
        step_id="s3", step_number=step_number, description="look around", tool=tool,
        params={}, critical=False, objective_anchor="look around", expected_output="done",
    )


def test_node_step_ingests_the_tools_it_actually_called_in_order():
    item = _item(tool="")  # a node step: nothing planned, the tool model picked its tools
    item.node_call_log = [
        {"tool": "list_directory", "target": "backend", "ok": True, "args": {}},
        {"tool": "read_file", "target": "a.py", "ok": True, "args": {}},
        {"tool": "read_file", "target": "b.py", "ok": False, "args": {}},
    ]
    got = _finalize(item).ingested
    assert [c["tool_name"] for c in got] == ["list_directory", "read_file", "read_file"]
    assert {c["sequence_position"] for c in got} == {3}          # one step number for the whole step
    assert [c["success"] for c in got] == [True, True, False]    # a failed call is recorded as failed


def test_step_that_called_no_tool_still_records_none():
    item = _item(tool="")
    item.node_call_log = []
    got = _finalize(item).ingested
    assert [c["tool_name"] for c in got] == ["none"] and got[0]["sequence_position"] == 3


def test_direct_step_still_records_its_one_planned_tool():
    got = _finalize(_item(tool="read_file")).ingested
    assert [c["tool_name"] for c in got] == ["read_file"]
