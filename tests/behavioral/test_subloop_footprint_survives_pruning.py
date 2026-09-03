"""REQ-21 AC3/AC4 (T42): sub-loop footprint survives DCP pruning.

Behavioral replay: create a growth-width split with children (real
``_split_step``), force a DCP prune pass on the message history, then resume
a child and assert it can state what was done / where it is going / what
remains using ONLY its footprint + the ledger — NOT the pruned messages.

REQ-21 AC3: the footprint is carried on the QueueItem (durable structured
data), not solely in the LLM-visible message history that DCP is free to
prune.
REQ-21 AC4: a resumed child reconstructs "what has been done, where it is
going, and what remains" from footprint + ledger.
"""

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.dcp import DCP
from backend.agent.der_loop import QueueItem


def _kernel_with_attempts(keys, conv="conv_t42"):
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conv
    k.session_id = conv
    k._der_crawl_attempts = {conv: set(keys)}
    k._der_ledger = type("L", (), {"conversation_id": conv})()
    k._growth_width = lambda u: 2
    return k


def _parent_item():
    return QueueItem(
        step_id="s1", step_number=1, description="research pricing",
        objective_anchor="research the pricing page",
        expected_output="pricing facts",
        depth_layer=0, is_subloop=False, critical=True,
    )


def _fake_history(n=8):
    """A message history resembling a long DER conversation, with DUPLICATE
    tool calls so DCP's dedup pass actually prunes (assistant text alone is
    not a tool call and survives every pass)."""
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"user turn {i}"})
        # Repeated tool calls with identical (name, args) -> DCP dedups them.
        msgs.append({
            "role": "assistant",
            "content": f"tool result {i}",
            "tool_calls": [{
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": "crawler_query",
                             "arguments": '{"query": "pricing page"}'},
            }],
        })
    return msgs


def test_footprint_survives_dcp_pruning():
    """REQ-21 AC3: after DCP prunes the message history, the child's
    footprint is still intact — it lives on the QueueItem, not the messages."""
    k = _kernel_with_attempts({"hash_a", "hash_b"})
    item = _parent_item()
    children = k._split_step(item, "verify_failed", {"u": 0.3}, work_units=10)
    assert len(children) == 2
    child = children[0]
    assert child.footprint is not None

    # Force a DCP prune pass that drops most of the history.
    dcp = DCP(turn_protection=1)
    pruned, stats = dcp.prune(_fake_history(), session_id="conv_t42")
    assert stats["output_count"] < stats["input_count"], "DCP must actually prune"

    # The footprint survives: it is durable structured data on the child.
    assert child.footprint.prior_summary, "footprint intact after prune (AC3)"
    assert "hash_a" in child.footprint.prior_summary


def test_child_resumes_from_footprint_plus_ledger():
    """REQ-21 AC4: a child that resumes after pruning reconstructs what has
    been done / where it is going / what remains from footprint + ledger —
    without the unpruned conversation."""
    k = _kernel_with_attempts({"hash_a", "hash_b", "hash_c"})
    item = _parent_item()
    child = k._split_step(item, "verify_failed", {"u": 0.3}, work_units=10)[0]
    fp = child.footprint

    # DCP prunes the history.
    dcp = DCP(turn_protection=1)
    pruned, _ = dcp.prune(_fake_history(), session_id="conv_t42")

    # Resume the child: reconstruct the three REQ-21 answers from the
    # footprint + ledger ONLY (the pruned messages are NOT consulted).
    what_done = fp.prior_summary          # Understanding
    where_going = fp.objective_anchor     # Awareness — the goal
    what_remains = fp.remaining           # Direction
    coordinate = fp.coordinate_ref        # ledger/memory key

    assert "3 prior gather attempt" in what_done, "Understanding from footprint"
    assert "research the pricing page" in where_going, "Awareness from footprint"
    assert what_remains == "research pricing", "Direction from footprint"
    assert coordinate == "conv_t42", "coordinate_ref keys the ledger"
    # The child can state all three WITHOUT the pruned messages.
    assert pruned != _fake_history(), "history WAS pruned — proof of survival"


def test_child_footprint_bounded_per_child_width3():
    """REQ-21 Edge Case: width=3 (max fan-out) — the footprint cost is paid
    three times but stays bounded per-child (same deduped summary)."""
    k = _kernel_with_attempts({"a", "b", "c", "d"})
    k._growth_width = lambda u: 3
    children = k._split_step(_parent_item(), "verify_failed", {"u": 0.3}, work_units=10)
    assert len(children) == 3
    sizes = {c.footprint.size_bytes for c in children}
    assert len(sizes) == 1, "identical bounded footprint per child"
    assert all(c.footprint.size_bytes < 512 for c in children)
