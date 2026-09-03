"""REQ-4 AC4 (T16b) contract — split children RESOLVE, they do not retry.

Pins the resolve-not-retry invariant at the REAL ``_split_step`` boundary
(real operator, stubbed collaborators) and the REAL ``_der_finalize_step``
fold-back (real instance, stubbed verify):

  - a split child's ``objective_anchor`` names the SPECIFIC blocker it exists
    to resolve — NEVER a restatement of the parent goal (the s2_s0 ->
    s2_s0_s0 cascade was the observed symptom of the anti-pattern)
  - the child's ``node_record`` carries ``blocker`` / ``blocker_named`` and its
    objective_anchor is the blocker text, not the parent's goal
  - a split that CANNOT name its blocker is recorded as such: blocker_named
    is False and the anchor carries an explicit ``[UNNAMED_BLOCKER]`` marker —
    the split is surfaced as evidence the failure was not understood, never
    hidden behind a fresh node id
  - a physics split (unresolved_u) is NOT a failure — its children name the
    oscillating state as the blocker (decomposition, not retry), and the
    anchor is still never the parent goal verbatim
  - FOLD-BACK (REQ-3 AC1): when a sub-loop child finalizes through the REAL
    ``_der_finalize_step``, its verified outcome is appended to the PARENT's
    ``node_record.folded_back`` — the child folds back as a compressed
    observation that CHANGES the parent's state (bounded by
    DER_FOLD_BACK_MAX), so the parent's next decision reads what the children
    resolved (the step-context builder surfaces FOLDED-BACK as first-class
    input)

Spec: specs/long-horizon-der-execution/requirements.md REQ-4 AC4, REQ-3 AC1.
"""
import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_constants import DER_FOLD_BACK_MAX
from backend.agent.der_loop import DirectorQueue, NodeRecord, QueueItem


class _CapturingRecorder:
    """Tolerant stub of the trajectory recorder: every method the finalize
    path calls (get_latest_coordinate, record, ...) is a no-op, while
    record_commit still captures — the stub must never raise or the REAL
    fold-back code below it is skipped by the broad swallowing try."""

    calls = []

    def __init__(self, *a, **kw):
        pass

    def __getattr__(self, name):
        def _noop(*a, **kw):
            return None

        return _noop

    def record_commit(self, **kwargs):
        _CapturingRecorder.calls.append(kwargs)


def _make_kernel(conversation_id: str = "conv-t16b") -> AgentKernel:
    """Real AgentKernel instance (no __init__), real _split_step/_finalize."""
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k._memory_interface = None
    k._trailing_director = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._der_trace = lambda *a, **kw: None
    k._der_ledger = None
    return k


def _make_parent(
    step_id="p1",
    description="research the topic",
    objective="research the topic deeply",
    expected="evidence",
    critical=True,
) -> QueueItem:
    return QueueItem(
        step_id=step_id, step_number=1, description=description,
        tool="run_command", params={}, critical=critical,
        objective_anchor=objective, expected_output=expected,
        # REQ-3 T8: every node carries its memory record — the parent in the
        # queue always carries one by the time children fold back (as in the
        # real flow, where the parent is stamped during its own finalize).
        node_record=NodeRecord(
            step_id=step_id, parent_step_id="", node_type="terminal",
            objective_anchor=objective, expected_output=expected,
        ),
    )


def _run_finalize(kernel, item, step_result, step_success, queue, verified):
    kernel._verify_step_result = (
        lambda goal, expected, result, tool=None, success=False: verified
    )
    return kernel._der_finalize_step(
        item=item,
        step_result=step_result,
        step_success=step_success,
        step_outputs=[],
        completed_items=[],
        _tokens_used=0,
        _token_budget=10_000,
        _session="sess-t16b",
        _turn_id="t1",
        _phase=2,
        is_mature=False,
        _live_ctx=None,
        plan=SimpleNamespace(original_task="do the thing"),
        context_package=None,
        queue=queue,
        verdict=None,
    )


@pytest.fixture(autouse=True)
def _patches(monkeypatch):
    _CapturingRecorder.calls = []
    monkeypatch.setattr(
        "backend.agent.caducean_trajectory.get_trajectory_recorder",
        lambda mi: _CapturingRecorder(),
    )
    from backend.agent.event_bus import get_event_bus

    _bus = get_event_bus()

    @patch.object(_bus, "emit", lambda *a, **kw: None)
    def _go():
        yield

    list(_go())


# ── AC4 core: the child's objective_anchor names the SPECIFIC blocker ───────
def test_failed_split_child_names_specific_blocker_not_parent_goal():
    k = _make_kernel()
    item = _make_parent(
        objective="research the topic deeply", expected="evidence of X"
    )
    cad = {"x": 0.0, "y": 0.0, "xi": 0.0, "u": 0.1}  # unresolved -> wide split
    step_result = "I found the history but no evidence of X"  # verify FAILED

    children = k._split_step(
        item, "verify_failed", cad, work_units=10, step_result=step_result
    )

    assert children, "a verify_failed split must spawn children"
    for c in children:
        assert c.objective_anchor != item.objective_anchor, (
            "AC4: the child's objective_anchor must NOT be a restatement of "
            "the parent goal — 'research the topic deeply' would be a retry "
            "wearing a new node id"
        )
        assert "expected output: evidence of X" in c.objective_anchor, (
            "AC4: the anchor names the SPECIFIC blocker — the acceptance "
            "criterion that was not satisfied"
        )
        assert c.node_record is not None
        assert c.node_record.objective_anchor == c.objective_anchor, (
            "the node record's awareness is the blocker, not the parent goal"
        )
        assert c.node_record.blocker == c.objective_anchor.removeprefix(
            "RESOLVE: "
        ), "blocker field carries the same specific blocker"
        assert c.node_record.blocker_named is True


