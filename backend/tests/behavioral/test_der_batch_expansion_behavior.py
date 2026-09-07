"""BT-12 (vision-goal-directed-search REQ-24, T37): DER-native batch expansion.

AC24.1: a parallel_safe+independent BatchToolCall node expands into releasable
  items through the existing all_ready_items path (no new scheduler).
AC24.2: brain.vis batches run under the DER-owned cap (4); crawl batches are
  governed downstream (orchestrator caps), VLM via the lease — DER adds nothing.
AC24.3: settled items fold via collect_batch_outcome into ONE BatchOutcome.
AC24.4: a NOT-parallel_safe batch runs sequentially in declared order.
Edge: empty items complete immediately with an empty outcome; one item's death
  marks that item only (DAG abort rules unchanged).

Producer-side only (fake executor, no network, no browser, no model).
"""
from __future__ import annotations

import asyncio

from backend.agent.der_loop import (
    BRAIN_VIS_MAX_CONCURRENCY,
    DirectorQueue,
    QueueItem,
    expand_batch_node,
    reset_brain_vis_semaphore_for_testing,
    run_batch_children,
)
from backend.core_models import BatchToolCall


def _tracker():
    return {"inflight": 0, "max": 0, "order": []}


def _make_executor(record, fail_keys=frozenset()):
    async def _exec(child):
        record["inflight"] += 1
        record["max"] = max(record["max"], record["inflight"])
        try:
            await asyncio.sleep(0)
            record["order"].append(child.step_id)
            if child.step_id in fail_keys:
                raise RuntimeError("boom")
            return (child.step_id, True, {"n": child.params.get("_batch_index")}, None)
        finally:
            record["inflight"] -= 1

    return _exec


def _parent(tool, n, *, parallel_safe=True, independent=True, step_id="b1"):
    return QueueItem(
        step_id=step_id,
        step_number=1,
        description="batch parent",
        tool=tool,
        batch=BatchToolCall(
            batch_id=f"{step_id}-batch",
            tool=tool,
            items=[{"q": f"q{i}"} for i in range(n)],
            parallel_safe=parallel_safe,
            independent=independent,
        ),
    )


def test_parallel_batch_releases_together_and_folds_one_outcome():
    """AC24.1+AC24.3: 4-item crawl batch releases all 4 via all_ready_items and
    folds a single 4-result BatchOutcome (DER adds no cap — orchestrator governs)."""
    q = DirectorQueue(objective="t", items=[(_parent_batch := _parent("crawler.dispatch", 4))])
    assert q.expand_batch_nodes() == 4
    assert q.expand_batch_nodes() == 0  # idempotent: parent completed
    ready = q.all_ready_items()
    assert len(ready) >= 2, f"expected concurrent release, got {len(ready)}"
    assert all(c.tool == "crawler.dispatch" for c in ready)
    assert all(c.parallel_safe and c.independent for c in ready)

    from backend.agent.der_loop import run_batch_children as _run

    record = _tracker()
    outcome = asyncio.run(_run(_parent_batch.batch, ready, _make_executor(record)))
    assert record["max"] >= 2, f"expected overlap, saw max {record['max']}"
    assert getattr(outcome, "batch_id") == "b1-batch"
    assert len(list(getattr(outcome, "results"))) == 4
    assert outcome.ok_count == 4


def test_brain_vis_batch_capped_at_four():
    """AC24.2: 6 brain.vis items overlap but never exceed the DER-owned cap."""
    reset_brain_vis_semaphore_for_testing()
    assert BRAIN_VIS_MAX_CONCURRENCY == 4
    q = DirectorQueue(objective="t", items=[(_bv_parent := _parent("brain.vis", 6, step_id="bv"))])
    assert q.expand_batch_nodes() == 6
    ready = q.all_ready_items()
    assert len(ready) == 6
    record = _tracker()
    outcome = asyncio.run(run_batch_children(_bv_parent.batch, ready, _make_executor(record)))
    assert 2 <= record["max"] <= 4, f"cap violated or no overlap: {record['max']}"
    assert len(list(getattr(outcome, "results"))) == 6
    reset_brain_vis_semaphore_for_testing()


def test_sequential_batch_runs_in_declared_order():
    """AC24.4: NOT-parallel_safe batch chains children — one ready at a time,
    in declared order; children are skipped by the concurrent filter."""
    q = DirectorQueue(objective="t", items=[(_seq_parent := _parent("crawler.dispatch", 3, parallel_safe=False, step_id="s"))])
    assert q.expand_batch_nodes() == 3
    seen = []
    for _ in range(3):
        ready = q.all_ready_items()
        assert len(ready) == 1, f"expected serial release, got {[c.step_id for c in ready]}"
        assert ready[0].parallel_safe is False
        seen.append(ready[0].step_id)
        q.mark_complete(ready[0].step_id)
    assert seen == ["s#0", "s#1", "s#2"]
    record = _tracker()
    children = [i for i in q.items if i.step_id.startswith("s#")]
    outcome = asyncio.run(run_batch_children(_seq_parent.batch, children, _make_executor(record)))
    assert [r.item_key for r in outcome.usable()] == seen


def test_empty_batch_completes_immediately_with_empty_outcome():
    """Edge: empty items materialize nothing; the parent completes; the fold is empty."""
    parent = _parent("crawler.dispatch", 0, step_id="e")
    assert expand_batch_node(parent) == []
    q = DirectorQueue(objective="t", items=[parent])
    assert q.expand_batch_nodes() == 0
    assert "e" in q.completed_ids
    outcome = asyncio.run(run_batch_children(parent.batch, [], _make_executor(_tracker())))
    assert list(getattr(outcome, "results")) == []
    assert outcome.ok_count == 0


def test_item_failure_marks_only_that_item():
    """Edge: an executor raise becomes that item's failure; the node completes."""
    q = DirectorQueue(objective="t", items=[(_fail_parent := _parent("crawler.dispatch", 3, step_id="f"))])
    q.expand_batch_nodes()
    ready = q.all_ready_items()
    record = _tracker()
    outcome = asyncio.run(
        run_batch_children(_fail_parent.batch, ready, _make_executor(record, fail_keys={"f#1"}))
    )
    assert outcome.ok_count == 2
    by_key = {r.item_key: r for r in getattr(outcome, "results")}
    assert by_key["f#1"].ok is False and "RuntimeError" in (by_key["f#1"].error or "")
    assert [r.item_key for r in outcome.usable()] == ["f#0", "f#2"]


def test_batch_behind_a_dep_waits():
    """A batch node with unsatisfied deps does not expand until unblocked."""
    parent = _parent("crawler.dispatch", 2, step_id="w")
    parent.depends_on = ["gate"]
    q = DirectorQueue(objective="t", items=[parent])
    assert q.expand_batch_nodes() == 0
    assert "w" not in q.completed_ids
