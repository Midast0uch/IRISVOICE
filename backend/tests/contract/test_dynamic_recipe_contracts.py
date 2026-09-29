"""Contract tests: artifact kinds across recipe edges.

REQ-7 (specs/tool-decision-engine-improvements), T8.

  AC7.2  every node's declared ``produces`` artifact kind satisfies the
         downstream consumer's declared ``consumes`` — validated BEFORE
         execution, not discovered mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import pytest

from backend.agent.dynamic_recipe import (
    DynamicCompositeRecipe,
    RecipeStep,
    RecipeValidationError,
    validate_composite_recipe,
)


@dataclass
class _Spec:
    """Stand-in for NodeSpec — the validator only reads these two fields."""

    consumes: Tuple[str, ...] = ()
    produces: str = ""


NODE_SPECS = {
    "search": _Spec(consumes=(), produces="pages"),
    "summarize": _Spec(consumes=("pages",), produces="text"),
    "speak": _Spec(consumes=("text",), produces=""),
}


def test_artifact_consumes_produces():
    """AC7.2: matching kinds pass; a kind the consumer never declared is
    rejected pre-flight; an unknown tool is rejected too."""
    # (a) the legal chain pages -> text -> (sink)
    ok = DynamicCompositeRecipe(
        recipe_id="r-ok",
        goal="summarize the RTX page and read it aloud",
        steps=[
            RecipeStep(step_id="s1", tool="search",
                       params={"query": "RTX 5090"}, produces="pages"),
            RecipeStep(step_id="s2", tool="summarize",
                       params={"content": "{{s1.output}}"},
                       depends_on=("s1",), consumes=("pages",),
                       produces="text"),
            RecipeStep(step_id="s3", tool="speak",
                       params={"text": "{{s2.output}}"},
                       depends_on=("s2",), consumes=("text",)),
        ],
        artifact_kinds=("text",),
    )
    assert [s.step_id for s in validate_composite_recipe(ok, NODE_SPECS)] == [
        "s1", "s2", "s3"]

    # (b) the upstream producer's kind is NOT in the consumer's declaration
    mismatch = DynamicCompositeRecipe(
        recipe_id="r-bad",
        goal="speak the search results",
        steps=[
            RecipeStep(step_id="s1", tool="search",
                       params={"query": "q"}, produces="pages"),
            # speak declares consumes=("text",) but s1 produces "pages"
            RecipeStep(step_id="s2", tool="speak",
                       params={"text": "{{s1.output}}"},
                       depends_on=("s1",), consumes=("pages",)),
        ],
    )
    with pytest.raises(RecipeValidationError) as exc:
        validate_composite_recipe(mismatch, NODE_SPECS)
    assert "AC7.2" in str(exc.value)
    assert "pages" in str(exc.value)

    # (c) a step naming a tool with no declaration at all
    unknown = DynamicCompositeRecipe(
        recipe_id="r-unknown",
        goal="do a thing",
        steps=[RecipeStep(step_id="s1", tool="no_such_tool",
                          params={"x": "y"})],
    )
    with pytest.raises(RecipeValidationError) as exc:
        validate_composite_recipe(unknown, NODE_SPECS)
    assert "unknown tool" in str(exc.value)

    # (d) circular dependencies are rejected during topological validation
    cyclic = DynamicCompositeRecipe(
        recipe_id="r-cycle",
        goal="loop forever",
        steps=[
            RecipeStep(step_id="s1", tool="search", params={"query": "q"},
                       depends_on=("s2",)),
            RecipeStep(step_id="s2", tool="summarize", params={"content": "c"},
                       depends_on=("s1",)),
        ],
    )
    with pytest.raises(RecipeValidationError) as exc:
        validate_composite_recipe(cyclic, NODE_SPECS)
    assert "circular" in str(exc.value)
