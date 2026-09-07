"""BT (vision-goal-directed-search T30 / REQ-13 AC13.3-13.4): dynamic
in-flight query adaptation. When a schema journey ends with required fields
STILL uncovered and the caller supplied an `on_missing_fields` Brain hook,
the orchestrator must synthesize targeted follow-up URLs and fetch them IN
THE SAME RUN — the active DAG grows, nothing restarts.

Follow-up pages share the parent's accumulator + coverage (verification
extends, not resets), are deduplicated against attempted URLs, and own a
CONTINUED capture-address block (no slot collision with the parent).
"""
from __future__ import annotations

import asyncio

import pytest

from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


class _FieldCap:
    """fetch.crawl carrying per-URL payloads in page.metadata; records the
    capture page_offset each URL was dispatched with."""

    name = "fetch.crawl"

    def __init__(self, payload_by_url: dict):
        self.payload_by_url = payload_by_url
        self.calls: list[str] = []
        self.offsets: dict[str, int] = {}

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id, page_offset: int = 0):
        self.calls.append(url)
        self.offsets[url] = int(page_offset or 0)
        fields = self.payload_by_url[url]
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(
                url=url, title="t", markdown="content long enough to read",
                html="", metadata=dict(fields),
            ),
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=5,
        )


def _no_history():
    class _R:
        async def resolve(self, query, quick=False):
            return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    import backend.crawler.source_registry as sr_mod

    sr_mod.get_source_registry = lambda: _R()


@pytest.fixture(autouse=True)
def _clean():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


_SCHEMA = {
    "type": "object",
    "properties": {
        "price": {"type": "number"},
        "benchmarks": {"type": "string"},
    },
    "required": ["price", "benchmarks"],
}


def test_followup_fetched_in_same_run_and_verification_extends():
    """AC13.3: price lands on initial URLs, benchmarks missing -> Brain hook
    returns a follow-up URL -> follow-up fetched in the SAME dispatch, and
    the run's verification snapshot covers BOTH fields."""
    cap = _FieldCap(
        {
            "https://a.example/1": {"price": 1999},
            "https://a.example/2": {"price": 1999},
            "https://follow.example/specs": {"benchmarks": "4k-ultra-120fps"},
        }
    )
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    hook_calls: list[list] = []

    def _brain(missing: list) -> list:
        hook_calls.append(list(missing))
        assert "benchmarks" in missing
        assert "price" not in missing  # price already covered, not re-asked
        return ["https://follow.example/specs"]

    result = asyncio.run(
        orch.dispatch_urls(
            ["https://a.example/1", "https://a.example/2"],
            query="price and benchmarks", job_id="j-adapt",
            concurrency_limit=2, max_pages=2,
            output_schema=_SCHEMA,
            on_missing_fields=_brain,
        )
    )

    assert hook_calls, "Brain hook was never consulted for the missing field"
    assert "https://follow.example/specs" in cap.calls
    urls = {p.url for p in result.pages}
    assert {"https://a.example/1", "https://a.example/2",
            "https://follow.example/specs"} <= urls
    assert result.verification is not None
    assert set(_SCHEMA["required"]) <= set(result.verification["verified"]), (
        f"verification did not extend across the follow-up: {result.verification}"
    )


def test_no_followup_when_schema_already_satisfied():
    """AC13.3 boundary: nothing missing -> hook never fires, no extra fetch."""
    cap = _FieldCap(
        {
            "https://b.example/1": {"price": 1999, "benchmarks": "4k-120"},
        }
    )
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    def _brain(missing: list) -> list:  # pragma: no cover - must not run
        raise AssertionError(f"hook must not fire when nothing is missing: {missing}")

    result = asyncio.run(
        orch.dispatch_urls(
            ["https://b.example/1"],
            query="q", job_id="j-satisfied",
            concurrency_limit=2, max_pages=1,
            output_schema=_SCHEMA,
            on_missing_fields=_brain,
        )
    )
    assert [p.url for p in result.pages] == ["https://b.example/1"]


def test_followup_uses_continued_capture_block():
    """CT-3 / AC13.4: the child dispatch must NOT reuse the parent's slot-0
    block — its capture addresses continue after the parent's."""
    cap = _FieldCap(
        {
            "https://c.example/1": {"price": 1999},
            "https://c.example/2": {"price": 1999},
            "https://follow.example/specs": {"benchmarks": "4k-ultra"},
        }
    )
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    asyncio.run(
        orch.dispatch_urls(
            ["https://c.example/1", "https://c.example/2"],
            query="q", job_id="j-offset",
            concurrency_limit=2, max_pages=2,
            output_schema=_SCHEMA,
            on_missing_fields=lambda missing: ["https://follow.example/specs"],
        )
    )

    parent_offsets = {cap.offsets["https://c.example/1"],
                      cap.offsets["https://c.example/2"]}
    child_offset = cap.offsets["https://follow.example/specs"]
    assert child_offset not in parent_offsets, (
        f"follow-up slot collides with parent block: child={child_offset} "
        f"parent={sorted(parent_offsets)} offsets={cap.offsets}"
    )
