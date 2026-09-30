"""Spec A2 (websearch-vision-browser, REQ-2 AC2.1-2.3, RC1): policy UA, 403 = blocked,
bounded Tier-2 setup.

Pins:
- Tier-1 and robots.txt send the policy User-Agent, not a generic browser UA.
- A bare 401/403 (no challenge markers) is ``blocked``; Tier 2 (the browser) is NOT called.
- A page WITH challenge markers is still ``challenge`` and still escalates (unchanged).
- A blocked URL is parked AND recorded with ``record_wall()`` so the next run skips it.
- A hanging ``new_context`` returns inside its bound (a wedged browser no longer holds the
  URL until the whole run budget cuts it).

Hermetic: httpx is mocked (pytest_httpx); the browser pool is a stub. No live web.
"""
from __future__ import annotations

import asyncio
import time

from pytest_httpx import HTTPXMock

from backend.crawler import capabilities as caps
from backend.crawler.robots_checker import RobotsChecker
from backend.crawler.usability import UsabilityReason

_URL = "https://walled.example/page"


class _AllowAll:
    async def is_allowed(self, url, ua=""):
        return True


def _stub_tier2(monkeypatch):
    """Replace Tier 2 with a recorder; returns the list of URLs it was called for."""
    calls: list[str] = []

    async def _tier2(url, goal, job_id, page_offset, on_progress):
        calls.append(url)
        return caps.FetchOutcome(
            url=url, capability="fetch.crawl", page=None,
            verdict=caps._unusable_verdict(detail="tier2 stub"),
        )

    monkeypatch.setattr(caps, "get_robots_checker", lambda: _AllowAll())
    monkeypatch.setattr(caps, "_browser_pool_fetch_one", _tier2)
    monkeypatch.setattr(caps, "_BROWSER_UNAVAILABLE_UNTIL", 0.0)
    return calls


def test_bare_403_is_blocked_and_never_reaches_the_browser(monkeypatch, httpx_mock: HTTPXMock):
    tier2_calls = _stub_tier2(monkeypatch)
    httpx_mock.add_response(status_code=403, text="<html><body>Forbidden</body></html>")

    outcome = asyncio.run(caps.FetchCrawlCapability().fetch_one(_URL, "goal", "j-blocked"))

    assert outcome.verdict.usable is False
    assert outcome.verdict.reason == UsabilityReason.BLOCKED
    assert tier2_calls == [], "a bare 403 escalated to the browser"
    assert outcome.har_entries[0]["status"] == 403
    assert outcome.har_entries[0]["error"] == "blocked"


def test_bare_401_is_blocked(monkeypatch, httpx_mock: HTTPXMock):
    tier2_calls = _stub_tier2(monkeypatch)
    httpx_mock.add_response(status_code=401, text="<html><body>Unauthorized</body></html>")

    outcome = asyncio.run(caps.FetchCrawlCapability().fetch_one(_URL, "goal", "j-401"))

    assert outcome.verdict.reason == UsabilityReason.BLOCKED
    assert tier2_calls == []


def test_challenge_marker_page_is_still_challenge_and_escalates(monkeypatch, httpx_mock: HTTPXMock):
    """Unchanged behavior: markers -> challenge -> Tier 2 is tried."""
    tier2_calls = _stub_tier2(monkeypatch)
    httpx_mock.add_response(
        status_code=403,
        text="<html><head><title>Just a moment...</title></head>"
             "<body><div id='cf-chl-widget'></div></body></html>",
    )

    outcome = asyncio.run(caps.FetchCrawlCapability().fetch_one(_URL, "goal", "j-chal"))

    assert tier2_calls == [_URL]
    # the Tier-2 stub's verdict is returned; the Tier-1 verdict it escalated from was CHALLENGE
    assert outcome.verdict.detail == "tier2 stub"


def test_tier1_sends_the_policy_user_agent(monkeypatch, httpx_mock: HTTPXMock):
    _stub_tier2(monkeypatch)
    httpx_mock.add_response(status_code=403, text="no")

    asyncio.run(caps.FetchCrawlCapability().fetch_one(_URL, "goal", "j-ua"))

    ua = httpx_mock.get_request().headers["user-agent"]
    assert ua == caps._TIER1_USER_AGENT
    assert ua.startswith("IRISVoice/") and "github.com/Midast0uch/IRISVOICE" in ua
    assert "Mozilla" not in ua


def test_robots_txt_fetch_sends_the_caller_user_agent(httpx_mock: HTTPXMock):
    httpx_mock.add_response(text="User-agent: *\nAllow: /\n")

    allowed = asyncio.run(
        RobotsChecker().is_allowed("https://example.org/a", caps._TIER1_USER_AGENT)
    )

    assert allowed is True
    req = httpx_mock.get_request()
    assert req.url.path == "/robots.txt"
    assert req.headers["user-agent"] == caps._TIER1_USER_AGENT


def test_blocked_url_is_parked_and_recorded_as_a_wall():
    """AC2.2: parking a blocked URL calls record_wall() so the next run skips the domain."""
    from backend.agent.tool_errors import is_walled, reset_wall_ledger_for_testing
    from backend.crawler.orchestrator import CrawlOrchestrator

    reset_wall_ledger_for_testing()
    try:
        assert is_walled("walled.example") is False
        orch = CrawlOrchestrator()
        orch._park_source("run-blocked", _URL, "blocked", lambda *a, **k: None)
        assert is_walled("walled.example") is True
        assert ("walled.example", "blocked") in orch._parks_by_job["run-blocked"]
    finally:
        reset_wall_ledger_for_testing()


def test_hanging_new_context_returns_within_its_bound(monkeypatch):
    """AC2.3: a wedged ``new_context`` must not hold the URL past the step bound."""
    released: list[bool] = []

    class _Lease:
        def release(self):
            released.append(True)

    class _HangingBrowser:
        async def new_context(self):
            await asyncio.sleep(3600)

    async def _acquire(max_lease_ms=0.0):
        return _HangingBrowser(), _Lease()

    monkeypatch.setattr("backend.vision.browser_pool.acquire_browser", _acquire)
    monkeypatch.setattr(caps, "_TIER2_STEP_TIMEOUT_S", 0.3)

    t0 = time.monotonic()
    outcome = asyncio.run(caps._browser_pool_fetch_one(_URL, "goal", "j-hang", 0, None))
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, f"new_context hang was not bounded ({elapsed:.1f}s)"
    assert outcome.page is None and outcome.verdict.usable is False
    assert released == [True], "the pool lease leaked after a bounded timeout"


def test_hanging_new_page_returns_within_its_bound_and_closes_the_context(monkeypatch):
    closed: list[bool] = []

    class _Lease:
        def release(self):
            pass

    class _Ctx:
        async def new_page(self):
            await asyncio.sleep(3600)

        async def close(self):
            closed.append(True)

    class _Browser:
        async def new_context(self):
            return _Ctx()

    async def _acquire(max_lease_ms=0.0):
        return _Browser(), _Lease()

    monkeypatch.setattr("backend.vision.browser_pool.acquire_browser", _acquire)
    monkeypatch.setattr(caps, "_TIER2_STEP_TIMEOUT_S", 0.3)

    t0 = time.monotonic()
    outcome = asyncio.run(caps._browser_pool_fetch_one(_URL, "goal", "j-hang2", 0, None))

    assert time.monotonic() - t0 < 2.0
    assert outcome.verdict.usable is False
    assert closed == [True], "the isolated context leaked after a bounded timeout"
