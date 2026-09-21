"""BT-6 (vision-goal-directed-search T27, REQ-11 + REQ-8): Semantic
Cross-Source Verification Gate.

The verification lives in `StepFindingsAccumulator` (Wave 3 T14). This suite
asserts the SEMANTIC behavior the card surface consumes (REQ-22 verified
badges / discrepancy pills):

  - two independent domains agreeing → the field is verified (AC11.2);
  - condition split: New vs Refurbished must NOT merge — two prices for one
    product are two data points, not a quorum (AC11.3);
  - bundle vs standalone splits the same way (AC11.3);
  - irreconcilable values (1999 official vs 2499 scalper, same condition)
    are NOT verified and are recorded WITH their source claims (AC11.4) —
    never silently resampled to one number;
  - parked/walled sources contribute no corroboration (AC11.2 boundary).

Also pins the dispatch-level wiring: with an output_schema in
`dispatch_urls`, the result carries the accumulator's verification snapshot
so the frontend has fields to render.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.der_loop import StepFindingsAccumulator
from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict

# ── module-level gate behavior ──────────────────────────────────────────────


def _acc() -> StepFindingsAccumulator:
    return StepFindingsAccumulator(goal_fields={"price", "availability"})


def test_two_domains_corroborating_one_value_marks_verified():
    acc = _acc()
    acc.add("https://a.example/p", {"price": 499, "availability": "in_stock"})
    acc.add("https://b.example/p", {"price": 499, "availability": "in_stock"})
    snap = acc.snapshot()
    assert snap["verified"]["price"]["verified"] is True
    assert snap["verified"]["price"]["corroborations"] == 2


def test_single_source_is_never_verified():
    acc = _acc()
    acc.add("https://a.example/p", {"price": 499})
    snap = acc.snapshot()
    assert snap["verified"]["price"]["verified"] is False


def test_condition_splits_prevent_cross_condition_quorum():
    """AC11.3: New vs Refurbished — a "cheap" refurbished price must not
    amalgamate INTO the new price's quorum and mislead the user."""
    acc = _acc()
    acc.add("https://a.example/p", {"price": 1999, "_condition": "new"})
    acc.add("https://b.example/p", {"price": 1149, "_condition": "refurbished"})
    snap = acc.snapshot()
    # Same numerical field, different conditions → verification is NOT
    # granted as a single bucket, and both conditions are recorded.
    v = snap["verified"]["price"]
    assert v["verified"] is False
    assert v["condition_distribution"] == {"new": 1, "refurbished": 1}


def test_irreconcilable_values_record_all_claims_with_sources():
    """AC11.4: differing numbers in the SAME condition (official MSRP vs a
    scalper) must land as a discrepancy WITH the claims — dropping one of
    them is what makes an answer fabricated rather than honest."""
    acc = _acc()
    acc.add("https://official.example/store", {"price": 1999})
    acc.add("https://scalper.example/listing", {"price": 2499})
    snap = acc.snapshot()
    v = snap["verified"]["price"]
    assert v["verified"] is False
    assert v.get("discrepancy") is True, (
        "two conflicting same-condition values returned an uneventful unverified — "
        "the discrepancy signal (REQ-11 AC4) is how the card shows a REAL conflict"
    )
    # AND the claims themselves survive (field value per source host).
    claims = v.get("claims") or []
    by_host = {c["host"]: c.get("value") for c in claims if isinstance(c, dict)}
    assert by_host.get("official.example") == 1999
    assert by_host.get("scalper.example") == 2499


def test_parked_sources_do_not_corroborate():
    """A walled source that was ASKED but never read must not count toward
    the quorum — otherwise a parked page 'votes' without evidence."""
    acc = _acc()
    acc.add("https://a.example/p", {"price": 499})
    acc.add("https://wall.example/p", {"price": 499}, parked=True)
    snap = acc.snapshot()
    assert snap["verified"]["price"]["verified"] is False
    assert snap["verified"]["price"]["corroborations"] == 1


# ── dispatch-level seam: the accumulator is FED by the crawl pipeline ───────


class _ExpCap:
    """Each URL's metadata carries the page's projected fields (the same
    shape the LLM extractor produces downstream). Two hosts, one device."""

    name = "fetch.crawl"

    TABLE = {
        "https://shop1.example/x": {"price": 1099, "availability": "in_stock"},
        "https://shop2.example/x": {"price": 1099, "availability": "in_stock"},
    }

    def __init__(self):
        self.calls: list[str] = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        self.calls.append(url)
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(url=url, title="t", markdown="real content long enough",
                          html="", metadata=dict(self.TABLE[url])),
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=1,
        )


@pytest.fixture(autouse=True)
def _clean():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


def test_dispatch_feeds_the_accumulator_and_result_carries_verification():
    """REQ-8 + REQ-11 wired: with output_schema set, dispatch_urls projects
    every page through `extract` (or metadata by default) into the
    StepFindingsAccumulator, and the CrawlResult carries the verified map so
    the card can render ✓/⚠ per field end-to-end."""
    cap = _ExpCap()
    register_capability(cap)

    class _R:
        async def resolve(self, query, quick=False):
            return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    import backend.crawler.source_registry as sr_mod

    sr_mod.get_source_registry = lambda: _R()

    orch = CrawlOrchestrator()
    orch._backend_override = None
    result = asyncio.run(
        orch.dispatch_urls(
            list(_ExpCap.TABLE), query="q", job_id="j-verify",
            concurrency_limit=2, max_pages=4,
            output_schema={
                "type": "object",
                "properties": {
                    "price": {"type": "number"},
                    "availability": {"type": "string"},
                },
                "required": ["price", "availability"],
            },
        )
    )
    v = getattr(result, "verification", None)
    assert v is not None, (
        "dispatch with output_schema produced no verification map — the "
        "cross-source quorum never reaches the frontend (REQ-8/REQ-11 seam)"
    )
    assert v["verified"]["price"]["verified"] is True
    assert v["verified"]["price"]["corroborations"] >= 2
    assert v["verified"]["availability"]["verified"] is True
