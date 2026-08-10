"""Standing CDD harness — specs/dag-node-execution-model REQ-1..REQ-9.

Replays a fixed set of failure→recovery trajectories through the REAL runner
and router, asserting BOTH the routes taken and the routes correctly NOT
taken (design.md Testing Strategy, tasks.md T17):

  challenge→vision        : a CHALLENGE failure routes to fetch.vision's
                            advertisement (REQ-4 AC1) — with no branch in the
                            failing node's module (BT-1, CT-4).
  no-candidates→discovery : a NO_CANDIDATES failure routes to
                            search_discovery (REQ-19 / T13).
  robots→terminal         : a robots.txt refusal is NEVER routed around, even
                            though a capable node exists (REQ-4 AC4, REQ-8
                            AC3, CT-5).
  budget→refused-amendment: an amendment that would exceed the per-task bound
                            is refused and recorded, execution unchanged
                            (REQ-5 AC3/AC5, REQ-9 AC3).

Follows the scripts/validate_der_*.py family conventions: [PASS]/[FAIL]
lines naming the REQ, exit 0 on success / non-zero on failure.

Run:  python scripts/validate_node_routing.py
"""

from __future__ import annotations

import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if os.path.isdir(os.path.join(_REPO, "backend")):
    sys.path.insert(0, _REPO)

from backend.agent.nodes.outcome import NodeOutcome, NodeStatus, Reason  # noqa: E402
from backend.agent.nodes.router import NodeRouter, RouteRequest  # noqa: E402
from backend.agent.nodes.runner import NodeRunner, outcome_from_crawler_error  # noqa: E402
from backend.agent.nodes.spec import NodeSpec  # noqa: E402
from backend.agent.tool_registry import ToolSpec, register_tool, resolve_tool  # noqa: E402


class _Failures:
    def __init__(self):
        self.items = []

    def check(self, name, cond):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            self.items.append(name)


def _node(name: str, **kw) -> NodeSpec:
    tier = kw.pop("permission_tier", None)
    ts_kw = {"description": f"{name} tool"}
    if tier is not None:
        ts_kw["permission_tier"] = tier
    register_tool(ToolSpec(name=name, **ts_kw))
    return NodeSpec(tool=resolve_tool(name), **kw)


