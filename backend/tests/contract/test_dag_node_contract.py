"""CT-1..CT-10 — boundary pins for the DAG Node Execution Model.

specs/dag-node-execution-model design.md Testing Strategy. Every contract here
pins a boundary the recursive-operator seam could silently cross; CT-4's
caller-existence pins are the highest-value (this codebase produced 19
built-but-never-called mechanisms while delivering the websearch spec — a test
that a mechanism WORKS cannot see that; only a test that it is REACHED can).
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from backend.agent.nodes.outcome import (
    Artifact,
    NodeOutcome,
    NodeStatus,
    Reason,
    is_terminal_reason,
)
from backend.agent.nodes.runner import (
    NodeRunner,
    adapt_legacy_outcome,
    outcome_from_crawler_error,
)
from backend.agent.nodes.router import NodeRouter, RouteRequest, routing_enabled
from backend.agent.nodes.spec import NodeSpec
from backend.agent.tool_registry import (
    ToolSpec,
    get_node_spec,
    register_node,
    register_tool,
    resolve_tool,
)
from backend.crawler.usability import UsabilityReason

_REPO = Path(__file__).resolve().parents[3]


def _src(rel: str) -> str:
    p = _REPO / rel
    assert p.is_file(), f"expected {rel} to exist at {p}"
    return p.read_text(encoding="utf-8", errors="replace")


def _calls_in(rel: str, name: str) -> bool:
    """True when *rel* contains a real call to *name* (parsed — a mention in a
    comment/docstring cannot satisfy the pin). Modeled on
    test_single_judge_and_wiring_contract._calls_in (design.md CT-4)."""
    tree = ast.parse(_src(rel))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == name:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                return True
    return False


def _node(name: str, **kw) -> NodeSpec:
    """Build a registered NodeSpec. ``permission_tier`` (if given) belongs on
    the wrapped ToolSpec, not the NodeSpec — pass it through."""
    tier = kw.pop("permission_tier", None)
    ts_kw = {"description": f"{name} tool"}
    if tier is not None:
        ts_kw["permission_tier"] = tier
    register_tool(ToolSpec(name=name, **ts_kw))
    return NodeSpec(tool=resolve_tool(name), **kw)


# ══════════════════════════════════════════════════════════════════════════
# CT-1 — every registered node returns a NodeOutcome; no node raises into the
# planner (REQ-1 AC2)
# ══════════════════════════════════════════════════════════════════════════


def test_runner_never_raises_into_planner():
    """REQ-1 AC2: a node that raises is converted to FAILED/UNEXPECTED, and
    the runner itself never propagates an exception."""
    async def _boom(name, params, session_id):
        raise RuntimeError("node exploded")

    runner = NodeRunner(executor=_boom)
    outcome = asyncio.run(runner.run("boom", {}))
    assert outcome.status == NodeStatus.FAILED
    assert outcome.reason == Reason.UNEXPECTED
    assert "RuntimeError" in outcome.detail


def test_runner_maps_legacy_success_and_failure():
    """REQ-7 AC1: undeclared tools run exactly as today, adapted to an
    outcome without blocking."""
    import time

    t0 = time.monotonic()
    ok = adapt_legacy_outcome("x", {"success": True, "result": "hello"}, started=t0)
    assert ok.status == NodeStatus.OK and ok.artifact.value == "hello"
    fail = adapt_legacy_outcome("x", {"success": False, "error": "boom"}, started=t0)
    assert fail.status == NodeStatus.FAILED
    assert fail.reason == Reason.TRANSPORT_ERROR


# ══════════════════════════════════════════════════════════════════════════
# CT-2 — Reason is closed (REQ-1 AC3)
# ══════════════════════════════════════════════════════════════════════════


def test_reason_vocabulary_is_closed():
    """REQ-1 AC3: a NodeSpec cannot declare a reason outside the enum."""
    with pytest.raises(TypeError):
        _node("bad", recovers_reasons=frozenset({"not_a_reason"}))
    with pytest.raises(TypeError):
        _node("bad2", emits_reasons=frozenset({"also_bad"}))


def test_reason_seeded_from_usability_vocabulary():
    """REQ-1 Verified: the crawler's proven failure vocabulary maps 1:1.

    UsabilityReason.OK is a STATUS (a usable page), not a failure reason — it
    has no Reason member by design; the four failure reasons map exactly."""
    _reason_values = {r.value for r in Reason}
    assert {r.value for r in (
        UsabilityReason.EMPTY, UsabilityReason.TOO_SHORT,
        UsabilityReason.CHALLENGE, UsabilityReason.TRANSPORT_ERROR,
    )} <= _reason_values
    assert "ok" not in _reason_values, "OK is a status, never a failure reason"


# ══════════════════════════════════════════════════════════════════════════
# CT-3 — the outcome reason reaches the EXISTING node-record / error_type
# machinery, not a parallel structure (REQ-1 AC5)
# ══════════════════════════════════════════════════════════════════════════


def test_der_failure_reason_lands_in_existing_error_type_field():
    """REQ-1 AC5 / design ripple-map CONTRACT LOCK: agent_kernel's failure
    routing stamps the typed reason onto item.error_type — the SAME field the
    ledger's record_failure already reads. No parallel structure."""
    src = _src("backend/agent/agent_kernel.py")
    # The DER seam assigns the typed reason into the existing field.
    assert "item.error_type = outcome.reason.value" in src, (
        "the typed reason must be written into the existing item.error_type "
        "field so CT-3's 'not a parallel structure' holds"
    )
    # And the ledger still consumes that field (unchanged pre-existing read).
    assert "error_type=getattr(item, \"error_type\", None)" in src


