"""DynamicCompositeRecipe — on-the-fly composite recipe synthesis + pre-flight
contract validation (REQ-7, specs/tool-decision-engine-improvements).

The Brain Agent synthesizes a recipe for a multi-tool goal when no existing
composite covers it (AC7.1): the sub-node execution sequence, data bindings
(``{{step_id.output}}``), and target artifact kinds. The ENGINE validates the
DAG BEFORE anything executes (AC7.2/AC7.3):

  * contract validation — every node's ``produces`` artifact kind satisfies
    the downstream consumer's ``NodeSpec.consumes`` declaration;
  * parameter validation — zero required tool schema parameters unassigned,
    null, or unresolved; an unresolvable parameter REJECTS the DAG and
    requests a repair;
  * circular dependencies — rejected during topological-sort validation.

Everything here is pure data + pure functions: no I/O, no model calls, no
store writes. The materialization (recipe → QueueItems) lives in der_loop.py
(T9); the registration of verified recipes into the episodic node graph lives
here too (T10, :func:`register_verified_recipe`).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover — NodeSpec is pure data, import is safe
    from backend.agent.nodes.spec import NodeSpec

logger = logging.getLogger("dynamic_recipe")

# Data bindings: {{step_id.output}} — the placeholder shape the Brain emits
# and resolve_dependent_params substitutes (AC7.1).
_BINDING = re.compile(r"\{\{\s*([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)\s*\}\}")


@dataclass
class RecipeStep:
    """One step of a synthesized composite recipe (AC7.1)."""

    step_id: str
    tool: str                       # the node/tool name to execute
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: Tuple[str, ...] = ()  # step_ids this step consumes from
    produces: str = ""              # artifact kind produced ("" = no artifact)
    consumes: Tuple[str, ...] = ()  # artifact kinds accepted from dependencies


@dataclass
class DynamicCompositeRecipe:
    """A Brain-synthesized composite recipe (AC7.1)."""

    recipe_id: str
    goal: str
    steps: List[RecipeStep] = field(default_factory=list)
    artifact_kinds: Tuple[str, ...] = ()  # the target artifact kinds
    source: str = "brain"           # "brain" (synthesized) | "graph" (recalled)

    def step_ids(self) -> List[str]:
        return [s.step_id for s in self.steps]

    def bindings(self) -> List[Tuple[str, str]]:
        """Every {{step_id.output}} binding in the recipe's params (AC7.1)."""
        found: List[Tuple[str, str]] = []
        for s in self.steps:
            for v in (s.params or {}).values():
                if isinstance(v, str):
                    found.extend(_BINDING.findall(v))
        return found


