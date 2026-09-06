"""Unit tests for vision-goal-directed-search Wave 1 foundation (T1, T2).

Pure-logic tests (no I/O): GoalAnatomy shape/templates/mutation/duck-typing
(REQ-1 AC1.1-AC1.4), TemporalDelta (REQ-14), batch dataclasses (REQ-18).
"""

import json

import pytest

from backend.core_models import (
    BatchItemResult,
    BatchOutcome,
    BatchToolCall,
    GoalAnatomy,
    TaskType,
    TemplateKind,
    TemporalDelta,
)


def test_goal_anatomy_defaults_carry_guardrail_floor():
    """AC1.1: guardrails default to NO_PURCHASE + DOMAIN_BOUND."""
    g = GoalAnatomy(objective="find the price")
    assert g.guardrails == ["NO_PURCHASE", "DOMAIN_BOUND"]
    assert g.fields is None and g.schema is None
    # Per-instance lists: mutating one goal must not leak into another.
    g.guardrails.append("MAX_DEPTH")
    assert GoalAnatomy(objective="other").guardrails == ["NO_PURCHASE", "DOMAIN_BOUND"]


def test_goal_anatomy_full_shape():
    """AC1.1: all seven parts are representable."""
    g = GoalAnatomy(
        objective="price of X",
        task_type=TaskType.DATA_EXTRACTION,
        target="price table",
        target_anchor="MSRP",
        fields=["price", "availability"],
        schema={"type": "object", "required": ["price"]},
        steps=["fetch", "extract"],
        edge_cases={"out of stock": "set price to null"},
        memory_anchors={"product": "X"},
    )
    assert g.target_anchor == "MSRP"
    assert g.edge_cases["out of stock"] == "set price to null"


def test_templates_cover_a_through_h():
    """AC1.2: every template kind builds a well-formed goal."""
    for kind in TemplateKind:
        g = GoalAnatomy.from_template(kind, objective="probe")
        assert isinstance(g.task_type, TaskType)
        assert "NO_PURCHASE" in g.guardrails and "DOMAIN_BOUND" in g.guardrails
        assert g.steps, kind
    assert len(list(TemplateKind)) == 8


def test_mutate_revises_live_and_rejects_unknown_fields():
    """AC1.3: in-flight revision works; unknown fields fail explicitly."""
    g = GoalAnatomy.from_template(TemplateKind.A, objective="v1")
    out = g.mutate(objective="v2", fields=["price"])
    assert out is g and g.objective == "v2" and g.fields == ["price"]
    with pytest.raises(ValueError):
        g.mutate(no_such_field="x")
    # Copy-on-write variant leaves the original untouched.
    branched = g.branched(objective="v3")
    assert branched.objective == "v3" and g.objective == "v2"


def test_duck_typing_prompt_and_json():
    """AC1.4: to_prompt/to_json/__str__; str() is prompt text for legacy callers."""
    g = GoalAnatomy(
        objective="price of X",
        task_type=TaskType.DATA_EXTRACTION,
        target="price table",
        target_anchor="MSRP",
        fields=["price"],
        schema={"type": "object", "required": ["price"]},
        steps=["fetch"],
    )
    prompt = g.to_prompt()
    assert "price of X" in prompt and "price table" in prompt and "MSRP" in prompt
    assert str(g) == prompt
    assert f"Task: {g}".startswith("Task: Objective: price of X")
    payload = json.loads(g.to_json())
    assert payload["objective"] == "price of X"
    assert payload["task_type"] == "data_extraction"


def test_temporal_delta_shape():
    """REQ-14: delta container with revision + natural-language statements."""
    d = TemporalDelta(document_id="url_snapshot:abc", revision=1,
                      delta_statements=["Price dropped from $1999 to $1799"],
                      changed_fields=["price"])
    assert not d.is_empty
    assert TemporalDelta(document_id="x").is_empty


def test_batch_dataclasses_aggregate():
    """REQ-18 AC18.1/AC18.3: composite call node + consolidated outcome."""
    call = BatchToolCall(batch_id="b1", tool="crawler_query",
                         items=[{"url": "a"}, {"url": "b"}])
    assert len(call) == 2 and call.parallel_safe and call.independent
    outcome = BatchOutcome(batch_id="b1", tool="crawler_query", results=[
        BatchItemResult(item_key="a", ok=True, result={"price": 5}),
        BatchItemResult(item_key="b", ok=False, error="timeout"),
    ])
    assert outcome.ok_count == 1
    assert [r.item_key for r in outcome.usable()] == ["a"]
