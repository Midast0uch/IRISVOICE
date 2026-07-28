"""
Contract tests for batch dispatch (T4.6 / CT-5, CT-8).

Pins:
  * CT-5: QueueItem shape (is_subloop, tool, step_id, step_number)
  * CT-8: abandon() drops a pending group (soft-cancel / turn boundary)
"""
import math

from backend.agent.batch_dispatch import SubLoopBatcher
from backend.agent.phase_manager import get_registry


class _FakeChild:
    def __init__(self, step_id, is_subloop=True, tool=None):
        self.step_id = step_id
        self.step_number = int(step_id.split("_s")[0].lstrip("p"))
        self.is_subloop = is_subloop
        self.tool = tool
        # REQ-18 AC1: only independent sub-loop children are batchable.
        self.independent = True
        self.description = "test"
        self.expected_output = "test"


def test_ct5_queue_item_shape():
    """CT-5: QueueItem shape — batcher expects is_subloop, tool, step_id."""
    _b = SubLoopBatcher()
    # Non-subloop → pass through
    _c = _FakeChild("p1_s1", is_subloop=False)
    assert _b.offer(_c, "q1") is None  # not batched, pass through
    # Subloop with tool → pass through
    _c2 = _FakeChild("p1_s2", tool="compute")
    assert _b.offer(_c2, "q1") is None  # has a tool, can't batch
    # Subloop without tool → batched
    _c3 = _FakeChild("p1_s3")
    assert _b.offer(_c3, "q1") is None  # batched (awaiting more)


def test_ct8_abandon_before_flush():
    """CT-8: abandon(join_point) drops a pending group — soft-cancel."""
    # Model a valid batchable child: independent (REQ-18 AC1) AND its quota's
    # oscillator placed at the firing point π so the phase-window gate (AC2)
    # admits it into a pending group.
    _osc = get_registry().register("q1:SUBLOOP", quota_id="q1", independent=True)
    _osc.theta = math.pi
    _b = SubLoopBatcher()
    _b.offer(_FakeChild("p1_s1"), "q1")
    assert len(_b._groups) == 1
    _b.abandon("p1")
    assert len(_b._groups) == 0