class RecipeValidationError(Exception):
    """A synthesized recipe failed pre-flight validation (AC7.3).

    Carries the reason so the caller can request a repaired DAG from the
    Brain Agent (the error-handling row: reject prior to execution, request
    a repair).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _topological_order(steps: List[RecipeStep]) -> List[RecipeStep]:
    """Kahn's algorithm. Raises RecipeValidationError on a circular
    dependency (the edge case: reject during topological sort validation)."""
    ids = {s.step_id for s in steps}
    if len(ids) != len(steps):
        raise RecipeValidationError("duplicate step_id in recipe")
    indeg = {s.step_id: 0 for s in steps}
    dependents: Dict[str, List[str]] = {s.step_id: [] for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep not in ids:
                raise RecipeValidationError(
                    f"step {s.step_id!r} depends on unknown step {dep!r}"
                )
            indeg[s.step_id] += 1
            dependents[dep].append(s.step_id)
    ready = [sid for sid, d in indeg.items() if d == 0]
    order: List[RecipeStep] = []
    by_id = {s.step_id: s for s in steps}
    while ready:
        sid = ready.pop(0)
        order.append(by_id[sid])
        for nxt in dependents[sid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(steps):
        cyclic = sorted(ids - {s.step_id for s in order})
        raise RecipeValidationError(
            f"circular dependency in recipe: {cyclic}"
        )
    return order


def _unresolved_params(step: RecipeStep) -> List[str]:
    """Required schema parameters that are unassigned, null, or unresolved
    (AC7.3). A param whose value is a {{binding}} placeholder is unresolved
    UNTIL its source step completes — pre-flight treats a binding whose
    source step is NOT in depends_on as unresolvable."""
    unresolved: List[str] = []
    for k, v in (step.params or {}).items():
        if v is None or (isinstance(v, str) and not v.strip()):
            unresolved.append(k)
            continue
        if isinstance(v, str):
            for src, _out in _BINDING.findall(v):
                if src not in step.depends_on:
                    unresolved.append(k)
                    break
    return unresolved


def validate_composite_recipe(
    recipe: DynamicCompositeRecipe,
    node_specs: Optional[Dict[str, Any]] = None,
) -> List[RecipeStep]:
    """Pre-flight contract + parameter validation (AC7.2/AC7.3).

    Returns the topologically-ordered steps when the DAG is valid. Raises
    RecipeValidationError when:
      * the recipe has no steps;
      * a step names an unknown tool (not in node_specs, when provided);
      * a step's ``produces`` artifact kind does not satisfy a downstream
        consumer's ``consumes`` declaration (AC7.2);
      * a required parameter is unassigned, null, or unresolvable (AC7.3);
      * the dependency graph is circular.

    ``node_specs`` maps tool name → an object with ``consumes``/``produces``
    (a NodeSpec or any stand-in). When None, the artifact-contract check is
    skipped (the caller validates the contract elsewhere).
    """
    if not recipe.steps:
        raise RecipeValidationError("recipe has no steps")
    order = _topological_order(recipe.steps)
    if node_specs:
        for s in order:
            spec = node_specs.get(s.tool)
            if spec is None:
                raise RecipeValidationError(
                    f"step {s.step_id!r} names unknown tool {s.tool!r}"
                )
            declared = tuple(getattr(spec, "consumes", ()) or ())
            if declared and s.consumes:
                missing = [c for c in s.consumes if c not in declared]
                if missing:
                    raise RecipeValidationError(
                        f"step {s.step_id!r} consumes {missing} but "
                        f"{s.tool!r} declares {list(declared)} (AC7.2)"
                    )
            # AC7.2: the downstream consumer's declaration must be satisfied
            # by the upstream producer's kind.
            for dep_id in s.depends_on:
                dep = next((x for x in recipe.steps if x.step_id == dep_id), None)
                if dep is not None and dep.produces and declared:
                    if dep.produces not in declared:
                        raise RecipeValidationError(
                            f"step {s.step_id!r} consumes {list(declared)} but "
                            f"dependency {dep_id!r} produces {dep.produces!r} "
                            "(AC7.2)"
                        )
    for s in order:
        unresolved = _unresolved_params(s)
        if unresolved:
            raise RecipeValidationError(
                f"step {s.step_id!r} has unresolvable required parameters: "
                f"{unresolved} (AC7.3)"
            )
    return order


# ── Episodic graph registration of VERIFIED recipes (REQ-7 AC7.5, T10) ───────
#
# Registration is what turns a one-off synthesized DAG into a resident
# capability. The composite's ToolSpec lands in the ONE tool registry (design
# D1 — no third registry), so ``get_registry_tools()`` — the candidate source
# the kernel injects into the Decision Engine — offers it on later turns, and
# the engine selects it by scoring the goal against the menu with NO Brain call
# (AC7.5).
#
# ``NodeSpec.composite_of`` carries the sub-graph NAMES (what the planner sees
# and can re-route at). The DAG BODY (params + ``{{step.output}}`` bindings) is
# retained in-process below so a re-selected composite can be re-materialized
# into QueueItems without re-synthesizing it. In-process only, deliberately: a
# new persistence layer would be a third store (design D1).

_COMPOSITE_PREFIX = "composite_"

# Permission tiers, least → most privileged. A composite is only as safe as its
# most privileged step — see register_verified_recipe.
_TIER_ORDER = {"read_only": 0, "side_effect": 1, "destructive": 2}

# composite node name -> the recipe body it was registered from (T10).
_RECIPE_NODES: Dict[str, "DynamicCompositeRecipe"] = {}


def composite_node_name(recipe: "DynamicCompositeRecipe") -> str:
    """Deterministic node name for *recipe* (AC7.5).

    Determinism is the whole point: the same DAG must resolve to the same node
    so a repeat request reuses it instead of registering a twin. The name is
    derived from the recipe's SHAPE (the ordered ``tool:produces`` chain plus
    the goal text) — never from ``recipe_id``, which the Brain is free to
    re-issue for an identical recipe.

    The goal text is embedded because the resident engine scores NAMES against
    the request (the pinned ONNX task shape carries no descriptions): an opaque
    hash would be unselectable. A short structural digest keeps two different
    DAGs for the same goal from colliding.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (recipe.goal or "").lower()).strip("_")[:40]
    if not slug:
        slug = re.sub(
            r"[^a-z0-9]+", "_", (recipe.recipe_id or "").lower()
        ).strip("_")[:40] or "recipe"
    shape = "|".join(f"{s.tool}:{s.produces}" for s in recipe.steps)
    digest = hashlib.sha256(shape.encode("utf-8")).hexdigest()[:8]
    return f"{_COMPOSITE_PREFIX}{slug}_{digest}"