# ══════════════════════════════════════════════════════════════════════════
# CT-4 — caller-existence pins: the router, the runner, and NodeSpec each have
# a REAL production caller, asserted by AST (design.md Testing Strategy)
# ══════════════════════════════════════════════════════════════════════════


def test_router_has_a_production_caller():
    """CT-4: the router's route() is reached from agent_kernel's DER failure
    seam AND from the crawler's advertisement consultation — not just from
    tests."""
    assert _calls_in("backend/agent/agent_kernel.py", "get_node_router"), (
        "NodeRouter has no production caller in agent_kernel — the DER failure "
        "seam must consult it (REQ-4)"
    )
    assert _calls_in("backend/agent/agent_kernel.py", "RouteRequest"), (
        "agent_kernel builds no RouteRequest — outcome-driven routing is unwired"
    )
    assert _calls_in("backend/crawler/orchestrator.py", "get_node_router"), (
        "orchestrator no longer consults the router — the websearch "
        "advertisements (T13) are dead"
    )


def test_runner_has_a_production_caller():
    """CT-4: get_node_runner().run() is reached from agent_kernel's DER
    recovery path — the runner is not built-but-never-called."""
    assert _calls_in("backend/agent/agent_kernel.py", "get_node_runner"), (
        "NodeRunner has no production caller — recovery nodes must execute "
        "through the runner (REQ-1 AC2)"
    )


def test_nodespec_registered_in_production():
    """CT-4: NodeSpec declarations happen in production code paths — the
    capabilities facade and the registry's default declarations — not only in
    tests."""
    assert _calls_in("backend/crawler/capabilities.py", "register_node"), (
        "capabilities facade never declares node metadata — fetch.crawl / "
        "fetch.vision / search_discovery are not nodes (REQ-2 AC4)"
    )
    assert _calls_in("backend/agent/tool_registry.py", "declare_default_node_metadata"), (
        "default node metadata (vision.* / media) is never declared"
    )


# ══════════════════════════════════════════════════════════════════════════
# CT-5 — REFUSED / ROBOTS_REFUSED / PERMISSION_DENIED are never routed around
# (REQ-4 AC4, REQ-8 AC3)
# ══════════════════════════════════════════════════════════════════════════


def test_terminal_reasons_never_routed():
    router = NodeRouter()
    router.register_node(_node("vision", recovers_reasons=frozenset({Reason.CHALLENGE})))
    for reason in (Reason.ROBOTS_REFUSED, Reason.PERMISSION_DENIED):
        outcome = NodeOutcome(status=NodeStatus.FAILED, reason=reason)
        decision = router.route(RouteRequest(
            task_id="t", step_id="s1", node="crawl", outcome=outcome,
        ))
        assert decision is not None and decision.blocked_by == "terminal", (
            f"{reason.value} was routed around — a deliberate refusal must "
            f"never be re-routed (REQ-4 AC4)"
        )
    refused = NodeOutcome(status=NodeStatus.REFUSED, reason=Reason.WALL)
    decision = router.route(RouteRequest(
        task_id="t", step_id="s1", node="crawl", outcome=refused,
    ))
    assert decision.blocked_by == "terminal"


def test_is_terminal_reason_covers_refusals():
    assert is_terminal_reason(Reason.ROBOTS_REFUSED)
    assert is_terminal_reason(Reason.PERMISSION_DENIED)
    assert not is_terminal_reason(Reason.CHALLENGE)


# ══════════════════════════════════════════════════════════════════════════
# CT-6 — a recovery node's permission tier is evaluated exactly as a planned
# node's, and cannot exceed the approved tier (REQ-8 AC1/AC2)
# ══════════════════════════════════════════════════════════════════════════


def test_recovery_tier_never_exceeds_approved():
    router = NodeRouter()
    # The only node advertising CHALLENGE is DESTRUCTIVE — the approved step
    # is read_only, so the route must be blocked, never taken silently.
    destructive = _node(
        "aggressive_recovery", permission_tier="destructive",
        recovers_reasons=frozenset({Reason.CHALLENGE}),
    )
    router.register_node(destructive)
    outcome = NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE)
    decision = router.route(RouteRequest(
        task_id="t", step_id="s1", node="crawl", outcome=outcome,
        approved_tier="read_only",
    ))
    assert decision is not None
    assert decision.selected is not None and decision.blocked_by == "permission", (
        "a destructive recovery node was selected for a read_only-approved step "
        "— routing must never exceed the approved tier (REQ-8 AC2)"
    )


