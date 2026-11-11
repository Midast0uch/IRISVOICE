"""page_relevance and page_blocked: two shadow Oracle questions in the research path.

What these guard (2026-11-10, backend/agent/page_shadow.py):
  * each question has a PRODUCTION caller - the crawler's research funnel asks
    page_relevance once per usable page before the extraction; the Tier-1 ->
    browser escalation asks page_blocked before the browser fetch;
  * the consult runs on the oracle_shadow lane, never on the fetch path, and
    the frame carries only what the fetch saw (never the extraction / answer);
  * each row carries its new criteria stamp, an input_key and the replayable
    state, and joins an OUTSIDE label:
      page_relevance = the extraction cited the page in a PASSED turn
                       (unlabelled when the turn failed or nothing landed);
      page_blocked   = the browser fetch's own usability outcome
                       (unlabelled when the browser made no request);
  * shadow only: every page is still extracted, every escalation still runs.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from backend.agent import decision_engine as de
from backend.agent import page_shadow as ps
from backend.agent import turn_verdict_label as tvl
from backend.crawler import capabilities as caps
from backend.crawler.crawl_planner import CrawlPlan
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator, FetchBackend
from backend.crawler.usability import UsabilityReason, UsabilityVerdict
from backend.utils.durability_queue import lane
from scripts.calibrate_decision_threshold import decision_label


class _FakeEngine:
    """Records every noul consult; P(true) comes from a per-url table."""

    model_id = "fake-d1"

    def __init__(self, p_by_url=None, default=0.7):
        self.calls = []
        self.p_by_url = p_by_url or {}
        self.default = default

    def noul(self, consumer_id, statement, frame, *, true_label="yes", false_label="no"):
        self.calls.append((consumer_id, dict(frame), threading.current_thread().name))
        p = self.p_by_url.get(frame.get("url"), self.default)
        return de.Noul(consumer_id=consumer_id, probability=p, engine_latency_ms=3)


@pytest.fixture
def harness(monkeypatch):
    ps.reset()
    tvl.reset()
    rows = []
    ps.set_row_sink(rows.append)
    eng = _FakeEngine()
    monkeypatch.setattr(ps, "ENGINE", eng)
    token = de.set_scope(turn_id="turn-page-1", step_id=None, node_exec_id=None)
    yield eng, rows
    de._SCOPE.reset(token)
    ps.set_row_sink(None)
    ps.reset()
    tvl.reset()


def _drain():
    assert lane("oracle_shadow").flush(10.0)


# -- page_relevance ---------------------------------------------------------

_PAGE_A = PageData(url="https://example.gov/doc", title="Doc", html="", metadata={},
                   markdown="X is the quantum model. X was verified by Y. What X means is key.")
_PAGE_B = PageData(url="https://news.example.com/a", title="News", html="", metadata={},
                   markdown="X appears in the new report. X is mentioned again in section three.")
_SUMMARY = "X is the quantum model verified by Y."


class _TwoPages(FetchBackend):
    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kw):
        return CrawlResult(query=query, pages=[_PAGE_A, _PAGE_B], duration_ms=5,
                           crawled_at="2026-11-10T00:00:00+00:00")


class _Planner:
    async def plan(self, query):
        return CrawlPlan(urls=[_PAGE_A.url, _PAGE_B.url], instructions="extract facts",
                         result_type="mixed", title="T")


class _Extractor:
    """Cites page A only; records what it was given and when."""

    def __init__(self):
        self.seen_urls = None
        self.queued_at_extract = None

    async def extract(self, result, instructions, result_type, title, **kw):
        self.seen_urls = [p.url for p in result.pages]
        self.queued_at_extract = ps.stats()["relevance_queued"]
        return {"title": title, "summary": _SUMMARY, "key_findings": [], "sources": []}


def _research(extractor):
    orch = CrawlOrchestrator(planner=_Planner(), extractor=extractor)
    orch._backend_override = _TwoPages()
    return asyncio.run(orch.research("what is X", mode="agent", session_id="s-page"))


def test_page_relevance_is_asked_per_usable_page_before_extraction_on_the_lane(harness):
    eng, rows = harness
    ext = _Extractor()
    result = _research(ext)
    _drain()
    # shadow only: the extraction still read BOTH pages
    assert ext.seen_urls == [_PAGE_A.url, _PAGE_B.url]
    assert result.cited_markdown and _PAGE_A.url in result.cited_markdown
    # asked BEFORE the extraction, once per usable page
    assert ext.queued_at_extract == 2
    calls = [c for c in eng.calls if c[0] == "page_relevance"]
    assert sorted(c[1]["url"] for c in calls) == sorted([_PAGE_A.url, _PAGE_B.url])
    for _cid, frame, thread_name in calls:
        # on the oracle_shadow lane, never on the crawl's own thread
        assert thread_name == "iris-oracle_shadow", thread_name
        # the question + what the fetch saw; nothing from the extraction
        assert frame["goal"] == "what is X"
        assert set(k for k, v in frame.items() if v) <= set(
            de.ORACLE_JOBS["judge_page"].fields)
        assert _SUMMARY not in str(frame)
    # rows are HELD for the turn verdict, not written unlabelled
    assert rows == []


def test_page_relevance_label_is_the_extraction_citation_in_a_passed_turn(harness):
    eng, rows = harness
    eng.p_by_url = {_PAGE_A.url: 0.9, _PAGE_B.url: 0.8}
    _research(_Extractor())
    _drain()
    assert tvl.report_verdict("turn-page-1", True) == 2
    by_url = {r["url"]: r for r in rows}
    a, b = by_url[_PAGE_A.url], by_url[_PAGE_B.url]
    assert a["outside_label"] is True and b["outside_label"] is False
    for r in (a, b):
        assert r["consumer_id"] == "page_relevance"
        assert r["criteria_version"] == "page_relevance/v1"
        assert r["label_source"] == "outcome" and r["shadow"] is True
        assert r["chosen"] is True and r["input_key"] and r["state"]
        assert r["turn_id"] == "turn-page-1" and r["job_id"]
    # the report's one label rule scores them: A right, B wrong
    assert decision_label(None, {}, a) is True
    assert decision_label(None, {}, b) is False


def test_page_relevance_rows_in_a_failed_turn_stay_unlabelled(harness):
    _eng, rows = harness
    _research(_Extractor())
    _drain()
    assert tvl.report_verdict("turn-page-1", False) == 0
    assert len(rows) == 2
    for r in rows:
        assert "outside_label" not in r and r["unlabelled"] == "turn_failed"
        assert decision_label(None, {}, r) is None


def test_page_relevance_without_a_landed_extraction_stays_unlabelled(harness):
    _eng, rows = harness
    ps.submit_page_relevance("what is X", [_PAGE_A, _PAGE_B], "job-never-extracted")
    _drain()
    assert tvl.report_verdict("turn-page-1", True) == 0
    assert len(rows) == 2
    assert {r["unlabelled"] for r in rows} == {"extraction_not_landed"}


def test_page_relevance_in_a_one_page_job_stays_unlabelled(harness):
    """The citation binding gives every summary sentence to the best-overlap
    page, so the only page of a job is cited by construction: no label."""
    _eng, rows = harness
    ps.submit_page_relevance("what is X", [_PAGE_A], "job-one-page")
    ps.note_extraction("job-one-page", {}, f"{_SUMMARY} [1]({_PAGE_A.url})")
    _drain()
    assert tvl.report_verdict("turn-page-1", True) == 0
    assert rows and rows[0]["unlabelled"] == "single_page_job"
    assert decision_label(None, {}, rows[0]) is None


# -- page_blocked -------------------------------------------------------------


def _tier1(verdict: UsabilityVerdict, text: str = "Just a moment... verify you are human",
           status: int = 403) -> caps.FetchOutcome:
    page = PageData(url="https://walled.example/p", title="Just a moment...",
                    markdown=text, html=None, metadata={}, error="challenge")
    return caps.FetchOutcome(
        url=page.url, capability="fetch.crawl", page=page if verdict.usable else None,
        verdict=verdict, har_entries=[{"url": page.url, "status": status}],
        observed_page=page)


_CHALLENGE = UsabilityVerdict(usable=False, reason=UsabilityReason.CHALLENGE)
_OK = UsabilityVerdict(usable=True, reason=UsabilityReason.OK)


def _browser(verdict, har=True):
    return caps.FetchOutcome(url="https://walled.example/p", capability="fetch.crawl",
                             page=None, verdict=verdict,
                             har_entries=[{"status": 200}] if har else [])


@pytest.fixture
def fetch_seams(monkeypatch):
    class _Robots:
        async def is_allowed(self, url, ua):
            return True

    monkeypatch.setattr(caps, "get_robots_checker", lambda: _Robots())
    monkeypatch.setattr(caps, "_browser_latched", lambda: False)
    state = {"tier1": None, "browser": None, "queued_at_browser": None}

    async def _fake_tier1(url, goal, job_id, page_offset, on_progress):
        return state["tier1"]

    async def _fake_browser(url, goal, job_id, page_offset, on_progress):
        state["queued_at_browser"] = ps.stats()["blocked_queued"]
        return state["browser"]

    monkeypatch.setattr(caps, "_fast_http_fetch_one", _fake_tier1)
    monkeypatch.setattr(caps, "_browser_pool_fetch_one", _fake_browser)
    return state


def _fetch():
    return asyncio.run(caps.FetchCrawlCapability().fetch_one(
        "https://walled.example/p", "goal", "job-blocked"))


@pytest.mark.parametrize("browser_verdict,label", [(_OK, False), (_CHALLENGE, True)])
def test_page_blocked_is_asked_before_the_browser_and_labelled_by_it(
        harness, fetch_seams, browser_verdict, label):
    eng, rows = harness
    fetch_seams["tier1"] = _tier1(_CHALLENGE)
    fetch_seams["browser"] = _browser(browser_verdict)
    out = _fetch()
    _drain()
    # shadow only: the escalation still ran and its outcome is returned
    assert out is fetch_seams["browser"]
    # the consult was queued BEFORE the browser fetch started
    assert fetch_seams["queued_at_browser"] == 1
    calls = [c for c in eng.calls if c[0] == "page_blocked"]
    assert len(calls) == 1
    _cid, frame, thread_name = calls[0]
    assert thread_name == "iris-oracle_shadow"
    assert frame["url"] == "https://walled.example/p" and frame["status"] == "403"
    assert "verify you are human" in frame["page_head"]
    assert set(k for k, v in frame.items() if v) <= set(
        de.ORACLE_JOBS["inspect_page"].fields)
    assert len(rows) == 1
    r = rows[0]
    assert r["consumer_id"] == "page_blocked"
    assert r["criteria_version"] == "page_blocked/text-v1"
    assert r["outside_label"] is label and r["label_source"] == "outcome"
    assert r["input_key"] and r["state"] and r["turn_id"] == "turn-page-1"
    assert decision_label(None, {}, r) is (bool(r["chosen"]) == label)


def test_page_blocked_without_a_browser_request_stays_unlabelled(harness, fetch_seams):
    _eng, rows = harness
    fetch_seams["tier1"] = _tier1(_CHALLENGE)
    fetch_seams["browser"] = _browser(_CHALLENGE, har=False)
    _fetch()
    _drain()
    assert len(rows) == 1 and "outside_label" not in rows[0]
    assert rows[0]["unlabelled"] == "no_browser_request"


@pytest.mark.parametrize("verdict", [
    _OK,                                                        # usable: no escalation
    UsabilityVerdict(usable=False, reason=UsabilityReason.BLOCKED),  # parked, no browser
])
def test_page_blocked_is_not_asked_when_nothing_escalates(harness, fetch_seams, verdict):
    eng, rows = harness
    fetch_seams["tier1"] = _tier1(verdict)
    fetch_seams["browser"] = _browser(_OK)
    _fetch()
    _drain()
    assert [c for c in eng.calls if c[0] == "page_blocked"] == []
    assert rows == [] and fetch_seams["queued_at_browser"] is None


# -- declarations ---------------------------------------------------------------


def test_both_questions_are_declared_noul_shadow_only():
    for cid, job in (("page_relevance", "judge_page"), ("page_blocked", "inspect_page")):
        assert de.declared_type(cid) == "noul"
        assert cid in de.CONSUMERS and cid in de.NO_DECISION_SITE
        assert de.oracle_job(cid).name == job
        assert de.ORACLE_JOBS[job].image_fields == ()
