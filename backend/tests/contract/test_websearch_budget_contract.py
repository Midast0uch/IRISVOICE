"""What a websearch is allowed to cost, and what vision is allowed to be for.

Two decisions from the 2026-08-11 live run (job 40e4e523…, 7m43s for 5 URLs),
neither of which had any test at all — the production advertisement was declared
in capabilities.py and asserted nowhere, and every time bound was a per-subsystem
check rather than an enforced ceiling.

  1. fetch.vision no longer advertises CHALLENGE recovery. Advertising it made
     vision a challenge-recovery node, so it ONLY ever ran on pages the crawl had
     already failed — Cloudflare walls, which a headless browser fails too.
     Measured: three escalations at 240s / 188s / 243s, all three returning
     status=challenge. 0/3, for four minutes of a seven-minute turn.
  2. A run has ONE ceiling and the source count does not change it. Bounds that
     are checked and logged do not bind: the session's max_wall_ms was 60_000
     while it ran to elapsed_ms=243_112.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.agent.nodes.outcome import Reason


@pytest.fixture(autouse=True)
def _registered():
    from backend.crawler.capabilities import register_capability
    from backend.vision.fetch_vision import FetchVisionCapability

    register_capability(FetchVisionCapability())


# ══════════════════════════════════════════════════════════════════════════
# 1 — vision is the reading surface, not the wall-breaker
# ══════════════════════════════════════════════════════════════════════════

def test_vision_does_not_advertise_challenge_recovery():
    from backend.agent.tool_registry import get_node_spec

    spec = get_node_spec("fetch.vision")
    assert spec is not None, "fetch.vision declares no NodeSpec"
    assert Reason.CHALLENGE not in spec.recovers_reasons, (
        "fetch.vision advertises CHALLENGE again, so the router will send every "
        "walled page to it. Measured 0/3 success at ~4 minutes; a walled page "
        "must park and the run move to the next Exa URL instead."
    )


def test_vision_still_recovers_reachable_pages_that_yielded_nothing():
    """The retained half. EMPTY/TOO_SHORT are pages the crawl REACHED but could
    not extract from — where a reading pass adds content instead of fighting."""
    from backend.agent.tool_registry import get_node_spec

    spec = get_node_spec("fetch.vision")
    assert Reason.EMPTY in spec.recovers_reasons
    assert Reason.TOO_SHORT in spec.recovers_reasons


def test_robots_and_transport_are_still_never_routed_around():
    """Unchanged and non-negotiable (REQ-5 AC3 / REQ-8 AC3): vision navigates
    directly with no robots gate, so routing a refusal to it would bypass
    robots.txt for the very URL that was refused."""
    from backend.agent.tool_registry import get_node_spec

    spec = get_node_spec("fetch.vision")
    assert Reason.TRANSPORT_ERROR not in spec.recovers_reasons


def test_a_challenge_no_longer_routes_anywhere():
    """End to end through the real router, not a synthetic node: the reason that
    used to trigger a four-minute escalation now selects nothing."""
    from backend.crawler.orchestrator import _router_recovery_node

    assert _router_recovery_node("challenge", step_id="budget-test-1") != "fetch.vision"


# ══════════════════════════════════════════════════════════════════════════
# 2 — the run ceiling binds, and does not scale with the source count
# ══════════════════════════════════════════════════════════════════════════

class _SlowCap:
    """A capability that never finishes — stands in for a wall that hangs."""

    name = "fetch.crawl"

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id, on_progress=None, page_offset=0):
        await asyncio.sleep(3600)


def _dispatch_with_budget(urls, budget_ms, monkeypatch):
    from backend.crawler import orchestrator as _orch
    from backend.crawler.capabilities import register_capability
    from backend.crawler.orchestrator import CrawlOrchestrator

    monkeypatch.setattr(_orch, "_RUN_BUDGET_MS", budget_ms)
    register_capability(_SlowCap())
    monkeypatch.setattr(
        CrawlOrchestrator, "_domain_failure_history",
        lambda self, url, query: asyncio.sleep(0, result=""),
    )

    orch = CrawlOrchestrator()
    orch._backend_override = None
    t0 = time.monotonic()
    asyncio.run(orch.dispatch_urls(
        urls, query="q", job_id="job-budget", concurrency_limit=3,
    ))
    return (time.monotonic() - t0) * 1000


def test_a_hung_run_is_cut_off_at_the_ceiling(monkeypatch):
    elapsed = _dispatch_with_budget(
        [f"https://slow{i}.example/" for i in range(3)], 1500, monkeypatch,
    )
    assert elapsed < 6000, (
        f"dispatch ran {elapsed:.0f}ms against a 1500ms ceiling — the bound is "
        f"being checked but not enforced, which is exactly how max_wall_ms=60000 "
        f"coexisted with elapsed_ms=243112"
    )


def test_the_ceiling_does_not_scale_with_the_number_of_sources(monkeypatch):
    """The user's constraint stated directly: the source count must not change
    how long a search takes."""
    three = _dispatch_with_budget(
        [f"https://a{i}.example/" for i in range(3)], 1500, monkeypatch,
    )
    twelve = _dispatch_with_budget(
        [f"https://b{i}.example/" for i in range(12)], 1500, monkeypatch,
    )
    assert twelve < three * 2.5, (
        f"3 urls took {three:.0f}ms and 12 took {twelve:.0f}ms — the run grows "
        f"with the candidate count instead of holding a ceiling"
    )
