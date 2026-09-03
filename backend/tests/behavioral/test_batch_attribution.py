"""
Behavioral test: batch attribution (T4.6 / REQ-18 / REQ-19).

Three Sub-Loop children → exactly one router.generate() invocation → all three
results attributed to their correct step_id → one parent collapse.
"""
from backend.agent.batch_dispatch import (
    BatchGroup,
    dispatch_batch,
)


class _FakeChild:
    def __init__(self, step_id, desc=""):
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
        return (
            '<subloop id="p1_s1">Result A</subloop>'
            '<subloop id="p1_s2">Result B</subloop>'
            '<subloop id="p1_s3">Result C</subloop>',
            "",
            [],
        )


def test_exactly_one_transport_call_for_three_children():
    _r = _FakeRouter()
    _children = [
        _FakeChild("p1_s1", "Q1"),
        _FakeChild("p1_s2", "Q2"),
        _FakeChild("p1_s3", "Q3"),
    ]
    _g = BatchGroup(join_point="p1", quota_id="q1", children=_children)
    _g.batched_prompt = "Q1\nQ2\nQ3"
    _results = dispatch_batch(_g, _r, "m", [{"role": "user", "content": "go"}])
    # Exactly one transport call for 3 children
    assert _r.call_count == 1
    # All three results from their own segments
    assert _results.get("p1_s1") == "Result A"
    assert _results.get("p1_s2") == "Result B"
    assert _results.get("p1_s3") == "Result C"
