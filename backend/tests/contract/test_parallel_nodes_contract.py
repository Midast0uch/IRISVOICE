"""Parallel DAG nodes (owner 2026-10-04) - one scheduler for every node.

The plan IS a DAG (QueueItem.depends_on). Until 2026-10-04 the DER loop ran it
one node at a time (next_ready -> run -> join), and the only concurrent path
ran fixed tools, never a node. Now the loop starts every ready node on its own
thread (the "execution.der_nodes" phase domain decides WHEN), settles each on
the loop thread when it finishes, and folds split children back into their
parent (the first VERIFIED child wins the race).

Contract, driven through the REAL _execute_plan_der loop with boundary stubs
(the harness shape of test_der_success_synthesizes):
  1. independent nodes overlap in wall time; a node that needs both starts
     only after both ended;
  2. a dependency chain never overlaps;
  3. two nodes that drive the browser take turns (one page per conversation)
     while a node that does not, overlaps them;
  4. split race (queue level + the real settle helper): the first VERIFIED
     child completes the parent and stops its siblings, the parent's
     dependents run; every child failed -> the parent fails, dependents abort;
  5. a stop reaches nodes still in flight (they are told to stop and recorded
     as not finished) instead of waiting for them.
On the old serial loop 1 and 3's overlap assertions fail.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.agent import agent_kernel
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem

# A real node runs seconds; the node domain may delay a start by up to 0.5 s
# (its position on the dial), so a 1.5 s node still overlaps a sibling.
_WORK_S = 1.5


class _StubLiveCtx:
    def __init__(self, *a, **k):
        self.package = None

    def refresh(self, item, completed_items):
        pass


def _step(sid, n, deps, tool=None):
    return SimpleNamespace(
        step_id=sid, step_number=n, description=f"do {sid}", tool=tool, params={},
        critical=True, depends_on=list(deps), expected_output=f"{sid} done",
        criticality="supporting",
    )


def _kernel(intervals, work=None, on_start=None):
    k = MagicMock()
    k.session_id = "sess"
    k.conversation_id = "conv-par"
    k._cancel_requested = SimpleNamespace(is_set=lambda: False)
    k._memory_interface = None
    k._der_stop_requested = False
    k.resolve_context_window = lambda: 30000
    k.resolve_turn_context_window = lambda: 128000  # a real budget for 3 steps
    k._reviewer = MagicMock()
    k._reviewer.review.return_value = (SimpleNamespace(), None)
    k._verified_fraction = lambda *a, **kw: 0.9
    k._der_check_steering = lambda *a, **kw: None
    k._synthesize_response = lambda task, results: (
        "SYNTHESIZED: the parallel nodes all finished and the answer is complete.")
    k._der_synthesize_success_outcome = (
        agent_kernel.AgentKernel._der_synthesize_success_outcome.__get__(k, agent_kernel.AgentKernel))
    k._der_node_record_evidence = agent_kernel.AgentKernel._der_node_record_evidence
    lock = threading.Lock()

    def _run_step(item, ctx, session, turn, plan, queue=None):
        t0 = time.perf_counter()
        if on_start:
            on_start(item, k)
        time.sleep((work or {}).get(item.step_id, _WORK_S))
        with lock:
            intervals[item.step_id] = (t0, time.perf_counter())
        return f"{item.step_id} ok", True

    k._der_run_step_execution = _run_step

    def _fake_finalize(item, step_result, step_success, step_outputs, completed_items,
                       _tokens_used, _token_budget, _session, _turn_id, _phase, is_mature,
                       _live_ctx, plan, context_package, queue, verdict, from_voice=False):
        step_outputs.append(step_result)
        completed_items.append(item)
        item.result = step_result
        queue.mark_complete(item.step_id)
        return _tokens_used + 10

    k._der_finalize_step = _fake_finalize
    k._der_graft_missing_artifacts = lambda *a, **kw: None
    k._der_handle_step_failure = MagicMock()
    return k


def _run(kernel, steps):
    plan = SimpleNamespace(original_task="compare A and B", plan_title="t",
                           strategy="standard", steps=steps)
    with patch("backend.agent.event_bus.get_event_bus", return_value=MagicMock()), \
            patch("backend.ws_manager.get_websocket_manager", return_value=None), \
            patch("backend.memory.live_context.LiveContextPackage", _StubLiveCtx),             patch("backend.agent.tool_registry.validate_tool_call",
                  # validation is not under test, and it reads the GLOBAL tool
                  # registry (web toggle) that other tests change
                  return_value=(True, None)):
        return agent_kernel.AgentKernel._execute_plan_der.__get__(
            kernel, agent_kernel.AgentKernel)(
            plan=plan, context_package=None, session_id="sess", turn_id="t1")


def _overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def test_independent_nodes_overlap_and_the_join_waits_for_both():
    iv: dict = {}
    _run(_kernel(iv), [_step("s1", 1, []), _step("s2", 2, []), _step("s3", 3, ["s1", "s2"])])
    assert set(iv) == {"s1", "s2", "s3"}, iv
    assert _overlap(iv["s1"], iv["s2"]), f"independent nodes ran one after the other: {iv}"
    assert iv["s3"][0] >= max(iv["s1"][1], iv["s2"][1]), "the join started before its inputs"


def test_a_dependency_chain_never_overlaps():
    iv: dict = {}
    _run(_kernel(iv, work={"s1": 0.3, "s2": 0.3, "s3": 0.3}),
         [_step("s1", 1, []), _step("s2", 2, ["s1"]), _step("s3", 3, ["s2"])])
    assert set(iv) == {"s1", "s2", "s3"}
    assert iv["s2"][0] >= iv["s1"][1] and iv["s3"][0] >= iv["s2"][1], iv


def test_browser_nodes_take_turns_while_other_nodes_overlap():
    iv: dict = {}
    _run(_kernel(iv), [_step("b1", 1, [], tool="browser_observe"),
                       _step("b2", 2, [], tool="browser_observe"),
                       _step("w1", 3, [], tool="search")])
    assert set(iv) == {"b1", "b2", "w1"}, iv
    assert not _overlap(iv["b1"], iv["b2"]), f"two nodes drove one browser page at once: {iv}"
    assert _overlap(iv["w1"], iv["b1"]) or _overlap(iv["w1"], iv["b2"]), iv


def _qi(sid, deps=()):
    return QueueItem(step_id=sid, step_number=1, description=sid, tool=None, params={},
                     critical=True, depends_on=list(deps), objective_anchor="o")


def _split_queue():
    items = [_qi("P"), _qi("D", ["P"]), _qi("c0"), _qi("c1"), _qi("c2")]
    for c in items[2:]:
        c.is_subloop = True
    q = DirectorQueue(objective="o", items=items)
    q.mode = ExecutionMode.AGENTIC
    q.mark_failed("P")
    aborted = q.abort_descendants("P")
    assert "D" in aborted
    q.hold_split_parent("P", ["c0", "c1", "c2"], aborted)
    return q, {it.step_id: it for it in items}


def test_split_race_first_verified_child_completes_the_parent():
    q, it = _split_queue()
    ready = {i.step_id for i in q.all_ready_items("sess")}
    assert ready == {"c0", "c1", "c2"}, "the parent waits; its dependent waits on it"
    it["c1"].node_record = SimpleNamespace(outcome="VERIFIED")
    it["c1"].result = "blocker resolved"
    q.mark_complete("c1")
    agent_kernel._der_settle_split(None, it["c1"], q, inflight={"c0": {}})
    assert "P" in q.completed_ids and it["P"].result == "blocker resolved"
    assert it["c0"]._race_lost, "the running sibling is told to stop"
    assert "c2" in q.completed_ids, "the sibling that never started never will"
    # c0 is still running (in flight) until the loop settles it as not needed;
    # the scheduler skips in-flight nodes, so the next node it starts is D.
    assert q.next_ready("sess", exclude={"c0"}).step_id == "D", "the plan continues"


def test_split_race_every_child_failed_fails_the_parent():
    q, it = _split_queue()
    for c in ("c0", "c1", "c2"):
        q.mark_failed(c)
        agent_kernel._der_settle_split(None, it[c], q, inflight={})
    assert "P" in q.failed_ids and "D" in q.failed_ids
    assert not q.split_pending and q.is_complete()


def test_a_stop_reaches_nodes_in_flight():
    iv: dict = {}

    def _stop_soon(item, k):
        if item.step_id == "s1":
            threading.Timer(0.3, lambda: setattr(k, "_der_stop_requested", True)).start()

    k = _kernel(iv, work={"s1": 6.0, "s2": 6.0}, on_start=_stop_soon)
    seen: dict = {}
    orig = DirectorQueue.mark_failed

    def _spy(self, sid):
        seen[sid] = True
        return orig(self, sid)

    t0 = time.perf_counter()
    with patch.object(DirectorQueue, "mark_failed", _spy):
        _run(k, [_step("s1", 1, []), _step("s2", 2, [])])
    took = time.perf_counter() - t0
    # The loop polls every 0.5 s; 6 s nodes would hold an unstoppable loop 6 s.
    assert took < 4.0, f"the stop waited for the nodes ({took:.1f} s)"
    assert seen.get("s1") or seen.get("s2"), "nodes in flight were not settled as not finished"
