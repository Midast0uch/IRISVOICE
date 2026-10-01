"""Contract: the CONTROL events of the taxonomy (docs/Design/EVENT_TAXONOMY.md
section 4) are emitted by the REAL chokepoints, on lane("memory_events"):

  PLAN_MADE  - _execute_plan_der accepts a plan
  REPLAN+SPLIT / SPLIT - AgentKernel._split_step (verify_failed / physics)
  PIVOT      - AgentKernel._der_enqueue_recovery (trigger = NodeOutcome Reason)
  HALTED     - _der_topology_halt (TOPO_VIOLATION)
  BUDGET_HIT - _der_budget_exit types the exit the loop condition took

Each test drives the chokepoint and asserts the memory_events ROW (family,
label, evidence, episode_id). The last test: a blocked lane never delays it.
"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from backend.agent import agent_kernel
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.tests.contract._events_fixture import BlockedLane, memory_interface, rows, store  # noqa: F401

EPISODE = "sess-ev:turn-ev"


def _kernel(store, session="sess-ev"):  # noqa: F811
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = None
    k.session_id = session
    k._der_session = session
    k._event_episode_id = EPISODE
    k._memory_interface = memory_interface(store)
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_live_cad_state = lambda s: {"u": 0.2, "xi": 0.5, "x": 0.1, "y": 0.3}
    return k


def _step(step_id="st1"):
    return QueueItem(
        step_id=step_id, step_number=1, description="build the widget", tool="code",
        params={}, critical=True, objective_anchor="deliver the feature",
        expected_output="widget renders with data",
    )


def test_halted_row_on_a_landed_topology_violation(store):  # noqa: F811
    fold = SimpleNamespace(ready=threading.Event(), done=threading.Event(),
                           lock=threading.Lock(), rec=3, step=7)
    fold.ready.set()
    owner = SimpleNamespace(_der_physics_pending={"sess-ev": fold}, session_id="sess-ev",
                            _event_episode_id=EPISODE, _memory_interface=memory_interface(store))
    try:
        agent_kernel._der_topology_halt(owner, "sess-ev")
    except Exception:  # noqa: BLE001 - TopologyViolationException, covered by test_topology_halt
        pass
    (row,) = rows(store, "HALTED")
    assert (row["family"], row["evidence"], row["episode_id"], row["thread_id"]) == (
        "control", "verifier", EPISODE, "sess-ev")
    assert row["valence"] == "sets_back"
    assert json.loads(row["payload"])["cause"] == "TOPO_VIOLATION"


def test_verify_failed_split_is_replan_then_split(store):  # noqa: F811
    k = _kernel(store)
    children = k._split_step(
        _step(), "verify_failed", {"u": 0.2}, 10,
        step_result="the result covers the feature but misses the empty-state branch",
        verified_fraction=0.4,
    )
    assert children
    evs = rows(store)
    assert [r["label"] for r in evs] == ["REPLAN", "SPLIT"]
    for r in evs:
        assert (r["family"], r["evidence"], r["episode_id"], r["step_index"]) == (
            "control", "verifier", EPISODE, "st1")
    payload = json.loads(evs[1]["payload"])
    assert payload["trigger"] == "verify_failed" and payload["width"] == len(children)


def test_physics_split_is_only_a_split(store):  # noqa: F811
    k = _kernel(store)
    assert k._split_step(_step(), "unresolved_u", {"u": 0.2}, 10)
    assert [r["label"] for r in rows(store)] == ["SPLIT"]


def test_a_refused_split_emits_nothing(store):  # noqa: F811
    k = _kernel(store)
    assert k._split_step(_step(), "verify_failed", {"u": 0.2}, 0) == []  # no work units left
    assert rows(store) == []


def test_recovery_route_is_a_pivot_typed_by_the_node_reason(store):  # noqa: F811
    from backend.tests.contract.test_wave5_ledger_contract import (
        _DEAD_RES, _recovery_item, _recovery_stub,
    )

    stub = _recovery_stub(visited={"https://dead.example/old-page"})
    stub._card_envelope = lambda _t: {}
    stub.session_id = "sess-ev"
    stub._event_episode_id = EPISODE
    stub._memory_interface = memory_interface(store)
    added = []
    queue = SimpleNamespace(add_item=added.append)
    AgentKernel._der_enqueue_recovery(
        stub, _recovery_item(), SimpleNamespace(name="fetch.vision"), _DEAD_RES, "sess-ev",
        "turn-ev", SimpleNamespace(reason=SimpleNamespace(value="empty")), "crawler_query", queue,
    )
    assert len(added) == 1
    (row,) = rows(store, "PIVOT")
    assert (row["family"], row["evidence"], row["episode_id"], row["trigger"]) == (
        "control", "verifier", EPISODE, "empty")
    assert json.loads(row["payload"])["to_tool"] == "fetch.vision"


def test_plan_made_row_when_the_plan_is_accepted(store, monkeypatch):  # noqa: F811
    """Drives the real _execute_plan_der up to the queue build and cuts the run at the
    next unguarded statement (the mode decision), so no step or model call runs."""

    class _Stop(Exception):
        pass

    def _stop(*_a, **_k):
        raise _Stop()

    monkeypatch.setattr(DirectorQueue, "_decide_mode", staticmethod(_stop))
    k = _kernel(store)
    k._router = SimpleNamespace(health_check_provider=lambda _r: {"ok": True})
    k.resolve_turn_context_window = lambda: 8192
    k.clear_turn_trust_flag = lambda: None
    k._der_topic_domain = lambda _t: "general"
    k._der_execution_domain = lambda _v: "der"
    plan = SimpleNamespace(
        original_task="make a widget", strategy="do_it_myself",
        steps=[SimpleNamespace(step_id="s1", step_number=1, description="read it",
                               tool="read_file", params={}, critical=True, depends_on=[],
                               expected_output="x", criticality="supporting")],
    )
    try:
        k._execute_plan_der(plan, session_id="sess-ev", turn_id="turn-ev")
    except _Stop:
        pass
    (row,) = rows(store, "PLAN_MADE")
    assert (row["family"], row["evidence"], row["episode_id"]) == ("control", "none", EPISODE)
    assert (row["exec_domain"], row["topic_domain"]) == ("der", "general")
    assert json.loads(row["payload"])["steps"] == 1


class _Q:
    def __init__(self, complete=False, cycles=False):
        self._c, self._y = complete, cycles

    def is_complete(self):
        return self._c

    def hit_cycle_limit(self):
        return self._y


def test_budget_exit_is_typed_by_the_condition_that_stopped_the_loop():
    exit_ = agent_kernel._der_budget_exit
    assert exit_(100, 100, 1.0, 600.0, _Q()) == "tokens"
    assert exit_(10, 100, 601.0, 600.0, _Q()) == "turn_time"
    assert exit_(10, 100, 1.0, 600.0, _Q(cycles=True)) == "steps"
    assert exit_(10, 100, 1.0, 600.0, _Q()) is None
    # A plan that ran to the end is not a budget hit, even when the tokens ran out on its last step.
    assert exit_(100, 100, 700.0, 600.0, _Q(complete=True)) is None


def test_blocked_memory_events_lane_does_not_delay_the_control_chokepoint(store):  # noqa: F811
    k = _kernel(store)
    with BlockedLane():
        t0 = time.monotonic()
        children = k._split_step(_step(), "verify_failed", {"u": 0.2}, 10,
                                 step_result="misses the empty-state branch", verified_fraction=0.4)
        assert children
        assert time.monotonic() - t0 < 1.0
    assert [r["label"] for r in rows(store)] == ["REPLAN", "SPLIT"]
