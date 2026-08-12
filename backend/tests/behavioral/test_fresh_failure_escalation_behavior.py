"""BT-12 — regression guard for the Problem-1 defect: vision never escalated
on a FRESH (first-time) failure.

Verified live 2026-08-10 17:09:08:
    dispatch ... url=https://palworld.wiki.gg/wiki/Palworld_Wiki cap=fetch.crawl
    usable=False reason=challenge
...and nothing followed. `_dispatch_one` only raced fetch.vision when
`source_registry` already had recorded failure history for the domain — a
domain hitting a bot challenge for the FIRST time in a run was routed to
`fetch.crawl` forever, because the race gate (REQ-10 AC3/AC4) is, by design,
history-only. This drives the real `CrawlOrchestrator.dispatch_urls` with
fake capabilities and asserts the escalation now fires — and that it never
fires for reasons that would route around robots.txt (REQ-5 AC3).
"""
from __future__ import annotations

import asyncio

import pytest

from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


def _usable_page(url):
    return PageData(
        url=url, title="T", markdown="quantum verification content here is real",
        html="", metadata={},
    )


def _usable_outcome(url, capability="fetch.crawl"):
    return FetchOutcome(
        url=url, capability=capability, page=_usable_page(url),
        verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
        duration_ms=1,
    )


class _FakeCrawlCap:
    """fetch.crawl fake that returns a per-URL canned outcome."""

    name = "fetch.crawl"

    def __init__(self, outcomes: dict):
        self._outcomes = outcomes
        self.calls: list[str] = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        self.calls.append(url)
        return self._outcomes[url]


class _FakeVisionCap:
    """fetch.vision fake that records which URLs it was asked to rescue."""

    name = "fetch.vision"

    def __init__(self, outcome_factory=_usable_outcome):
        self._outcome_factory = outcome_factory
        self.calls: list[str] = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id, on_action=None):
        self.calls.append(url)
        return self._outcome_factory(url, capability="fetch.vision")


@pytest.fixture(autouse=True)
def _clean_registry():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


class _NoHistoryRegistry:
    """No prior failure recorded for ANY domain — the race gate (REQ-10 AC4)
    must stay closed; escalation is the ONLY path that can reach vision."""

    async def resolve(self, query, quick=False):
        return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}


def _make_orch():
    orch = CrawlOrchestrator()
    orch._backend_override = None  # force the dispatch path
    import backend.crawler.source_registry as sr_mod

    sr_mod.get_source_registry = lambda: _NoHistoryRegistry()
    return orch


# ══════════════════════════════════════════════════════════════════════════
# Escalate: challenge / empty / too_short, on a domain with NO history
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("reason", [
    # CHALLENGE WAS REMOVED FROM THIS LIST ON PURPOSE, 2026-08-12, and is called
    # out here because dropping a parametrize case is normally a way of quietly
    # weakening a test. It is not dropped — it MOVED to
    # test_fresh_challenge_parks_instead_of_escalating below, which asserts the
    # behaviour the case now has. fetch.vision no longer advertises CHALLENGE:
    # escalating a wall to a headless browser measured 0/3 live over 240s+188s+
    # 243s and returned no content. EMPTY and TOO_SHORT are pages the crawl
    # REACHED but could not extract from, which is what vision is for, so they
    # stay here unchanged.
    UsabilityReason.EMPTY, UsabilityReason.TOO_SHORT,
])
def test_fresh_failure_escalates_to_vision_and_vision_result_wins(reason):
    """The Problem-1 regression guard: a FIRST-TIME crawl failure with a
    vision-recoverable reason must reach fetch.vision even though
    source_registry has no history for the domain."""
    url = "https://palworld.wiki.gg/wiki/Palworld_Wiki"
    crawl = _FakeCrawlCap({url: FetchOutcome(
        url=url, capability="fetch.crawl", page=None,
        verdict=UsabilityVerdict(usable=False, reason=reason, detail="fresh failure"),
        duration_ms=1,
    )})
    vision = _FakeVisionCap()
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch()

    result = asyncio.run(orch.dispatch_urls([url], query="q", job_id="j-esc", concurrency_limit=2))

    assert crawl.calls == [url], "crawl.fetch_one was not tried first"
    assert vision.calls == [url], (
        f"reason={reason.value} did NOT escalate to fetch.vision on a "
        f"no-history domain — this is the exact live defect (dispatch "
        f"usable=False reason={reason.value}, nothing followed)"
    )
    assert len(result.pages) == 1 and result.pages[0].url == url, (
        "vision rescued the page but the dispatch result did not carry it"
    )
    # REQ-17 AC6 / REQ-18 AC2: the rescued page carries provenance, exactly
    # like the raced path already does for a history-based escalation.
    assert result.pages[0].metadata.get("content_origin") == "vision"