def main() -> int:
    f = _Failures()

    # ── Trajectory 1 (REQ-4): challenge → vision ───────────────────────────
    crawl = _node("fetch.crawl", emits_reasons=frozenset({Reason.CHALLENGE}))
    vision = _node("fetch.vision", recovers_reasons=frozenset({Reason.CHALLENGE}))
    router = NodeRouter()
    router.register_node(crawl)
    router.register_node(vision)

    outcome = NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE)
    decision = router.route(RouteRequest(
        task_id="harness", step_id="t1", node="fetch.crawl", outcome=outcome,
    ))
    f.check(
        "REQ-4 AC1 challenge→vision routed by advertisement",
        decision is not None and decision.selected is not None
        and decision.selected.name == "fetch.vision",
    )
    # The mapped crawler error string yields the SAME typed reason (T11).
    f.check(
        "REQ-1 AC3 crawler 'challenge' maps to Reason.CHALLENGE",
        outcome_from_crawler_error("challenge detected", 0.0).reason == Reason.CHALLENGE,
    )

    # ── Trajectory 2 (REQ-19 / T13): no-candidates → discovery ────────────
    planner = _node("url_planner", emits_reasons=frozenset({Reason.NO_CANDIDATES}))
    discovery = _node("search_discovery", recovers_reasons=frozenset({Reason.NO_CANDIDATES}))
    router2 = NodeRouter()
    router2.register_node(planner)
    router2.register_node(discovery)
    d2 = router2.route(RouteRequest(
        task_id="harness", step_id="t2", node="url_planner",
        outcome=NodeOutcome(status=NodeStatus.FAILED, reason=Reason.NO_CANDIDATES),
    ))
    f.check(
        "REQ-19 no_candidates→discovery routed",
        d2 is not None and d2.selected is not None
        and d2.selected.name == "search_discovery",
    )

    # ── Trajectory 3 (REQ-4 AC4 / REQ-8 AC3): robots → terminal, never routed
    router3 = NodeRouter()
    router3.register_node(vision)  # a node capable of fetching exists
    d3 = router3.route(RouteRequest(
        task_id="harness", step_id="t3", node="fetch.crawl",
        outcome=NodeOutcome(status=NodeStatus.FAILED, reason=Reason.ROBOTS_REFUSED),
    ))
    f.check(
        "REQ-4 AC4 robots refusal NEVER routed around (terminal)",
        d3 is not None and d3.blocked_by == "terminal" and d3.selected is None,
    )
    f.check(
        "REQ-8 AC3 permission_denied also terminal",
        router3.route(RouteRequest(
            task_id="harness", step_id="t3b", node="fetch.crawl",
            outcome=NodeOutcome(status=NodeStatus.FAILED, reason=Reason.PERMISSION_DENIED),
        )).blocked_by == "terminal",
    )

    # ── Trajectory 4 (REQ-4 AC3): bound holds — no infinite loop ──────────
    router4 = NodeRouter(recovery_bound=1)
    router4.register_node(vision)
    o4 = NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE)
    d4a = router4.route(RouteRequest(task_id="h", step_id="t4", node="fetch.crawl", outcome=o4))
    d4b = router4.route(RouteRequest(task_id="h", step_id="t4", node="fetch.crawl", outcome=o4))
    f.check(
        "REQ-4 AC3 recovery bound holds (second identical failure terminal)",
        d4a.selected is not None and d4b is not None and d4b.blocked_by == "bound",
    )

    # ── Trajectory 5 (REQ-8 AC1/AC2): permission gate on recovery ──────────
    router5 = NodeRouter()
    router5.register_node(_node(
        "aggressive", permission_tier="destructive",
        recovers_reasons=frozenset({Reason.CHALLENGE}),
    ))
    d5 = router5.route(RouteRequest(
        task_id="h", step_id="t5", node="fetch.crawl",
        outcome=NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE),
        approved_tier="read_only",
    ))
    f.check(
        "REQ-8 AC2 recovery tier never exceeds approved tier",
        d5 is not None and d5.blocked_by == "permission" and d5.selected is not None,
    )

    # ── Trajectory 6 (REQ-5 AC3/AC5): amendment bound refused + recorded ───
    try:
        from backend.agent.der_loop import DirectorQueue, QueueItem
        from backend.agent.agent_kernel import AgentKernel

        queue = DirectorQueue(objective="task", items=[
            QueueItem(step_id="s1", step_number=1, description="step"),
        ])
        queue.mark_complete("s1")

        class _Plan:
            original_task = "task"
            plan_title = "p"

        k = AgentKernel.__new__(AgentKernel)
        k._der_amendment_count = 0
        k.conversation_id = "harness"

        class _Step:
            description = "amended"
            tool = "search"
            params = {}
            depends_on = ["s1"]

        applied = k._der_amend_graph([_Step()], "sess", _Plan(), queue)
        f.check("REQ-5 AC1 amendment applies within bound", applied is True)
        f.check(
            "REQ-5 AC2 completed work preserved by amendment",
            any(it.step_id == "s1" for it in queue.items),
        )
        # Force the bound: pre-set the counter to the bound.
        k._der_amendment_count = k._AMENDMENT_BOUND
        refused = k._der_amend_graph([_Step()], "sess", _Plan(), queue)
        f.check(
            "REQ-5 AC3/AC5 amendment refused when bound exceeded, no crash",
            refused is False,
        )
    except Exception as exc:  # noqa: BLE001 — harness must report, not die
        f.check(f"REQ-5 amendment trajectory ran ({exc})", False)

    # ── Trajectory 7 (REQ-7 AC4): kill switch disables routing ─────────────
    os.environ["IRIS_NODE_ROUTING_ENABLED"] = "0"
    from backend.agent.nodes.router import routing_enabled

    f.check("REQ-7 AC4 kill switch disables routing", routing_enabled() is False)
    d7 = router.route(RouteRequest(
        task_id="h", step_id="t7", node="fetch.crawl",
        outcome=NodeOutcome(status=NodeStatus.FAILED, reason=Reason.CHALLENGE),
    ))
    f.check("REQ-7 AC4 no decision while disabled", d7 is None)
    os.environ["IRIS_NODE_ROUTING_ENABLED"] = "1"

    # ── Summary ─────────────────────────────────────────────────────────────
    if f.items:
        print(f"\nNODE-ROUTING: {len(f.items)} FAILED")
        return 1
    print("\nNODE-ROUTING: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
