"""BT-13 (vision-goal-directed-search REQ-25, T38): extraction self-correction.

AC25.2: an invalid first extraction triggers EXACTLY ONE re-extract carrying
  the stated error (on page.metadata — hooks keep their 1-arg shape).
AC25.3: still-invalid accepts-as-is, flags unvalidated on the page, and the
  run continues (never raises, never retries again).
AC25.4: no-schema path costs nothing (hook once, no validation keys).

Runs against the real CrawlOrchestrator.dispatch_urls with a fake capability —
no network (same harness as the per-host throttling suite).
"""
from __future__ import annotations

import asyncio

import pytest

from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


@pytest.fixture(autouse=True)
def _clean():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


class _PageCap:
    """fetch.crawl returning one usable page per URL."""

    name = "fetch.crawl"

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(url=url, title="t", markdown="real content long enough",
                          html="", metadata={}),
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=1,
        )


def _no_history():
    class _R:
        async def resolve(self, query, quick=False):
            return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    import backend.crawler.source_registry as sr_mod

    sr_mod.get_source_registry = lambda: _R()


_SCHEMA = {
    "type": "object",
    "properties": {"price": {"type": "number", "minimum": 0}},
    "required": ["price"],
}


class _CorrectingHook:
    """First extraction mistypes price; the correction (with the stated error)
    returns a valid payload."""

    def __init__(self):
        self.calls: list[dict] = []
        self.seen_errors: list[str] = []

    def __call__(self, page):
        self.calls.append(dict(page.metadata or {}))
        err = (page.metadata or {}).get("_validation_error")
        if err:
            self.seen_errors.append(err)
        if len(self.calls) == 1:
            return {"price": "free"}  # wrong type: string vs number
        return {"price": 99}


class _StubbornHook:
    """Never valid — proves accept-and-flag after exactly one retry."""

    def __init__(self):
        self.calls = 0

    def __call__(self, page):
        self.calls += 1
        return {"price": -5}  # violates minimum: 0


def _run(extract, schema=_SCHEMA):
    register_capability(_PageCap())
    _no_history()
    orch = CrawlOrchestrator()
    return asyncio.run(
        orch.dispatch_urls(
            ["https://example.com/item"],
            query="t13",
            job_id="t13",
            output_schema=schema,
            extract=extract,
            concurrency_limit=1,
        )
    )


def test_invalid_first_extraction_triggers_one_stated_correction():
    """AC25.2: exactly one re-extract, carrying the validation error; the
    corrected payload flows to coverage (no unvalidated flag)."""
    hook = _CorrectingHook()
    result = _run(hook)
    assert len(hook.calls) == 2, f"expected initial + ONE correction, got {len(hook.calls)}"
    assert "_validation_error" not in hook.calls[0]
    assert len(hook.seen_errors) == 1
    assert "price" in hook.seen_errors[0]
    assert len(result.pages) == 1
    assert result.pages[0].metadata.get("unvalidated") is None
    assert "_validation_error" not in (result.pages[0].metadata or {})
    assert (result.verification or {}).get("instance", {}).get("price") == 99
    assert result.error is None


def test_still_invalid_accepts_and_flags_without_raising():
    """AC25.3: correction still fails → payload accepted as-is, flagged
    unvalidated on the page, hook ran exactly twice, run completes."""
    hook = _StubbornHook()
    result = _run(hook)
    assert hook.calls == 2, f"expected initial + ONE correction, got {hook.calls}"
    assert len(result.pages) == 1
    assert result.pages[0].metadata.get("unvalidated") is True
    assert result.error is None  # the run continues; nothing raises


def test_no_schema_path_costs_nothing():
    """AC25.4: without output_schema the projection never runs — the hook is
    not called at all (zero cost) and no validation keys touch metadata."""
    seen: list[dict] = []

    def _hook(page):
        seen.append(dict(page.metadata or {}))
        return {"price": 1}

    result = _run(_hook, schema=None)
    assert seen == []
    assert len(result.pages) == 1
    assert "_validation_error" not in (result.pages[0].metadata or {})
    assert (result.pages[0].metadata or {}).get("unvalidated") is None
