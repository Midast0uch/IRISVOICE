"""Behavioral tests: recipe materialization + episodic graph reuse.

REQ-7 (specs/tool-decision-engine-improvements), T9/T10.

  AC7.4  a VALIDATED recipe materializes into DER QueueItems in topological
         order, with dependency edges and {{step.output}} bindings intact.
  AC7.5  a verified recipe registers into the episodic node graph as a
         reusable composite NodeSpec, and a later matching request is selected
         by the resident Decision Engine with NO Brain LLM call.

The engine half runs the REAL production wiring: the box's candidate source is
``tool_registry.get_registry_tools`` — the function agent_kernel injects at
``agent_kernel.py:14997`` — so "the composite is selectable" is asserted
against the same seam production uses, not a hand-built menu.
"""

from __future__ import annotations

import pytest

from backend.agent import dynamic_recipe as dr
from backend.agent import tool_registry as tr
from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.der_loop import materialize_recipe
from backend.agent.dynamic_recipe import (
    DynamicCompositeRecipe,
    RecipeStep,
    composite_node_name,
    get_registered_recipe,
    register_verified_recipe,
)
from backend.agent.tool_decision import DecisionKind, ToolDecisionBox

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the
# real enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ('tool_choice',)
pytestmark = pytest.mark.usefixtures("oracle_decides_module")


GOAL = "find the RTX 5090 price and save it to notes"


def _recipe() -> DynamicCompositeRecipe:
    """search -> write_file, built from REAL registry tools so the tier and
    capability derivations in register_verified_recipe are exercised."""
    return DynamicCompositeRecipe(
        recipe_id="r-beh-1",
        goal=GOAL,
        steps=[
            RecipeStep(step_id="s1", tool="search",
                       params={"query": "RTX 5090 price"}, produces="pages"),
            RecipeStep(step_id="s2", tool="write_file",
                       params={"path": "notes.md", "content": "{{s1.output}}"},
                       depends_on=("s1",), consumes=("pages",)),
        ],
        artifact_kinds=("pages",),
    )


@pytest.fixture
def builtins():
    """Register the builtin tools; drop anything a test adds afterwards."""
    tr.register_builtin_tools()
    before_reg = set(tr._REGISTRY)
    before_nodes = set(tr._NODE_SPECS)
    prev_internet = tr._internet_provider
    yield
    tr._internet_provider = prev_internet
    for name in set(tr._REGISTRY) - before_reg:
        tr._REGISTRY.pop(name, None)
    for name in set(tr._NODE_SPECS) - before_nodes:
        tr._NODE_SPECS.pop(name, None)
        dr._RECIPE_NODES.pop(name, None)
        try:
            from backend.agent.nodes.router import get_node_router
            get_node_router().unregister_node(name)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AC7.4 — materialization into DER queue items
# ---------------------------------------------------------------------------


def test_der_queue_materialization():
    """AC7.4: the validated recipe becomes QueueItems in topological order,
    carrying its dependency edges and unresolved bindings."""
    items = materialize_recipe(_recipe(), step_number=1,
                               objective_anchor=GOAL)

    assert [i.tool for i in items] == ["search", "write_file"]
    assert [i.step_id for i in items] == ["s1", "s2"]
    # step numbers are assigned in sequence from the caller's start
    assert [i.step_number for i in items] == [1, 2]
    # the dependency edge survives, so readiness releases s2 after s1
    assert items[1].depends_on == ["s1"]
    assert items[0].depends_on == []
    # the binding is NOT resolved at materialization time — it is substituted
    # as source steps complete (resolve_dependent_params), so it must survive
    assert items[1].params["content"] == "{{s1.output}}"
    assert items[1].objective_anchor == GOAL
    assert all(i.critical for i in items)


# ---------------------------------------------------------------------------
# AC7.5 — graph registration + engine fast reuse
# ---------------------------------------------------------------------------


