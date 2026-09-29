"""Unit tests: dynamic composite recipe synthesis + pre-flight validation.

REQ-7 (specs/tool-decision-engine-improvements), T8.

  AC7.1  the Brain synthesizes a recipe as a DAG of steps carrying data
         bindings ({{step_id.output}}), dependency edges, and target kinds.
  AC7.3  a required parameter that is unassigned, null, or unresolved REJECTS
         the recipe before anything executes (and asks for a repair).

Nothing here touches the registry, the queue, or a model — the models and the
validator are pure data + pure functions.
"""

from __future__ import annotations

import pytest

from backend.agent.dynamic_recipe import (
    DynamicCompositeRecipe,
    RecipeStep,
    RecipeValidationError,
    validate_composite_recipe,
)


def _two_step_recipe(**over) -> DynamicCompositeRecipe:
    """search -> write_file, the canonical synthesized two-tool recipe."""
    steps = over.pop("steps", None) or [
        RecipeStep(
            step_id="s1",
            tool="search",
            params={"query": "RTX 5090 price"},
            produces="pages",
        ),
        RecipeStep(
            step_id="s2",
            tool="write_file",
            params={"path": "notes.md", "content": "{{s1.output}}"},
            depends_on=("s1",),
            consumes=("pages",),
        ),
    ]
    return DynamicCompositeRecipe(
        recipe_id=over.pop("recipe_id", "r-synth-1"),
        goal=over.pop("goal", "find the RTX 5090 price and save it to notes"),
        steps=steps,
        artifact_kinds=over.pop("artifact_kinds", ("pages",)),
        **over,
    )


# ---------------------------------------------------------------------------
# AC7.1 — the synthesized DAG
# ---------------------------------------------------------------------------


def test_brain_recipe_synthesis_dag():
    """AC7.1: the synthesized recipe is a DAG — ordered steps, dependency
    edges, and {{step.output}} bindings the executor can resolve."""
    recipe = _two_step_recipe()

    assert recipe.step_ids() == ["s1", "s2"]
    assert recipe.source == "brain"
    # the binding the Brain emitted is discoverable as (source_step, output)
    assert recipe.bindings() == [("s1", "output")]
    assert recipe.steps[1].depends_on == ("s1",)
    assert recipe.steps[0].produces == "pages"

    order = validate_composite_recipe(recipe)
    # topological order: the producer precedes its consumer
    assert [s.step_id for s in order] == ["s1", "s2"]

    # a wider DAG still orders correctly (s3 depends on s2 depends on s1)
    wide = _two_step_recipe(steps=[
        RecipeStep(step_id="s1", tool="search", params={"query": "q"},
                   produces="pages"),
        RecipeStep(step_id="s2", tool="write_file",
                   params={"path": "a", "content": "{{s1.output}}"},
                   depends_on=("s1",), consumes=("pages",), produces="text"),
        RecipeStep(step_id="s3", tool="speak",
                   params={"text": "{{s2.output}}"}, depends_on=("s2",)),
    ])
    assert [s.step_id for s in validate_composite_recipe(wide)] == [
        "s1", "s2", "s3"]


# ---------------------------------------------------------------------------
# AC7.3 — null / missing / unresolvable parameters are rejected
# ---------------------------------------------------------------------------


def test_reject_null_or_missing_params():
    """AC7.3: an unassigned, null, or unresolvable required parameter rejects
    the DAG before execution and carries the reason for the repair request."""
    # (a) a null parameter
    nulled = _two_step_recipe(steps=[
        RecipeStep(step_id="s1", tool="search", params={"query": None},
                   produces="pages"),
        RecipeStep(step_id="s2", tool="write_file",
                   params={"path": "n.md", "content": "{{s1.output}}"},
                   depends_on=("s1",), consumes=("pages",)),
    ])
    with pytest.raises(RecipeValidationError) as exc:
        validate_composite_recipe(nulled)
    assert "query" in str(exc.value)
    assert "AC7.3" in str(exc.value)

    # (b) an empty-string parameter is equally unassigned
    blank = _two_step_recipe(steps=[
        RecipeStep(step_id="s1", tool="search", params={"query": "   "},
                   produces="pages"),
        RecipeStep(step_id="s2", tool="write_file",
                   params={"path": "n.md", "content": "{{s1.output}}"},
                   depends_on=("s1",), consumes=("pages",)),
    ])
    with pytest.raises(RecipeValidationError) as exc:
        validate_composite_recipe(blank)
    assert "query" in str(exc.value)

    # (c) a binding whose SOURCE STEP is not in depends_on can never resolve
    dangling = _two_step_recipe(steps=[
        RecipeStep(step_id="s1", tool="search", params={"query": "q"},
                   produces="pages"),
        RecipeStep(step_id="s2", tool="write_file",
                   params={"path": "n.md", "content": "{{s9.output}}"},
                   depends_on=("s1",), consumes=("pages",)),
    ])
    with pytest.raises(RecipeValidationError) as exc:
        validate_composite_recipe(dangling)
    assert "content" in str(exc.value)

    # (d) an empty recipe is not a DAG at all
    with pytest.raises(RecipeValidationError):
        validate_composite_recipe(DynamicCompositeRecipe(recipe_id="r0",
                                                         goal="g", steps=[]))