def test_error_result_names_tool_failure_as_blocker():
    k = _make_kernel()
    item = _make_parent()
    cad = {"u": 0.1, "x": 0.0, "y": 0.0, "xi": 0.0}

    children = k._split_step(
        item, "verify_failed", cad, work_units=10,
        step_result="error: file not found at /tmp/x",
    )

    assert children
    for c in children:
        assert "the tool reported" in c.objective_anchor
        assert "file not found" in c.objective_anchor
        assert item.objective_anchor not in c.objective_anchor


# ── AC4: a split that cannot name its blocker is recorded as such ────────────
def test_unnamed_blocker_recorded_as_such():
    k = _make_kernel()
    # NO expected output and NO result evidence -> nothing specific can be named.
    item = _make_parent(objective="do the thing", expected="")
    cad = {"u": 0.1, "x": 0.0, "y": 0.0, "xi": 0.0}

    children = k._split_step(  # logging only — no crash
        item, "verify_failed", cad, work_units=10, step_result=""
    )

    assert children, "the split still proceeds — it must not silently vanish"
    for c in children:
        assert "[UNNAMED_BLOCKER]" in c.objective_anchor, (
            "AC4: an unnamed blocker is recorded EXPLICITLY — surfaced as "
            "evidence the failure was not understood, never hidden behind a "
            "fresh node id"
        )
        assert c.node_record.blocker_named is False
        assert c.node_record.blocker == ""
        assert c.node_record.objective_anchor == c.objective_anchor


# ── physics split is decomposition, but STILL names what it resolves ─────────
def test_physics_split_names_oscillation_not_parent_goal():
    k = _make_kernel()
    item = _make_parent(objective="calibrate the sensor")
    cad = {"u": 0.3, "x": 0.0, "y": 0.0, "xi": 0.0}  # oscillating -> wide

    children = k._split_step(item, "unresolved_u", cad, work_units=10)

    assert children
    for c in children:
        assert "oscillating state" in c.objective_anchor, (
            "a physics split names the state it resolves (decomposition), not "
            "the parent goal verbatim"
        )
        assert "calibrate the sensor" != c.objective_anchor
        assert c.node_record.blocker_named is True


# ── FOLD-BACK (REQ-3 AC1): child outcome CHANGES the parent's state ──────────
def test_fold_back_appends_child_outcome_to_parent_state():
    k = _make_kernel()
    parent = _make_parent(step_id="p1")
    queue = DirectorQueue(objective="do the thing", items=[parent])

    # A sub-loop child of p1 that VERIFIES through the REAL finalize path.
    child = QueueItem(
        step_id="p1_s0", step_number=1, description="RESOLVE: expected output: evidence (sub 1)",
        tool="run_command", params={}, critical=True,
        objective_anchor="RESOLVE: expected output: evidence",
        expected_output="evidence", is_subloop=True,
        node_record=NodeRecord(
            step_id="p1_s0", parent_step_id="p1", node_type="sub_loop",
            objective_anchor="RESOLVE: expected output: evidence",
            blocker="expected output: evidence", blocker_named=True,
        ),
    )
    queue.add_item(child)

    _run_finalize(k, child, "evidence found", True, queue, "VERIFIED")

    assert parent.node_record is not None, "parent must carry a node record"
    assert parent.node_record.folded_back, (
        "REQ-3 AC1: the child folds back as a compressed observation that "
        "CHANGES the parent's state"
    )
    assert any("p1_s0" in fb and "VERIFIED" in fb for fb in parent.node_record.folded_back), (
        "the folded-back observation names the child and its outcome"
    )


def test_fold_back_is_bounded_by_der_fold_back_max():
    k = _make_kernel()
    parent = _make_parent(step_id="p1")
    queue = DirectorQueue(objective="do the thing", items=[parent])

    for i in range(DER_FOLD_BACK_MAX + 2):
        child = QueueItem(
            step_id=f"p1_s{i}", step_number=1, description=f"RESOLVE: {i}",
            tool="run_command", params={}, critical=True,
            objective_anchor=f"RESOLVE: {i}", expected_output="evidence",
            is_subloop=True,
            node_record=NodeRecord(
                step_id=f"p1_s{i}", parent_step_id="p1", node_type="sub_loop",
                objective_anchor=f"RESOLVE: {i}", blocker=f"{i}", blocker_named=True,
            ),
        )
        queue.add_item(child)
        _run_finalize(k, child, f"outcome {i}", True, queue, "VERIFIED")

    assert len(parent.node_record.folded_back) <= DER_FOLD_BACK_MAX, (
        "fold-back is bounded — NodeRecord.folded_back never grows into a log"
    )
    assert parent.node_record.folded_back[-1].startswith(f"[p1_s{DER_FOLD_BACK_MAX + 1}]"), (
        "the most RECENT outcomes are kept (bounded recency)"
    )


def test_step_context_builder_surfaces_folded_back():
    """REQ-3 AC1: FOLDED-BACK is a first-class part of the step input."""
    src = inspect.getsource(AgentKernel._execute_plan_der)
    assert "FOLDED-BACK:" in src, (
        "REQ-3 AC1: the step-context builder must surface the parent's "
        "folded-back observations as first-class step context"
    )
    assert "folded_back" in src, "the builder reads NodeRecord.folded_back"


# ── static: no code path restates the parent goal as a child anchor ──────────
def test_split_source_never_restates_parent_anchor():
    src = inspect.getsource(AgentKernel._split_step)
    assert "objective_anchor=item.objective_anchor" not in src, (
        "the split operator must NEVER copy the parent's objective_anchor onto "
        "a child — that is the retry anti-pattern"
    )
