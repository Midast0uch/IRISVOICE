"""
Tests for SubLoopBatcher (T4.2 / REQ-15).

Covers:
  * Non-Sub-Loop children pass through individually (None returned)
  * Sub-Loop children are grouped by join_point
  * Full group (BATCH_MAX_CHILDREN) triggers flush
  * Flush expired groups on timeout
  * Abandon drops a group
  * Parse batched response back to per-child results
"""
import time

from backend.agent.batch_dispatch import (
    BATCH_MAX_CHILDREN,
    BatchGroup,
    SubLoopBatcher,
    dispatch_batch,
)


class _FakeChild:
    def __init__(self, step_id, is_subloop=True, description="test", expected_output="out"):
        self.step_id = step_id
        self.is_subloop = is_subloop
        self.description = description
        self.expected_output = expected_output
        # REQ-18 AC1: only independent sub-loop children are batchable.
        self.independent = True
        self.step_number = 0


def test_non_subloop_passes_through():
    _b = SubLoopBatcher()
    _c = _FakeChild("p1_s1", is_subloop=False)
    assert _b.offer(_c, "q1") is None


def test_subloop_create_group():
    _b = SubLoopBatcher()
    _c = _FakeChild("p1_s1", is_subloop=True)
    # One child → waiting for more
    assert _b.offer(_c, "q1") is None


def test_full_group_flushes():
    _b = SubLoopBatcher()
    for i in range(BATCH_MAX_CHILDREN):
        _r = _b.offer(_FakeChild(f"p1_s{i}"), "q1")
    # Last child fills the group → returns the BatchGroup
    assert _r is not None
    assert len(_r.children) == BATCH_MAX_CHILDREN


def test_flush_expired():
    _b = SubLoopBatcher()
    _b.offer(_FakeChild("p1_s1"), "q1")
    _expired = _b.flush_expired()
    # No time has passed → not expired
    assert len(_expired) == 0


def test_abandon_drops_group():
    _b = SubLoopBatcher()
    _b.offer(_FakeChild("p1_s1"), "q1")
    _b.abandon("p1")
    assert len(_b._groups) == 0


def test_parse_batched_response():
    _b = SubLoopBatcher()
    _c1 = _FakeChild("p1_s1")
    _c2 = _FakeChild("p1_s2")
    from backend.agent.batch_dispatch import BatchGroup
    _g = BatchGroup(join_point="p1", quota_id="q1", children=[_c1, _c2])
    _b._compose_batch(_g)
    _resp = '<subloop id="p1_s1">\nresult A\n</subloop>\n<subloop id="p1_s2">\nresult B\n</subloop>'
    _results = _b.parse_batched_response(_g, _resp)
    assert _results.get("p1_s1") == "result A"
    assert _results.get("p1_s2") == "result B"


def test_parse_fallback_numbered():
    """Fallback parsing when subloop tags are absent."""
    _b = SubLoopBatcher()
    _c1 = _FakeChild("p1_s1", description="Query A")
    _c2 = _FakeChild("p1_s2", description="Query B")
    _g = BatchGroup(join_point="p1", quota_id="q1", children=[_c1, _c2])
    _b._compose_batch(_g)
    _resp = "# 1\nAnswer A\n# 2\nAnswer B"
    _results = _b.parse_batched_response(_g, _resp)
    # Fallback ordered extraction (may have trailing content)
    assert "Answer A" in _results.get("p1_s1", "")
    assert "Answer B" in _results.get("p1_s2", "")


def test_dispatch_batch():
    """dispatch_batch calls router.generate and parses results."""
    _c1 = _FakeChild("p1_s1")
    _c2 = _FakeChild("p1_s2")
    _g = BatchGroup(join_point="p1", quota_id="q1", children=[_c1, _c2])
    _g.batched_prompt = "Query A\nQuery B"

    class _FakeRouter:
        def generate(self, *a, **k):
            return (
                '<subloop id="p1_s1">Result A</subloop>'
                '<subloop id="p1_s2">Result B</subloop>',
                "",
                [],
            )

    _results = dispatch_batch(_g, _FakeRouter(), "m", [{"role": "user", "content": "go"}])
    assert _results.get("p1_s1") == "Result A"
    assert _results.get("p1_s2") == "Result B"
