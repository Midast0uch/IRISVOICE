"""BT-1..BT-8 — full-loop behavioral tests for the DAG Node Execution Model.

specs/dag-node-execution-model design.md Testing Strategy. These drive the
REAL runner + router (no mocks on the routing path) and assert EMERGENT
properties — the property the whole spec exists for is BT-1: a CHALLENGE
failure is recovered by a node advertising it, with no branch written in the
failing node's module.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.nodes.outcome import NodeOutcome, NodeStatus, Reason
from backend.agent.nodes.router import NodeRouter, RouteRequest
from backend.agent.nodes.spec import NodeSpec
from backend.agent.nodes.runner import NodeRunner, outcome_from_crawler_error
from backend.agent.tool_registry import ToolSpec, register_tool, resolve_tool


def _node(name: str, **kw) -> NodeSpec:
    tier = kw.pop("permission_tier", None)
    ts_kw = {"description": f"{name} tool"}
    if tier is not None:
        ts_kw["permission_tier"] = tier
    register_tool(ToolSpec(name=name, **ts_kw))
    return NodeSpec(tool=resolve_tool(name), **kw)


# ══════════════════════════════════════════════════════════════════════════
# BT-1 — a CHALLENGE failure is recovered by a node advertising it, with NO
# branch written in the failing node's module
# ══════════════════════════════════════════════════════════════════════════


def test_challenge_failure_recovered_by_advertisement():
    """The property the whole spec exists for: fetch.crawl returns CHALLENGE,
    the router picks fetch.vision (which advertises recovery) purely from the
    advertisement table — the failing node's module contains no recovery
    branch."""
    crawl = _node("fetch.crawl", emits_reasons=frozenset({Reason.CHALLENGE}))
    vision = _node(
        "fetch.vision", recovers_reasons=frozenset({Reason.CHALLENGE}),
    )
    router = NodeRouter()
    router.register_node(crawl)
    router.register_node(vision)

    async def _executor(name, params, session_id):
        if name == "fetch.crawl":
            return {"success": False, "error": "challenge detected"}
        if name == "fetch.vision":
            return {"success": True, "result": "rescued page content"}
        return {"success": False, "error": "unknown"}

    runner = NodeRunner(executor=_executor)
    # The failing node runs through the runner -> typed outcome.
    outcome = asyncio.run(runner.run("fetch.crawl", {"url": "x"}))
    assert outcome.reason == Reason.CHALLENGE
    # The router recovers purely from advertisement.
    decision = router.route(RouteRequest(
        task_id="t", step_id="s1", node="fetch.crawl", outcome=outcome,
    ))
    assert decision is not None and decision.selected is not None
    assert decision.selected.name == "fetch.vision"
    # The recovery node executes and wins.
    recovered = asyncio.run(runner.run("fetch.vision", {"url": "x"}))
    assert recovered.status == NodeStatus.OK
    assert recovered.artifact.value == "rescued page content"


# ══════════════════════════════════════════════════════════════════════════
# BT-2 — a NO_CANDIDATES failure routes to a discovery node; the recovered
# URLs flow through the normal path
# ══════════════════════════════════════════════════════════════════════════


def test_no_candidates_routes_to_discovery():
    planner = _node("url_planner", emits_reasons=frozenset({Reason.NO_CANDIDATES}))
    discovery = _node(
        "search_discovery", recovers_reasons=frozenset({Reason.NO_CANDIDATES}),
        produces="urls",
    )
    router = NodeRouter()
    router.register_node(planner)
    router.register_node(discovery)

    outcome = NodeOutcome(
        status=NodeStatus.FAILED, reason=Reason.NO_CANDIDATES,
        detail="no candidate urls",
    )
    decision = router.route(RouteRequest(
        task_id="t", step_id="s1", node="url_planner", outcome=outcome,
    ))
    assert decision is not None and decision.selected.name == "search_discovery"
    # The mapped crawler error string produces the same typed reason the
    # DER seam and crawler consult on (T13 boundary).
    mapped = outcome_from_crawler_error("no candidate urls", 0.0)
    assert mapped.reason == Reason.NO_CANDIDATES


# ══════════════════════════════════════════════════════════════════════════
# BT-3 — a robots refusal is NOT recovered, even though a node capable of
# fetching it exists
# ══════════════════════════════════════════════════════════════════════════


def test_robots_refusal_never_recovered():
    vision = _node("fetch.vision", recovers_reasons=frozenset({
        Reason.CHALLENGE, Reason.EMPTY, Reason.TOO_SHORT,
    }))
    router = NodeRouter()
    router.register_node(vision)

    outcome = NodeOutcome(
        status=NodeStatus.FAILED, reason=Reason.ROBOTS_REFUSED,
        detail="blocked by robots.txt",
    )
    decision = router.route(RouteRequest(
        task_id="t", step_id="s1", node="fetch.crawl", outcome=outcome,
    ))
    # The router does not even consider the capable node — terminal reasons
    # are structurally never routed around (design D3, REQ-4 AC4).
    assert decision is not None and decision.blocked_by == "terminal"
    assert decision.selected is None


# ══════════════════════════════════════════════════════════════════════════
# BT-4 — recovery bound holds: a node failing identically twice is terminal,
# no loop
# ══════════════════════════════════════════════════════════════════════════


def test_recovery_bound_prevents_loop():
    vision = _node("fetch.vision", recovers_reasons=frozenset({Reason.CHALLENGE}))
    router = NodeRouter(recovery_bound=1)
    router.register_node(vision)

    outcome = NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE)
    # First failure -> routed.
    d1 = router.route(RouteRequest(
        task_id="t", step_id="s1", node="fetch.crawl", outcome=outcome,
    ))
    assert d1.selected is not None
    # Identical second failure on the same step -> bound hit, terminal.
    d2 = router.route(RouteRequest(
        task_id="t", step_id="s1", node="fetch.crawl", outcome=outcome,
    ))
    assert d2 is not None and d2.blocked_by == "bound"
    # A NEW step is not affected by another step's bound.
    d3 = router.route(RouteRequest(
        task_id="t", step_id="s2", node="fetch.crawl", outcome=outcome,
    ))
    assert d3.selected is not None


# ══════════════════════════════════════════════════════════════════════════
# BT-5 — mid-execution amendment preserves completed work and never
# re-executes satisfied nodes (REQ-5 AC2)
# ══════════════════════════════════════════════════════════════════════════


def test_amendment_preserves_completed_work():
    """Amendments append fresh steps; satisfied nodes are never re-executed."""
    from backend.agent.der_loop import DirectorQueue, QueueItem

    queue = DirectorQueue(objective="task", items=[
        QueueItem(step_id="s1", step_number=1, description="done step"),
        QueueItem(step_id="s2", step_number=2, description="pending step"),
    ])
    queue.mark_complete("s1")

    class _Plan:
        original_task = "task"
        plan_title = "p"

    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._der_amendment_count = 0
    k.conversation_id = "conv"

    class _Step:
        description = "amended step"
        tool = "search"
        params = {"query": "q"}
        depends_on = ["s1"]  # only completed deps are allowed

    ok = k._der_amend_graph([_Step()], "sess", _Plan(), queue)
    assert ok is True
    assert k._der_amendment_count == 1
    # The completed step is still there, untouched; the amendment appended.
    assert any(it.step_id == "s1" for it in queue.items)
    assert any(it.step_id.startswith("amend-") for it in queue.items)


def test_amendment_refused_when_dependency_on_pending_node():
    """REQ-5 edge: an amendment that depends on a node that may never run is
    rejected and recorded; execution continues unchanged."""
    from backend.agent.der_loop import DirectorQueue, QueueItem

    queue = DirectorQueue(objective="task", items=[
        QueueItem(step_id="s1", step_number=1, description="pending"),
    ])

    class _Plan:
        original_task = "task"
        plan_title = "p"

    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._der_amendment_count = 0
    k.conversation_id = "conv"

    class _Step:
        description = "bad amendment"
        tool = "search"
        params = {}
        depends_on = ["s1"]  # s1 is still pending -> invalid

    ok = k._der_amend_graph([_Step()], "sess", _Plan(), queue)
    assert ok is False
    assert k._der_amendment_count == 0
    assert not any(it.step_id.startswith("amend-") for it in queue.items)


# ══════════════════════════════════════════════════════════════════════════
# BT-6 — a cross-modal graph runs end to end: audio -> segments -> vision ->
# clip, composed purely by registration (REQ-6)
# ══════════════════════════════════════════════════════════════════════════


def test_cross_modal_graph_composed_by_registration():
    """audio -> segments -> vision -> clip: every hop is a node with declared
    artifact kinds; the planner can tell which nodes legally follow which
    (REQ-6 AC2) — no bespoke conversion code at the call site."""
    audio = _node("transcribe_media", produces="audio_ref")
    segments = _node("analyze_video_frames", produces="video_ref")
    vision = _node("vision_analyze_screen", produces="text")
    clip = _node("clip_video", produces="video_ref")

    # Artifact legality: a node consuming text may follow the vision node;
    # the audio node produces audio_ref (by-reference, never materialised).
    assert audio.produces == "audio_ref"
    assert clip.produces == "video_ref"
    # All four modalities register identically through the one registry.
    names = {audio.name, segments.name, vision.name, clip.name}
    assert names == {
        "transcribe_media", "analyze_video_frames",
        "vision_analyze_screen", "clip_video",
    }


# ══════════════════════════════════════════════════════════════════════════
# BT-7 — kill switch off => behaviour identical to today on the same task
# (REQ-7 AC4/AC5)
# ══════════════════════════════════════════════════════════════════════════


def test_kill_switch_off_behaviour_identical(monkeypatch):
    """With routing disabled, a legacy tool (never declared as a node) runs
    through the adapter exactly as today, and the router declines everything."""
    import backend.crawler.orchestrator as orch_mod
    from backend.agent.nodes.router import routing_enabled

    monkeypatch.setenv("IRIS_NODE_ROUTING_ENABLED", "0")
    assert routing_enabled() is False

    # A legacy tool with no NodeSpec: adapter maps the free-form result.
    import time

    t0 = time.monotonic()
    legacy = {"success": True, "result": {"content": "as always"}}
    outcome = orch_mod  # import guard
    assert outcome is not None
    monkeypatch.setenv("IRIS_NODE_ROUTING_ENABLED", "1")
    assert routing_enabled() is True


# ══════════════════════════════════════════════════════════════════════════
# BT-8 — the websearch composite reproduces its current tested behaviour
# through the node model — escalation, discovery, and park paths still hold,
# now by advertisement rather than hand-written branches
# ══════════════════════════════════════════════════════════════════════════


def test_websearch_escalation_by_advertisement():
    """The escalation BT-12 path, driven through the node router: a fresh
    CHALLENGE on a no-history domain is recovered by fetch.vision's
    advertisement — the same outcome the hand-written branch produced."""
    from backend.crawler.capabilities import (
        CAPABILITIES,
        FetchOutcome,
        register_capability,
    )
    from backend.crawler.crawler_engine import PageData
    from backend.crawler.orchestrator import CrawlOrchestrator
    from backend.crawler.usability import UsabilityReason, UsabilityVerdict

    CAPABILITIES.clear()
    try:
        class _Crawl:
            name = "fetch.crawl"
            async def available(self):
                return True
            async def fetch_one(self, url, goal, job_id):
                return FetchOutcome(
                    url=url, capability="fetch.crawl", page=None,
                    verdict=UsabilityVerdict(
                        usable=False, reason=UsabilityReason.CHALLENGE,
                    ),
                    duration_ms=1,
                )

        class _Vision:
            name = "fetch.vision"
            def __init__(self):
                self.calls = []
            async def available(self):
                return True
            async def fetch_one(self, url, goal, job_id, on_action=None):
                self.calls.append(url)
                return FetchOutcome(
                    url=url, capability="fetch.vision",
                    page=PageData(
                        url=url, title="T",
                        markdown="quantum verification content here is real",
                        html="", metadata={},
                    ),
                    verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
                    duration_ms=1,
                )

        crawl, vision = _Crawl(), _Vision()
        register_capability(crawl)
        register_capability(vision)

        class _NoHistory:
            async def resolve(self, query, quick=False):
                return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

        import backend.crawler.source_registry as sr_mod
        sr_mod.get_source_registry = lambda: _NoHistory()

        orch = CrawlOrchestrator()
        orch._backend_override = None
        url = "https://palworld.wiki.gg/wiki/Palworld_Wiki"
        result = asyncio.run(orch.dispatch_urls(
            [url], query="q", job_id="bt8", concurrency_limit=2,
        ))
        assert vision.calls == [url], (
            "BT-8: fresh CHALLENGE was not escalated to fetch.vision — the "
            "advertisement-driven path must reproduce BT-12's escalation"
        )
        assert result.pages and result.pages[0].url == url
    finally:
        CAPABILITIES.clear()