def test_fresh_challenge_parks_instead_of_escalating():
    """The CHALLENGE case, moved out of the escalation parametrize above.

    It must do BOTH halves: not burn a vision session on a wall it cannot pass,
    and not vanish. A source the agent could not read has to remain visible to
    the user — dropping it silently just produces an answer with fewer citations
    and no explanation (REQ-13 AC4 / REQ-15).
    """
    url = "https://walled.example/guide"
    crawl = _FakeCrawlCap({url: FetchOutcome(
        url=url, capability="fetch.crawl", page=None,
        verdict=UsabilityVerdict(
            usable=False, reason=UsabilityReason.CHALLENGE, detail="cf-turnstile",
        ),
        duration_ms=1,
    )})
    vision = _FakeVisionCap()
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch()
    parked: list = []
    orch._park_source = lambda job_id, u, kind, emit: parked.append((u, kind))

    result = asyncio.run(orch.dispatch_urls(
        [url], query="q", job_id="j-wall", concurrency_limit=2,
    ))

    assert crawl.calls == [url], "crawl.fetch_one was not tried first"
    assert vision.calls == [], (
        f"a walled page was escalated to fetch.vision ({vision.calls}) — this is "
        f"the four-minute 0/3 path the advertisement change removed"
    )
    assert not result.pages, "a challenged page must not yield content"
    assert [u for u, _ in parked] == [url], (
        f"the walled source was not parked ({parked}) — skipping the escalation "
        f"must not mean skipping the report"
    )


def test_escalation_fires_at_most_once_per_url():
    """A URL escalates exactly once — vision.fetch_one is called a single
    time even when its own outcome is ALSO unusable (no retry loop)."""
    url = "https://still-bad.example/x"
    crawl = _FakeCrawlCap({url: FetchOutcome(
        url=url, capability="fetch.crawl", page=None,
        verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.EMPTY),
        duration_ms=1,
    )})

    def _vision_also_fails(u, capability="fetch.vision"):
        return FetchOutcome(
            url=u, capability=capability, page=None,
            verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.TRANSPORT_ERROR),
            duration_ms=1,
        )

    vision = _FakeVisionCap(outcome_factory=_vision_also_fails)
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch()

    result = asyncio.run(orch.dispatch_urls([url], query="q", job_id="j-once", concurrency_limit=2))

    assert vision.calls == [url], f"vision.fetch_one called {len(vision.calls)}x, expected exactly once"
    assert result.pages == []  # still unusable overall, but no crash / no loop


# ══════════════════════════════════════════════════════════════════════════
# Do NOT escalate: transport_error (robots.txt refusal, DNS failure)
# ══════════════════════════════════════════════════════════════════════════

def test_robots_txt_refusal_is_not_escalated():
    """REQ-5 AC3: fetch.vision has no robots gate of its own (only
    crawler_engine.crawl() checks robots.txt) — escalating a robots.txt
    refusal would silently route around compliance for the exact URL it
    just refused. Must NEVER reach fetch.vision."""
    url = "https://reddit.com/r/example"
    crawl = _FakeCrawlCap({url: FetchOutcome(
        url=url, capability="fetch.crawl", page=None,
        verdict=UsabilityVerdict(
            usable=False, reason=UsabilityReason.TRANSPORT_ERROR,
            detail="error=blocked by robots.txt",
        ),
        duration_ms=1,
    )})
    vision = _FakeVisionCap()
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch()

    asyncio.run(orch.dispatch_urls([url], query="q", job_id="j-robots", concurrency_limit=2))

    assert vision.calls == [], (
        "a robots.txt-refused URL reached fetch.vision — this bypasses "
        "REQ-5 AC3 robots compliance for exactly the URL it just refused"
    )