def get_registered_recipe(node_name: str) -> Optional["DynamicCompositeRecipe"]:
    """The recipe body registered under *node_name*, or None (AC7.5)."""
    return _RECIPE_NODES.get(node_name)


def register_verified_recipe(
    recipe: "DynamicCompositeRecipe",
    node_specs: Optional[Dict[str, Any]] = None,
) -> "NodeSpec":
    """REQ-7 AC7.5 (T10): register a VERIFIED dynamic recipe into the episodic
    node graph as a reusable composite node.

    Steps:
      1. ``validate_composite_recipe`` runs FIRST — an unvalidated DAG never
         reaches the graph ("verified" is enforced here, not assumed from the
         caller's word). Reuses T8's validator; no second validator.
      2. Every step tool must exist in the tool registry — a composite we
         cannot tier-check or execute must never be registered, or the
         permission gate would approve it on an under-declared tier.
      3. A ToolSpec is registered for the composite (idempotent, per
         ``register_tool``) so ``get_registry_tools()`` — and therefore the
         Decision Engine's candidate menu — offers it.
      4. A ``NodeSpec`` with ``composite_of`` = the ordered sub-node tools is
         registered (the graph entry the planner reads).

    The composite's declared ``permission_tier`` is the MAXIMUM tier over its
    steps: a recipe that bundles a ``side_effect``/``destructive`` step must
    not be advertised as ``read_only``, or it would bypass the approval gate
    that the individual step would have triggered.

    Idempotent: re-registering the same recipe returns the existing node
    instead of tripping ``register_node``'s duplicate guard (CT-8 forbids two
    DIFFERENT nodes claiming one name — a re-verified recipe is the same node).

    Returns the registered :class:`NodeSpec`.
    """
    from backend.agent.nodes.spec import NodeSpec  # lazy — no import cycle
    from backend.agent.tool_registry import (
        ToolSpec,
        get_node_spec,
        register_node,
        register_tool,
        resolve_tool,
    )

    order = validate_composite_recipe(recipe, node_specs)
    name = composite_node_name(recipe)

    existing = get_node_spec(name)
    if existing is not None:
        _RECIPE_NODES.setdefault(name, recipe)
        return existing

    tier = "read_only"
    requires_internet = False
    for s in order:
        spec = resolve_tool(s.tool)
        if spec is None:
            raise RecipeValidationError(
                f"step {s.step_id!r} names tool {s.tool!r} which is not in the "
                "tool registry — refusing to register an unexecutable composite "
                "(AC7.5)"
            )
        _t = getattr(spec, "permission_tier", "read_only") or "read_only"
        if _TIER_ORDER.get(_t, 0) > _TIER_ORDER.get(tier, 0):
            tier = _t
        requires_internet = requires_internet or bool(
            getattr(spec, "requires_internet", False)
        )

    tool = resolve_tool(name)
    if tool is None:
        tool = register_tool(ToolSpec(
            name=name,
            description=(recipe.goal or name)[:400],
            parameters={},
            category="composite",
            permission_tier=tier,
            executor="internal",
            requires_internet=requires_internet,
        ))

    produces = next((s.produces for s in reversed(order) if s.produces), "")
    if not produces and recipe.artifact_kinds:
        produces = recipe.artifact_kinds[0]
    consumes: List[str] = []
    for s in order:
        for c in (s.consumes or ()):
            if c not in consumes:
                consumes.append(c)

    node = register_node(NodeSpec(
        tool=tool,
        consumes=tuple(consumes),
        produces=produces,
        composite_of=tuple(s.tool for s in order),
    ))
    _RECIPE_NODES[name] = recipe
    logger.info(
        "[dynamic_recipe] registered composite node=%s sub_nodes=%s tier=%s",
        name, node.composite_of, tier,
    )
    return node