def test_recovery_tier_within_approved_is_taken():
    router = NodeRouter()
    router.register_node(_node(
        "safe_recovery", permission_tier="read_only",
        recovers_reasons=frozenset({Reason.CHALLENGE}),
    ))
    outcome = NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE)
    decision = router.route(RouteRequest(
        task_id="t", step_id="s1", node="crawl", outcome=outcome,
        approved_tier="read_only",
    ))
    assert decision.selected is not None and decision.blocked_by is None


# ══════════════════════════════════════════════════════════════════════════
# CT-7 — an undeclared legacy tool executes unchanged, and the kill switch
# restores pre-change behaviour (REQ-7 AC1/AC4/AC5)
# ══════════════════════════════════════════════════════════════════════════


def test_kill_switch_disables_routing(monkeypatch):
    monkeypatch.setenv("IRIS_NODE_ROUTING_ENABLED", "0")
    assert routing_enabled() is False
    router = NodeRouter()
    router.register_node(_node(
        "vision", recovers_reasons=frozenset({Reason.CHALLENGE}),
    ))
    outcome = NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE)
    decision = router.route(RouteRequest(
        task_id="t", step_id="s1", node="crawl", outcome=outcome,
    ))
    assert decision is None, "routing returned a decision while disabled (REQ-7 AC4)"
    monkeypatch.setenv("IRIS_NODE_ROUTING_ENABLED", "1")
    assert routing_enabled() is True


def test_kill_switch_crawler_rollback_restores_prechange(monkeypatch):
    """REQ-7 AC5: with routing disabled the crawler's pre-change branch
    outcomes are restored byte-for-byte (design D8 rollback path)."""
    import backend.crawler.orchestrator as orch_mod

    monkeypatch.setenv("IRIS_NODE_ROUTING_ENABLED", "0")
    assert orch_mod._router_recovery_node("challenge") == "fetch.vision"
    assert orch_mod._router_recovery_node("empty") == "fetch.vision"
    assert orch_mod._router_recovery_node("too_short") == "fetch.vision"
    assert orch_mod._router_recovery_node("transport_error") is None
    assert orch_mod._router_recovery_node("no_candidates") == "search_discovery"
    assert orch_mod._router_recovery_node("robots_refused") is None
    monkeypatch.setenv("IRIS_NODE_ROUTING_ENABLED", "1")


# ══════════════════════════════════════════════════════════════════════════
# CT-8 — duplicate node registration fails at startup rather than shadowing
# (REQ-2 edge)
# ══════════════════════════════════════════════════════════════════════════


def test_duplicate_node_registration_fails_loudly():
    spec = _node("dup_probe", produces="pages")
    register_node(spec)
    with pytest.raises(ValueError):
        register_node(_node("dup_probe", produces="text"))  # same name, again
    # The original declaration is untouched (no silent shadow).
    assert get_node_spec("dup_probe") is spec


def test_node_registration_requires_existing_tool():
    """REQ-2: node metadata for an unknown tool fails loudly, never orphans."""
    fake = ToolSpec(name="never_registered_tool", description="x")
    with pytest.raises(ValueError):
        register_node(NodeSpec(tool=fake))


# ══════════════════════════════════════════════════════════════════════════
# CT-9 — composite keeps one outer outcome while recording sub-outcomes
# (REQ-3 AC2/AC4)
# ══════════════════════════════════════════════════════════════════════════


def test_composite_outer_outcome_with_sub_outcomes():
    sub1 = NodeOutcome(status=NodeStatus.OK, artifact=Artifact("pages"))
    sub2 = NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE)
    outer = NodeOutcome(
        status=NodeStatus.PARTIAL,
        reason=Reason.NONE,
        artifact=Artifact("pages"),
        sub_outcomes=[sub1, sub2],
    )
    # One outer outcome (AC4) that still carries its sub-node records (AC2).
    assert outer.status == NodeStatus.PARTIAL
    assert len(outer.sub_outcomes) == 2
    assert outer.sub_outcomes[1].reason == Reason.CHALLENGE
    # crawler_query is the reference composite (REQ-3 AC5 / T12).
    cq = get_node_spec("crawler_query")
    assert cq is not None and cq.is_composite, (
        "crawler_query must be declared as a composite (REQ-3 AC5)"
    )
    assert set(cq.composite_of) == {"fetch.crawl", "fetch.vision", "search_discovery"}


# ══════════════════════════════════════════════════════════════════════════
# CT-10 — large artifacts pass by reference; no video/audio materialised into
# the graph (REQ-6 edge case, design D7)
# ══════════════════════════════════════════════════════════════════════════


def test_large_artifacts_pass_by_reference():
    media = Artifact.by_ref("video_ref", "file:///tmp/clip.mp4")
    assert media.value is None, "a large artifact must not be materialised inline"
    assert media.ref == "file:///tmp/clip.mp4"
    audio = Artifact.by_ref("audio_ref", "data/capture.wav")
    assert audio.value is None and audio.ref == "data/capture.wav"
    # The media ToolSpecs declare the by-reference artifact kinds.
    assert get_node_spec("transcribe_media").produces == "audio_ref"
    assert get_node_spec("clip_video").produces == "video_ref"
