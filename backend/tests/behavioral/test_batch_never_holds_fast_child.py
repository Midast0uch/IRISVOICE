"""
Behavioral test: fast child never held (T4.6 / REQ-15 AC3).

A child whose oscillator phase is near the firing point (θ ≈ π) must NOT wait
for a full batch. It dispatches individually within BATCH_MAX_HOLD_S.
"""
from backend.agent.batch_dispatch import (
    BATCH_MAX_HOLD_S,
    SubLoopBatcher,
)


class _FakeChild:
    def __init__(self, step_id, desc="fast"):
        self.step_id = step_id
        self.step_number = 0
        self.is_subloop = True
        self.tool = None
        # REQ-18 AC1: only independent sub-loop children are batchable.
        self.independent = True
        self.description = desc
        self.expected_output = desc


def test_fast_child_does_not_wait_full_batch():
    """A single Sub-Loop child must not be held past BATCH_MAX_HOLD_S."""
    _b = SubLoopBatcher()
    _c = _FakeChild("p1_s0")
    # Offer a single child — should not return a batch (needs 3)
    _result = _b.offer(_c, "q1")
    assert _result is None  # child is waiting for more
    # Flush expired should release it after BATCH_MAX_HOLD_S
    import time
    time.sleep(BATCH_MAX_HOLD_S + 0.05)
    _expired = _b.flush_expired()
    assert len(_expired) == 1
    assert _expired[0].join_point == "p1"
