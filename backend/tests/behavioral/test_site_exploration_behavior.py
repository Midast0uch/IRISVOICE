"""Behavioral: the agent explores the relevant pages of one site, and only those
(specs/research-memory-chain-browser W3, REQ-6).

  * crawl: when the kept passages are too few for a site that produced relevant ones,
    ONE hop fetches that site's most goal-relevant same-site links - not the
    irrelevant ones, not other sites, not log-out links - bounded in links and in
    time; with enough kept passages there is no hop;
  * browser_explore: on a real Chromium against a local multi-page site, the
    goal-relevant subpages are read and the irrelevant ones are never requested;
    the page bound and the time bound hold.

The crawl half drives the real orchestrator funnel (split -> credibility -> rerank ->
hop -> rerank) over an in-memory site served by a stub FetchBackend (the Tier-1 fetch
needs the crawl4ai subprocess); rerank is BM25-only. The browser half uses no stubs
except the egress guard (it correctly refuses the loopback fixture).
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import threading
import time

import pytest

from backend.agent.tools import browser_tools
from backend.crawler import capture_store
from backend.crawler import orchestrator as orch_mod
from backend.crawler.crawl_planner import CrawlPlan
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator, FetchBackend

# ── crawl: the same-site hop ───────────────────────────────────────────────

_SITE = "https://shop.test"
_ABOUT_TEXT = "About our company history and the people who work here every day."


def _page(path: str, text: str) -> PageData:
    return PageData(url=_SITE + path, title=path, markdown=text, html="", metadata={})


_INDEX_LINKS = (
    "[Pricing plans](https://shop.test/pricing) [Enterprise plans](/plans/enterprise) "
    "[About us](/about) [Our team](/team) [Log out](/logout) "
    "[Other pricing plans](https://other.test/pricing)"
)
_INDEX = _page("/", "Shop pricing plans overview: every pricing plan cost is listed. " + _INDEX_LINKS)
_PAGES = {
    "/pricing": _page("/pricing", "Pricing plans cost from ten dollars; each pricing plan cost is listed here."),
    "/plans/enterprise": _page("/plans/enterprise", "Enterprise pricing plans cost are quoted per seat; plan cost varies."),
    "/about": _page("/about", _ABOUT_TEXT),
    "/team": _page("/team", _ABOUT_TEXT),
}


class _SiteBackend(FetchBackend):
    """Serves the in-memory site; records every fetch's URLs."""

    def __init__(self, first_pages, delay: float = 0.0):
        self.first_pages = first_pages
        self.fetches: list = []
        self._delay = delay

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kwargs):
        self.fetches.append(list(urls))
        if len(self.fetches) == 1:
            pages = self.first_pages
        else:
            if self._delay:
                await asyncio.sleep(self._delay)
            pages = [_PAGES[u[len(_SITE):]] for u in urls if u[len(_SITE):] in _PAGES]
        return CrawlResult(query=query, pages=pages, duration_ms=5, crawled_at="2026-01-01T00:00:00+00:00")


class _Planner:
    def __init__(self, urls):
        self._urls = urls

    async def plan(self, query):
        return CrawlPlan(urls=self._urls, instructions="facts", result_type="mixed", title="T")


@pytest.fixture(autouse=True)
def _bm25_only(monkeypatch):
    monkeypatch.setattr("backend.crawler.rerank._embed", lambda texts, deadline=None: None)


def _research(backend, first_urls, query="shop pricing plans cost"):
    orch = CrawlOrchestrator(planner=_Planner(first_urls))
    orch._backend_override = backend

    async def _noop(*_a, **_k):
        return None

    orch._learn_from_crawl = _noop
    orch._apply_har_penalties = lambda *a, **k: None
    return asyncio.run(orch.research(query, mode="agent", session_id="", on_progress=lambda _p: None, max_pages=5))


def test_a_thin_result_hops_to_the_relevant_same_site_links_only():
    backend = _SiteBackend([_INDEX])
    result = _research(backend, [_SITE + "/"])

    assert len(backend.fetches) == 2, "one hop, not more (depth 1)"
    assert set(backend.fetches[1]) == {_SITE + "/pricing", _SITE + "/plans/enterprise"}, backend.fetches[1]
    assert len(backend.fetches[1]) <= orch_mod._HOP_MAX_LINKS
    kept_urls = {p.url for p in result.passages}
    assert _SITE + "/pricing" in kept_urls and _SITE + "/plans/enterprise" in kept_urls
    assert not result.error


def test_the_hop_never_leaves_the_site_or_follows_acting_links():
    backend = _SiteBackend([_INDEX])
    _research(backend, [_SITE + "/"])
    hopped = " ".join(backend.fetches[1])
    for forbidden in ("other.test", "/logout", "/about", "/team"):
        assert forbidden not in hopped, forbidden


def test_enough_kept_passages_means_no_hop():
    relevant = [
        _page(f"/r{i}", f"Shop pricing plans cost guide number {i}: the pricing plan cost is explained in detail.")
        for i in range(orch_mod._HOP_MIN_KEPT)
    ]
    backend = _SiteBackend(relevant)
    result = _research(backend, [p.url for p in relevant])
    assert len(backend.fetches) == 1, "the kept passages were enough; no hop"
    assert len(result.passages) >= orch_mod._HOP_MIN_KEPT


