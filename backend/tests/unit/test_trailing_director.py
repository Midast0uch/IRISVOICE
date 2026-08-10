"""
Tests for trailing_director.py — TrailingDirector
Source: specs/IRIS_Swarm_PRD_v9.md (Section 8) + bootstrap/GOALS.md Step 1.6

Key requirements:
  - analyze_gaps() returns [] (not raises) when adapter fails
  - gap items are never critical=True
  - max 3 gap items returned per completed step

Run: python -m pytest backend/tests/test_trailing_director.py -v
"""

from unittest.mock import MagicMock
import json
import pytest


# ── Import sanity ──────────────────────────────────────────────────────────

def test_imports():
    from backend.agent.trailing_director import TrailingDirector
    assert TrailingDirector


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_step(step_id="s1", step_number=1, description="do thing",
               expected_output=None, result=None):
    step = MagicMock()
    step.step_id = step_id
    step.step_number = step_number
    step.description = description
    step.expected_output = expected_output
    step.result = result
    return step


def _make_plan(task="build feature"):
    plan = MagicMock()
    plan.original_task = task
    return plan


def _gap_response(gap_items=None, has_gaps=None):
    """Build a valid gap analysis JSON response."""
    if gap_items is None:
        gap_items = []
    if has_gaps is None:
        has_gaps = len(gap_items) > 0
    return json.dumps({
        "has_gaps": has_gaps,
        "confidence": 0.8,
        "gap_items": gap_items,
    })


# ── analyze_gaps() — never raises ────────────────────────────────────────

def test_analyze_gaps_returns_empty_list_when_adapter_raises():
    """adapter.infer() raises → [] returned, not exception."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("model down")
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert result == []


def test_analyze_gaps_returns_empty_list_on_runtime_error():
    """RuntimeError from adapter → [] returned, not exception."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.side_effect = RuntimeError("oom")
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert result == []


def test_analyze_gaps_returns_list_type_always():
    """Return type is always list, never None."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="not json")
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert isinstance(result, list)


# ── gap items are never critical=True ────────────────────────────────────

def test_gap_items_never_critical():
    """All returned QueueItems must have critical=False."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": "add edge case handling", "tool": None, "params": {}, "depth_layer": 1},
        {"description": "validate input schema", "tool": None, "params": {}, "depth_layer": 2},
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert len(result) > 0
    for item in result:
        assert item.critical is False, f"Gap item {item.step_id} has critical=True"


# ── max 3 gap items per completed step ───────────────────────────────────

def test_max_3_gap_items_returned():
    """Even if model returns 5 gap items, only 3 are returned."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": f"gap {i}", "tool": None, "params": {}, "depth_layer": 1}
        for i in range(5)
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert len(result) <= 3


def test_exactly_3_gap_items_when_3_provided():
    """3 gap items in model response → 3 returned."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": f"gap {i}", "tool": None, "params": {}, "depth_layer": 1}
        for i in range(3)
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert len(result) == 3


# ── has_gaps=False → empty list ───────────────────────────────────────────

def test_no_gaps_returns_empty_list():
    """has_gaps=false in model response → empty list returned."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=json.dumps({
        "has_gaps": False, "confidence": 0.9, "gap_items": []
    }))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert result == []


def test_has_gaps_true_but_empty_items_returns_empty():
    """has_gaps=true but empty gap_items → [] returned."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=json.dumps({
        "has_gaps": True, "confidence": 0.5, "gap_items": []
    }))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert result == []


# ── QueueItem fields on gap items ─────────────────────────────────────────

def test_gap_item_has_correct_step_id_format():
    """Gap item step_ids follow gap-{step_id}-{index} format."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": "fix edge case", "tool": None, "params": {}, "depth_layer": 1},
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(step_id="step_42"),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert len(result) == 1
    assert "gap" in result[0].step_id
    assert "step_42" in result[0].step_id


def test_gap_item_inherits_step_number():
    """Gap items use the same step_number as the completed step."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": "add validation", "tool": None, "params": {}, "depth_layer": 1},
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(step_number=7),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert result[0].step_number == 7


def test_gap_item_objective_anchor_set():
    """Gap items carry the plan's original_task as objective_anchor."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": "edge case", "tool": None, "params": {}, "depth_layer": 1},
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(task="design auth system"),
        context_package=None,
        is_mature=False,
    )
    assert result[0].objective_anchor == "design auth system"


def test_gap_item_depth_layer_set():
    """depth_layer from model response is stored on QueueItem."""
    from backend.agent.trailing_director import TrailingDirector
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": "deep fix", "tool": None, "params": {}, "depth_layer": 3},
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=None,
        is_mature=False,
    )
    assert result[0].depth_layer == 3


# ── _parse_gap_items() directly ──────────────────────────────────────────

def test_parse_gap_items_bad_json_returns_empty():
    """Invalid JSON → [] returned."""
    from backend.agent.trailing_director import TrailingDirector
    td = TrailingDirector(adapter=MagicMock(), memory_interface=MagicMock())
    result = td._parse_gap_items("{not valid json}", _make_step(), "task")
    assert result == []


def test_parse_gap_items_no_json_returns_empty():
    """No JSON blob in response → [] returned."""
    from backend.agent.trailing_director import TrailingDirector
    td = TrailingDirector(adapter=MagicMock(), memory_interface=MagicMock())
    result = td._parse_gap_items("sorry, no gaps found", _make_step(), "task")
    assert result == []


def test_parse_gap_items_caps_at_3():
    """Hard cap at 3 regardless of what the spec says."""
    from backend.agent.trailing_director import TrailingDirector
    td = TrailingDirector(adapter=MagicMock(), memory_interface=MagicMock())
    raw = _gap_response(gap_items=[
        {"description": f"g{i}", "tool": None, "params": {}, "depth_layer": 1}
        for i in range(10)
    ])
    result = td._parse_gap_items(raw, _make_step(), "task")
    assert len(result) <= 3


# ── Context package handling ──────────────────────────────────────────────

def test_analyze_gaps_handles_broken_context_package():
    """Broken context_package properties → no raise, still works."""
    from backend.agent.trailing_director import TrailingDirector

    class BrokenCtx:
        @property
        def mycelium_path(self):
            raise RuntimeError("gone")
        @property
        def gradient_warnings(self):
            raise RuntimeError("gone")

    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=_gap_response(gap_items=[
        {"description": "fix", "tool": None, "params": {}, "depth_layer": 1},
    ]))
    td = TrailingDirector(adapter=adapter, memory_interface=MagicMock())
    result = td.analyze_gaps(
        completed_step=_make_step(),
        plan=_make_plan(),
        context_package=BrokenCtx(),
        is_mature=True,
    )
    assert isinstance(result, list)