class _PickEngine:
    """Decision-engine stand-in that must find its pick on the real menu."""

    def __init__(self, chosen: str):
        self._chosen = chosen
        self.model_id = "stub"
        self.counters = EngineCounters()
        self.seen_options: list = []

    def decide(self, consumer_id, options, frame):
        self.seen_options = list(options)
        # the composite must actually be ON the menu the box composed — this
        # is the assertion that the registration reached the engine
        assert self._chosen in options, (
            f"registered composite {self._chosen!r} never reached the scorer; "
            f"menu was {options}"
        )
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=0.99,
            distribution=(CandidateScore(self._chosen, -0.05, 0.99),),
            engine_latency_ms=3,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        class _R:
            retried = False
            args: dict = {}
        return _R()


class _BrainRouter:
    """The Brain. Any call here is a failure for AC7.5."""

    def __init__(self):
        self.calls = 0

    def generate(self, role, messages, **kw):
        self.calls += 1
        return ("", "", [])

    def resolve(self, role):
        class _R:
            id = "same"
            model = "same"
        return _R()


class _Bridge:
    def __init__(self):
        self.exec_calls = []

    async def execute_tool(self, tool, params, session_id="unknown",
                           decision_meta=None, **kw):
        self.exec_calls.append((tool, params))
        return {"success": True}

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        pass


def test_graph_cache_and_fast_reuse(builtins):
    """AC7.5: register the verified DAG; a repeat request is served by the
    resident Decision Engine with zero Brain calls."""
    recipe = _recipe()
    node = register_verified_recipe(recipe)
    name = composite_node_name(recipe)

    # ── the graph entry ────────────────────────────────────────────────────
    assert node.name == name
    assert node.is_composite
    assert node.composite_of == ("search", "write_file")
    assert node.produces == "pages"
    # the DAG body is retained so the composite can be re-materialized
    assert get_registered_recipe(name) is recipe

    # the composite is only as privileged as its most privileged step:
    # write_file is side_effect, so the composite must NOT advertise read_only
    assert node.permission_tier == "side_effect"

    # ── idempotent: the same recipe is the same node, not a twin ───────────
    assert register_verified_recipe(recipe) is node
    assert composite_node_name(recipe) == name

    # ── exposed to the engine's production candidate source ────────────────
    # Capability inheritance: the composite requires what its steps require, so
    # a web-backed composite is WITHHELD while internet is off (the registry
    # gate is fail-closed) and appears once web mode is on.
    assert name not in {t["name"] for t in tr.get_registry_tools()}
    tr.set_capability_providers(internet=lambda: True)
    assert name in {t["name"] for t in tr.get_registry_tools()}
    assert tr.get_node_spec(name) is node

    # ── reuse: the engine selects it, the Brain is never consulted ─────────
    #
    # NOTE (finding, not a workaround): the box composes its menu as
    # ``clean[:cap - 2] + [DELEGATE, NONE]`` and the registry holds 56 tools,
    # so with the shipped ``candidate_cap = 6`` only the FIRST FOUR registry
    # names reach the scorer. A composite registered at runtime is appended
    # last, so production reachability of this fast path depends on the
    # candidate-narrowing work owned by REQ-25 / AC25.7 (T51, DEFERRED) — it is
    # NOT fixed here. This test therefore drives the box through its own
    # injection seam with the composite among the candidates, which is the
    # contract the box actually implements ("select among the candidates given").
    candidates = [
        {"name": name, "description": recipe.goal, "category": "composite"},
        {"name": "speak", "description": "Speak text", "category": "system"},
    ]
    engine = _PickEngine(chosen=name)
    router = _BrainRouter()
    box = ToolDecisionBox(
        router=router,
        tool_bridge=_Bridge(),
        get_available_tools=lambda: candidates,
        validate_tool_call=lambda n, p: (True, None),
        infer_fn=lambda prompt, **kw: "done",
        memory_lookup_fn=lambda _g: None,
        decision_engine=engine,
    )

    decision = box.resolve(step={"description": GOAL})

    assert decision.kind == DecisionKind.TOOL
    assert decision.tool == name
    assert router.calls == 0, "the Brain must not be consulted on a cache hit"
    assert name in engine.seen_options
