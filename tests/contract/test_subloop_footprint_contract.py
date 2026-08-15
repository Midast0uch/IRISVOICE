"""REQ-21 (T40/T41) contract pins: sub-loop children carry a compressed
footprint.

  - T40: ``QueueItem`` gains a bounded ``footprint: Optional[SubLoopFootprint]``
    field (der_loop.py); every NON-split-created construction is unaffected
    (defaults to None).
  - T41: ``_split_step`` populates each child's footprint with the THREE
    REQ-21 parts — Understanding (prior attempts across ALL attempts,
    bounded), Awareness (the goal), Direction (remaining/ruled_out) — plus a
    coordinate_ref and size_bytes bound. Bounded by construction: prior
    attempts are a deduplicated key set, so cost does NOT grow linearly with
    tool calls (AC2).

REQ-21 AC1 (coverage complete, bound on COST): the prior_summary covers ALL
committed attempts — truncation of the summary would be a spec failure; the
bound is on the summary's cost (deduped keys), not on which attempts it
covers.
"""

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import QueueItem, SubLoopFootprint


def _kernel_with_attempts(keys):
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv_req21"
    k.session_id = "conv_req21"
    k._der_crawl_attempts = {"conv_req21": set(keys)}
    k._der_ledger = type("L", (), {"conversation_id": "conv_req21"})()
    k._growth_width = lambda u: 2
    return k


def _parent_item():
    return QueueItem(
        step_id="s1", step_number=1, description="research pricing",
        objective_anchor="research the pricing page",
        expected_output="pricing facts",
        depth_layer=0, is_subloop=False, critical=True,
    )


# ── T40: the field exists and non-child steps are unaffected ───────────────


def test_queueitem_footprint_defaults_to_none():
    """Every existing construction (non-split-created step) is unaffected —
    footprint defaults to None."""
    q = QueueItem(step_id="s", step_number=1, description="ordinary step")
    assert q.footprint is None


def test_subloop_footprint_dataclass_fields():
    """The footprint carries the three REQ-21 parts + bound fields."""
    f = SubLoopFootprint(
        step_id="s1_s0", parent_step_id="s1",
        objective_anchor="research the pricing page",
        prior_summary="3 prior attempts",
        remaining="fetch pricing table",
        ruled_out="google search is exhausted",
        coordinate_ref="conv_req21",
        size_bytes=128,
    )
    assert f.step_id == "s1_s0"
    assert f.parent_step_id == "s1"
    assert f.remaining and f.ruled_out
    assert f.size_bytes > 0


# ── T41: _split_step populates the footprint ───────────────────────────────


def test_split_step_attaches_footprint_with_all_three_parts():
    """Each child from a split carries Understanding (prior attempts, ALL of
    them), Awareness (the goal), Direction (remaining), + coordinate_ref."""
    k = _kernel_with_attempts({"hash_a", "hash_b", "hash_c"})
    item = _parent_item()
    children = k._split_step(item, "verify_failed", {"u": 0.3}, work_units=10)

    assert len(children) == 2
    for child in children:
        assert child.is_subloop is True
        assert child.footprint is not None, "child must carry a footprint"
        fp = child.footprint
        # Understanding: ALL prior attempts covered, not a truncated sample.
        assert "3 prior gather attempt" in fp.prior_summary
        assert "hash_a" in fp.prior_summary
        assert "hash_b" in fp.prior_summary
        assert "hash_c" in fp.prior_summary
        # Awareness: the goal is inherited.
        assert fp.objective_anchor == "research the pricing page"
        assert child.objective_anchor == "research the pricing page"
        assert child.expected_output == "pricing facts"
        # Direction: remaining = the parent description.
        assert fp.remaining == "research pricing"
        # Coordinate ref + bound.
        assert fp.coordinate_ref == "conv_req21"
        assert fp.size_bytes > 0
        assert fp.parent_step_id == "s1"


def test_prior_summary_is_bounded_not_linear_in_attempts():
    """REQ-21 AC2: the footprint cost does NOT grow linearly with the number
    of prior tool calls — prior attempts are a DEDUPLICATED key set. 5 vs 50
    attempts yield summaries of comparable, bounded size."""
    small = _kernel_with_attempts({f"k{i}" for i in range(5)})
    large = _kernel_with_attempts({f"k{i}" for i in range(50)})
    item = _parent_item()
    c_small = small._split_step(item, "verify_failed", {"u": 0.3}, work_units=10)[0]
    c_large = large._split_step(item, "verify_failed", {"u": 0.3}, work_units=10)[0]
    # 10x more attempts -> far less than 10x the footprint bytes (deduped keys,
    # capped listing at 5 in the summary).
    assert c_large.footprint.size_bytes < c_small.footprint.size_bytes * 3, (
        "footprint cost must be bounded, not linear in attempt count (AC2)"
    )


def test_split_refused_when_width_zero_no_footprint_needed():
    """A refused split (width < 1) returns no children — nothing to carry."""
    k = _kernel_with_attempts({"a"})
    k._growth_width = lambda u: 0
    children = k._split_step(_parent_item(), "verify_failed", {"u": 0.9}, work_units=0)
    assert children == []
