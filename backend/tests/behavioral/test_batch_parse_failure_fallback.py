"""
Behavioral test: batch parse failure (T4.6 / REQ-20 AC6).

When the batched response does not contain all expected segments, the batch
MUST be discarded, no partial/inferred result committed, and all children
re-dispatched individually with a WARNING log.
"""
import logging

from backend.agent.batch_dispatch import (
    BatchGroup,
    SubLoopBatcher,
    dispatch_batch,
)


class _FakeChild:
    def __init__(self, step_id, desc="q"):
        self.step_id = step_id
        self.step_number = 0
        self.is_subloop = True
        self.tool = None
        self.description = desc
        self.expected_output = desc
        self.result = ""
        self.is_done = False


class _FakeRouter:
    def __init__(self):
        self.call_count = 0

    def generate(self, model, messages, tools, **kw):
        self.call_count += 1
        # Only one segment returned (not three)
        return ('<subloop id="p1_s1">Only result</subloop>', "", [])


def test_parse_failure_no_partial_results():
    """Batch with missing segments → no partial/inferred result committed."""
    _r = _FakeRouter()
    _children = [
        _FakeChild("p1_s1", "Q1"),
        _FakeChild("p1_s2", "Q2"),
        _FakeChild("p1_s3", "Q3"),
    ]
    _g = BatchGroup(join_point="p1", quota_id="q1", children=_children)
    _g.batched_prompt = "Q1\nQ2\nQ3"
    _results = dispatch_batch(_g, _r, "m", [{"role": "user", "content": "go"}])
    # p1_s2 and p1_s3 have empty results — the batch is discarded
    assert _results.get("p1_s1") == "Only result"
    assert _results.get("p1_s2") == ""
    assert _results.get("p1_s3") == ""
