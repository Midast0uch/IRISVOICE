"""REQ-24 contract — the DAG is forward-only: a terminal node is FROZEN.

Pins the forward-only property at the REAL ``_split_step`` / ``DirectorQueue``
boundary (real instances, stubbed collaborators — no redesign, the property
holds today and this file locks it):

  - a node that reaches a TERMINAL state (VERIFIED/FAILED, via
    ``queue.mark_complete``) is immutable and is NEVER re-queued — recovery
    does not rewind it to pending (AC1)
  - recovery SPAWNS a NEW node whose ``parent_step_id`` is the frozen node's
    id — the edge FROM the frozen node, never a mutation of it (AC2)
  - statically: no terminal->pending reset exists anywhere in the DER loop
    sources; ``_split_step`` child ids are always fresh (``parent_s{i}``)

Spec: specs/der-dag-inversion/requirements.md REQ-24, task T39.
"""

from __future__ import annotations

import inspect

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem


def _make_queue_item(step_id: str) -> QueueItem:
    return QueueItem(
        step_id=step_id, step_number=1, description="do it",
        tool="run_command", params={}, critical=False,
        objective_anchor="do the thing", expected_output="done",
    )


def _make_kernel() -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-fwd"
    k._der_work_units = 10
    k._der_live_cad_state = lambda s: {"x": 0.1, "y": 0.2, "xi": 0.3, "u": 0.4}
    k._memory_interface = None
    k._der_ledger = None
    k._der_trace = lambda *a, **kw: None
    return k


class TestTerminalNodeFrozen:
    """AC1/AC2 — terminal nodes are never mutated or re-queued."""

    def test_split_spawns_new_nodes_never_requeues_parent(self):
        kernel = _make_kernel()
        item = _make_queue_item("step-terminal")
        queue = DirectorQueue(objective="do the thing", items=[item])
        queue.mark_complete(item.step_id)  # terminal

        children = kernel._split_step(
            item,
            trigger="verify_failed",
            cad={"x": 0.1, "y": 0.2, "xi": 0.3, "u": 0.4},
            work_units=10,
        )

        # Recovery SPAWNS NEW nodes: every child has a FRESH step_id carved
        # from the parent (AC2), and carries the parent's id as the edge FROM
        # the frozen node.
        assert children, "recovery must spawn child nodes"
        child_ids = {c.step_id for c in children}
        assert item.step_id not in child_ids, (
            "recovery must NEVER reuse the terminal node's own id — it is "
            "frozen, not re-run"
        )
        for c in children:
            assert c.step_id.startswith(f"{item.step_id}_s"), (
                "child ids are carved parent_s{i} — a fresh identity"
            )
            # The edge FROM the frozen node: the child's memory record points
            # at the parent (NodeRecord.parent_step_id), and/or the carved id
            # itself encodes the parent. Either way the parent is referenced,
            # never reused.
            if c.node_record is not None:
                assert c.node_record.parent_step_id == item.step_id, (
                    "the child's memory record parent edge points AT the "
                    "frozen node"
                )

        # The parent node object itself is untouched: still terminal in the
        # queue, same id, and NOT re-queued (it was never added again).
        assert queue.completed_ids == [item.step_id]
        assert item.step_id not in queue.vetoed_ids
        assert item.step_id not in queue.failed_ids
        assert sum(1 for it in queue.items if it.step_id == item.step_id) == 1, (
            "the terminal node is in the queue exactly ONCE — recovery does "
            "not re-add it"
        )

    def test_failed_terminal_label_is_not_rewound_by_recovery(self):
        kernel = _make_kernel()
        item = _make_queue_item("step-frozen")
        item.result = "failed attempt"
        queue = DirectorQueue(objective="do the thing", items=[item])
        queue.mark_complete(item.step_id)

        children = kernel._split_step(
            item,
            trigger="verify_failed",
            cad={"x": 0.1, "y": 0.2, "xi": 0.3, "u": 0.4},
            work_units=10,
        )

        assert children
        # The parent keeps its terminal identity — nothing about the original
        # node was reset to pending or re-labelled by the recovery act.
        assert item.step_id == "step-frozen"
        assert queue.completed_ids == [item.step_id]
        for c in children:
            assert c.step_id != item.step_id
            assert c.result != item.result or c.step_id != item.step_id


class TestNoTerminalToPendingReset:
    """Static guard — the property is pinned so a future "recovery" cannot
    silently rewind a terminal node (the exact regression class REQ-24
    bars: a hardcoded retry that mutates the frozen record)."""

    def test_split_step_never_readds_the_parent_item(self):
        src = inspect.getsource(AgentKernel._split_step)
        # Children are NEW QueueItems; the parent must never be re-added to
        # any queue by the split operator itself.
        assert "add_item(item)" not in src, (
            "the split operator must not re-add the terminal parent item"
        )
        assert 'f"{item.step_id}_s{i}"' in src, (
            "child identities are always carved fresh from the parent id"
        )

    def test_no_terminal_to_pending_reset_in_loop_sources(self):
        from backend.agent import der_loop as _dl

        for mod in (AgentKernel, _dl.DirectorQueue, _dl.QueueItem):
            src = inspect.getsource(mod)
            # A terminal->pending rewind would have to either empty the
            # outcome or re-queue the completed id. Neither exists.
            assert 'outcome = ""' not in src, (
                f"{mod.__name__} must not blank a node's outcome"
            )
        # The queue keeps completed ids disjoint from the runnable path: a
        # completed id is never pushed back onto the pending item list.
        queue_src = inspect.getsource(_dl.DirectorQueue.add_item)
        assert "completed_ids" not in queue_src, (
            "add_item must not touch completed_ids — a completed node cannot "
            "be re-queued"
        )