def test_the_hop_is_bounded_in_links():
    many = "".join(f" [Pricing plans {i}](/plans/p{i})" for i in range(12))
    backend = _SiteBackend([_page("/", "Shop pricing plans cost overview." + many)])
    orch_pages = {f"/plans/p{i}": _page(f"/plans/p{i}", "Pricing plans cost details.") for i in range(12)}
    _PAGES.update(orch_pages)
    try:
        _research(backend, [_SITE + "/"])
    finally:
        for key in orch_pages:
            _PAGES.pop(key, None)
    assert len(backend.fetches) == 2 and len(backend.fetches[1]) == orch_mod._HOP_MAX_LINKS


def test_a_slow_hop_is_cut_at_its_time_bound_and_the_crawl_still_answers(monkeypatch):
    monkeypatch.setattr(orch_mod, "_HOP_BUDGET_S", 0.2)
    backend = _SiteBackend([_INDEX], delay=30.0)
    t0 = time.monotonic()
    result = _research(backend, [_SITE + "/"])
    assert time.monotonic() - t0 < 10.0, "the hop outran its bound"
    assert not result.error and result.passages, "the first page's passages still answer"
    assert {p.url for p in result.passages} == {_SITE + "/"}


# ── browser_explore on a real Chromium ─────────────────────────────────────

_NAV = (
    "<nav><a href='/pricing'>Pricing plans</a> <a href='/plans/pro'>Pro</a> "
    "<a href='/plans/team'>Team</a> <a href='/plans'>Plans</a> <a href='/about'>About us</a> "
    "<a href='/careers'>Careers</a> <a href='/logout'>Log out</a> "
    "<a href='http://localhost:1/pricing'>Elsewhere pricing plans</a></nav>"
)
_BODIES = {
    "/": "Welcome to the shop home page.",
    "/pricing": "Pricing plans start at ten dollars per month for the basic plan with every feature included.",
    "/plans/pro": "The pro plan costs twenty dollars per month and adds priority support for all teams.",
    "/plans/team": "The team plan costs fifty dollars per month and adds shared workspaces for the whole team.",
    "/plans": "All plans are listed on this slow overview page that takes a long time to load.",
    "/about": "About the company: a long history of making things that people use every day.",
    "/careers": "Careers: we are hiring engineers and designers to work with us this year.",
}


class _SiteHandler(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):  # noqa: N802 - http.server API
        path = self.path.split("?")[0]
        _SiteHandler.hits.append(path)
        if path == "/plans":
            time.sleep(4.0)  # the page that blows the time bound
        text = _BODIES.get(path, "Not found.")
        body = f"<!doctype html><html><head><title>{path}</title></head><body>{_NAV}<main><p>{text}</p></main></body></html>"
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_a):
        pass


@pytest.fixture(scope="module")
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SiteHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def explorer(site, monkeypatch, tmp_path):
    async def _ok(_url):
        return ""

    monkeypatch.setattr(browser_tools, "_egress_error", _ok)
    monkeypatch.setattr(capture_store, "_store", capture_store.CaptureStore(root=str(tmp_path)))
    _SiteHandler.hits.clear()
    return f"conv-explore-{time.monotonic_ns()}"


@pytest.fixture
async def conv(explorer, site):
    assert (await browser_tools.browser_open(explorer, site + "/", None))["success"]
    _SiteHandler.hits.clear()  # only what browser_explore itself requests counts
    yield explorer
    await browser_tools.close_conversation_browser(explorer)


async def test_browser_explore_reads_the_relevant_subpages_and_not_the_others(conv, site, monkeypatch):
    monkeypatch.setattr(browser_tools, "_EXPLORE_TIMEOUT_S", 20.0)
    res = await browser_tools.browser_explore(conv, "pricing plans cost per month", 5)

    assert res["success"], res
    urls = {p["url"].replace(site, "") for p in res["pages"]}
    assert {"/pricing", "/plans/pro", "/plans/team"} <= urls, urls
    assert not urls & {"/about", "/careers", "/logout"}
    assert not set(_SiteHandler.hits) & {"/about", "/careers", "/logout"}, _SiteHandler.hits
    pricing = next(p for p in res["pages"] if p["url"].endswith("/pricing"))
    assert "ten dollars" in pricing["passage"] and len(pricing["passage"]) <= browser_tools._EXPLORE_PASSAGE_CHARS
    assert res["trust"] == "untrusted"


async def test_browser_explore_page_bound(conv, monkeypatch):
    monkeypatch.setattr(browser_tools, "_EXPLORE_TIMEOUT_S", 20.0)
    res = await browser_tools.browser_explore(conv, "pricing plans cost per month", 2)
    assert res["success"] and len(res["pages"]) == 2
    assert len({h for h in _SiteHandler.hits if h in ("/pricing", "/plans/pro", "/plans/team", "/plans")}) <= 2


async def test_browser_explore_time_bound_returns_what_it_has(conv, monkeypatch):
    """The slow overview page (4 s) is first in rank; the 2 s bound cuts it and the
    call returns inside the bound instead of waiting for it."""
    monkeypatch.setattr(browser_tools, "_EXPLORE_TIMEOUT_S", 2.0)
    t0 = time.monotonic()
    res = await browser_tools.browser_explore(conv, "plans", 5)
    assert time.monotonic() - t0 < 6.0, "browser_explore outran its time bound"
    assert res["success"] and res["pages"] == []


async def test_browser_explore_without_a_session_says_so():
    res = await browser_tools.browser_explore("no-such-conversation", "pricing", 3)
    assert res["success"] is False and "browser_open" in res["error"]
