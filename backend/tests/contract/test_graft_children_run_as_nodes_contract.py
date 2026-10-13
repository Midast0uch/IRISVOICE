"""Contract: a DER graft's recovery children run as NODES, and a failed split
settles its parent.

Measured live 2026-10-12: 7 of 7 recovery grafts in logs/iris.log were
BATCH_ROUTED - one tool-less text call answered each child and no child ran a
node. conv-1573 s2 hit its 12-call limit, the text guess stood in for the page,
and when every child of a split failed the parent stayed in split_pending
(neither complete nor failed).

Pinned here, through the REAL seams:
  1. _der_route_subloop_children queues each child as a node with no
     pre-seeded answer and never calls the router.
  2. _der_post_step's failure branch settles the split: the parent fails and
     its dependents abort.
  3. _der_split_blocker names the node's own stop reason, not the expected
     output.
"""

import types
from unittest.mock import patch

from backend.agent import agent_kernel, batch_dispatch
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem


class _RecordingRouter:
    """Router stand-in: answers every call with one tagged guess, records it."""

    def __init__(self) -> None:
        self.calls = []

    def generate(self, *args, **kwargs):
        self.calls.append(args)
        return ('<subloop id="s2_s0">guess</subloop>', "", [])


def _child(n: int) -> QueueItem:
    return QueueItem(
        step_id=f"s2_s{n}",
        step_number=2,
        description="open the Poetry category",
        objective_anchor="obj",
        expected_output="the Poetry page is open",
        is_subloop=True,
        independent=True,
        tool=None,
    )


def test_split_children_are_queued_without_a_preseeded_answer():
    """Measured 2026-10-12: 7 of 7 split children went through the batcher
    (BATCH_ROUTED) and were answered by one tool-less text call, so none ran
    a node. Each child must be queued as a node with no result, and the
    router must never be called for it."""
    k = AgentKernel.__new__(AgentKernel)
    router = _RecordingRouter()
    k._router = router

    children = [_child(0), _child(1), _child(2)]
    queue = DirectorQueue(objective="obj")

    # Spy on the real batch dispatcher: if the children reach it, the real
    # function still runs and calls the router, so the guard sees the call.
    with patch(
        "backend.agent.batch_dispatch.dispatch_batch",
        wraps=batch_dispatch.dispatch_batch,
    ) as spy:
        k._der_route_subloop_children(children, queue, "sess", "turn")

    queued = {it.step_id for it in queue.items}
    assert queued == {"s2_s0", "s2_s1", "s2_s2"}, f"all children must be queued, got {queued}"
    for child in children:
        assert not child.result, (
            f"child {child.step_id} must run as a node, not carry a pre-seeded "
            f"answer (result={child.result!r})"
        )
    assert router.calls == [], "split children must not reach the router"
    spy.assert_not_called()


def test_failed_children_settle_the_parent():
    """Measured 2026-10-12 (conv-1573 s2): every child of the split failed, and
    the parent stayed in split_pending - neither complete nor failed - while
    the dependents it had revived waited on it. The failure path must settle
    the split: the parent fails and its dependents abort."""
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._der_route_step_failure = lambda *a, **kw: None
    k._der_report_run_grade = lambda *a, **kw: None
    # Stand-in for the real handler: it only marks the node failed, so no
    # further split is created and the settle path is what is under test.
    k._der_handle_step_failure = lambda item, queue, *a, **kw: queue.mark_failed(item.step_id)

    parent = QueueItem(
        step_id="s2", step_number=2, description="open the Poetry category",
        expected_output="the Poetry page is open",
    )
    dependent = QueueItem(
        step_id="s3", step_number=3, description="read the first poem",
        depends_on=["s2"], expected_output="the poem text is read",
    )
    queue = DirectorQueue(objective="obj")
    queue.add_item(parent)
    queue.add_item(dependent)
    queue.mark_failed("s2")
    queue.abort_descendants("s2")
    # The failure split s2 into one child and revived its dependent s3.
    queue.hold_split_parent("s2", ["s2_s0"], ["s3"])

    child = QueueItem(
        step_id="s2_s0", step_number=2, description="open the Poetry category",
        expected_output="the Poetry page is open", is_subloop=True,
    )
    queue.add_item(child)
    queue.mark_failed("s2_s0")
    plan = types.SimpleNamespace(
        steps=[parent, dependent], original_task="obj", plan_title="t", strategy="standard",
    )

    agent_kernel._der_post_step(
        k,
        child,
        "I opened the site.\n[node error: step call limit reached (12 calls)]",
        False,
        None,
        "execute",
        queue=queue,
        plan=plan,
        _session="sess",
        _turn_id="turn",
        context_package=None,
        completed_items=[],
        step_outputs=[],
        _tokens_used=0,
        _token_budget=30000,
        is_mature=False,
        _live_ctx=None,
        from_voice=False,
        inflight=set(),
    )

    assert "s2" in queue.failed_ids, "every child failed, so the parent must fail"
    assert "s2" not in queue.split_pending, "the parent must leave split_pending"
    assert "s3" in queue.failed_ids, "the parent's dependent must abort"


def test_node_error_names_the_blocker():
    """Measured 2026-10-12 (conv-1573 s2): the node stopped at its 12-call
    limit, but the split named the blocker by the expected output, so the
    child was told only what the parent had been told. The blocker must name
    the node's own stop reason."""
    k = AgentKernel.__new__(AgentKernel)
    item = QueueItem(
        step_id="s2", step_number=2, description="open the Poetry category",
        expected_output="the Poetry page is open",
    )
    blocker = k._der_split_blocker(
        item,
        "verify_failed",
        "I opened the site.\n\nActions:\n- browser_open x -> ok\n\n"
        "[node error: step call limit reached (12 calls)]",
    )
    assert "step call limit reached (12 calls)" in blocker, blocker
    assert "the Poetry page is open" not in blocker, blocker