def test_dns_failure_is_not_escalated():
    """DNS failure is a transport_error too — vision cannot resolve a name
    crawl could not, so escalating it wastes a browser launch for nothing,
    and (more importantly) the reason is transport_error, which is
    deliberately excluded wholesale (see `_FRESH_FAILURE_ESCALATE_REASONS`
    in orchestrator.py — the robots.txt guard covers ALL transport_error,
    not only the robots-specific detail string)."""
    url = "https://this-domain-does-not-resolve.invalid/page"
    crawl = _FakeCrawlCap({url: FetchOutcome(
        url=url, capability="fetch.crawl", page=None,
        verdict=UsabilityVerdict(
            usable=False, reason=UsabilityReason.TRANSPORT_ERROR,
            detail="error=fetch failed: [Errno -2] Name or service not known",
        ),
        duration_ms=1,
    )})
    vision = _FakeVisionCap()
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch()

    asyncio.run(orch.dispatch_urls([url], query="q", job_id="j-dns", concurrency_limit=2))

    assert vision.calls == [], "a DNS failure reached fetch.vision — vision cannot resolve it either"


def test_usable_outcome_never_escalates():
    """A USABLE crawl outcome must never trigger escalation — the whole
    point of escalation is recovering a FAILURE, not double-fetching a
    success."""
    url = "https://good.example/a"
    crawl = _FakeCrawlCap({url: _usable_outcome(url)})
    vision = _FakeVisionCap()
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch()

    asyncio.run(orch.dispatch_urls([url], query="q", job_id="j-good", concurrency_limit=2))

    assert vision.calls == [], "vision was called even though crawl already succeeded"


def test_no_vision_registered_no_crash():
    """Escalation must degrade gracefully — no fetch.vision registered at
    all (REQ-6 AC1 edge) must not raise or loop."""
    url = "https://palworld.wiki.gg/wiki/Palworld_Wiki"
    crawl = _FakeCrawlCap({url: FetchOutcome(
        url=url, capability="fetch.crawl", page=None,
        verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.CHALLENGE),
        duration_ms=1,
    )})
    register_capability(crawl)  # fetch.vision NOT registered
    orch = _make_orch()

    result = asyncio.run(orch.dispatch_urls([url], query="q", job_id="j-nov", concurrency_limit=2))
    assert result.pages == []


# ══════════════════════════════════════════════════════════════════════════
# The existing history-based race path (REQ-10 AC3/AC4) is unchanged
# ══════════════════════════════════════════════════════════════════════════

def test_history_based_race_path_still_used_when_history_present():
    """Regression guard for the OTHER path (REQ-10 AC3): a domain WITH
    recorded failure history must still go through `_race_url` — BOTH
    capabilities are called even though crawl's outcome is already usable.
    The new sequential escalation only ever calls vision AFTER an unusable
    crawl outcome, so if this fired instead of the race, vision.calls would
    be empty (a usable crawl outcome never triggers escalation).

    FIXTURE INPUT CHANGED, 2026-08-12, and called out because the assertions are
    untouched: the recorded history was `last_error: "challenge"`. The race is
    advertisement-gated like everything else, and fetch.vision no longer
    advertises CHALLENGE — so a challenge-history domain correctly stops racing
    too. Knowing in advance that a domain walls us does not make vision better at
    walls; it just wastes the session earlier. The history is now `empty`, a
    reason vision DOES recover, so this still exercises the race mechanism that
    REQ-10 AC3 is about rather than the reason that no longer routes.
    """
    url = "https://known-bad.example/x"
    crawl = _FakeCrawlCap({url: _usable_outcome(url)})
    vision = _FakeVisionCap()  # would only be called by escalation if crawl failed
    register_capability(crawl)
    register_capability(vision)
    orch = CrawlOrchestrator()
    orch._backend_override = None

    class _HistoryRegistry:
        async def resolve(self, query, quick=False):
            return {
                "hit": True,
                "sources": [{"url": url, "domain": "known-bad.example", "last_error": "empty"}],
                "coverage_score": 1.0, "topics": ["q"],
            }

    import backend.crawler.source_registry as sr_mod
    sr_mod.get_source_registry = lambda: _HistoryRegistry()

    result = asyncio.run(orch.dispatch_urls([url], query="q", job_id="j-hist", concurrency_limit=2))

    assert crawl.calls == [url]
    assert vision.calls == [url], (
        "history present but vision was never called — the race path "
        "(REQ-10 AC3) has been replaced or broken by the escalation change"
    )
    assert result.pages[0].url == url
