"""Behavioral tests: REQ-4 depth-check — VERIFIED-but-shallow triggers gap analysis.

Drives TrailingDirector.analyze_gaps on a step that is VERIFIED (success)
but shallow (low depth_layer), and asserts it STILL returns gap-filling
items. The depth auditor is a double-check on the leading loop — it must
not be skipped just because the step passed verification. This is the
cross-layer seam (leading verify -> trailing depth audit).

Spec: specs/der-loop-integrity-display/requirements.md REQ-4.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.der_loop import QueueItem
from backend.agent.trailing_director import TrailingDirector


class _StubAdapter:
    def __init__(self, raw):
        self._raw = raw

    def infer(self, prompt, role=None, max_tokens=0, temperature=0.0):
        return SimpleNamespace(raw_text=self._raw)


_GAP_RAW = (
    '{"has_gaps": true, "confidence": 0.4, "gap_items": ['
    '{"description": "add edge-case handling", "depth_layer": 2}]}'
)


def _make_item(verified_label, depth_layer):
    it = QueueItem(
        step_id="step-1",
        step_number=1,
        description="build the widget",
        tool="code",
        params={},
        critical=False,
        objective_anchor="make a widget",
    )
    it.result = "widget built"
    it.verified_label = verified_label
    it.depth_layer = depth_layer
    return it


def _make_plan():
    return SimpleNamespace(original_task="make a widget")


class TestDepthCheckVerifiedButShallow:
    def test_verified_shallow_triggers_gap_analysis(self):
        td = TrailingDirector(_StubAdapter(_GAP_RAW), memory_interface=None)
        item = _make_item("VERIFIED", depth_layer=1)  # verified but shallow
        plan = _make_plan()
        gaps = td.analyze_gaps(item, plan, context_package=None, is_mature=True)
        # The depth auditor fires even though the step was VERIFIED.
        assert len(gaps) >= 1
        assert "edge-case" in gaps[0].description

    def test_unverified_also_triggers(self):
        td = TrailingDirector(_StubAdapter(_GAP_RAW), memory_interface=None)
        item = _make_item("FAILED", depth_layer=1)
        gaps = td.analyze_gaps(
            item, _make_plan(), context_package=None, is_mature=True
        )
        assert len(gaps) >= 1

    def test_no_gaps_returns_empty(self):
        _no_gap = '{"has_gaps": false, "gap_items": []}'
        td = TrailingDirector(_StubAdapter(_no_gap), memory_interface=None)
        item = _make_item("VERIFIED", depth_layer=3)
        gaps = td.analyze_gaps(
            item, _make_plan(), context_package=None, is_mature=True
        )
        assert gaps == []
