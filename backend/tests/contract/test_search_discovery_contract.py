"""CT-12 (REQ-19): vision-driven search-engine discovery.

Pins:
  - discovered URLs enter the NORMAL per-URL dispatch path (REQ-19 AC3) — the
    same `fetch.crawl` capability call site CT-8 / test_stealth_contract.py
    already pins as robots-checked on every call, so a discovered URL is
    robots-checked exactly like a planned one, by construction (no second
    fetch path is introduced, design D2/D4).
  - a search-engine CAPTCHA/bot-wall is PARKED and reported, never solved
    (REQ-19 AC5, Non-Requirements).
  - discovery attempts at most once per research run (REQ-19 AC7).
  - DOM extraction filters the engine's own domain / ads; the vision-read
    fallback only runs when DOM extraction yields nothing (REQ-19 AC2).

Hermetic: a fake BrowserSession + fake vision provider stand in for
Playwright and the VLM. No live web, no real vision server.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.crawler.capabilities import CAPABILITIES, FetchCrawlCapability, register_capability
from backend.crawler.crawl_planner import CrawlPlan
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.vision.browser_session import SessionBounds, VisionAction, WallKind
from backend.vision.search_discovery import (
    DiscoveryResult,
    click_discovered_result,
    discover_urls_via_vision,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fakes (mirror test_fetch_vision_contract.py's style)
# ═══════════════════════════════════════════════════════════════════════════

class _FakeDiscoverySession:
    """In-memory BrowserSession stand-in for discovery."""

    def __init__(self, job_id, url, goal, bounds=None):
        self.job_id = job_id
        self.url = url
        self.goal = goal
        self.bounds = bounds or SessionBounds()
        self.acts: list[VisionAction] = []
        self.closed = False
        self.available_flag = True
        self.wall_result = None
        self.settled_html = ""
        self.screenshot_bytes = b"PNG"

    async def open(self):
        pass

    def available(self):
        return self.available_flag

    async def act(self, action: VisionAction):
        self.acts.append(action)

    async def settle(self):
        return self.settled_html

    async def detect_wall(self):
        return self.wall_result

    async def screenshot(self):
        return self.screenshot_bytes

    async def close(self):
        self.closed = True


class _FakeProvider:
    def __init__(self, read_text_value="", analyze_value=""):
        self.read_text_value = read_text_value
        self.analyze_value = analyze_value
        self.read_text_calls = 0
        self.analyze_calls = 0

    def read_text(self, img_bytes):
        self.read_text_calls += 1
        return self.read_text_value

    def analyze_screen(self, img_bytes, question=""):
        self.analyze_calls += 1
        return self.analyze_value


_RESULTS_HTML = """
<html><body>
<div id="header"><a href="https://www.bing.com/">Home</a></div>
<li class="b-algo"><a href="https://real-source.example/article-one">Article One</a></li>
<li class="b-algo"><a href="https://real-source.example/article-two">Article Two</a></li>
<a href="https://doubleclick.net/ad?x=1">Sponsored</a>
</body></html>
"""


# ═══════════════════════════════════════════════════════════════════════════
# discover_urls_via_vision — DOM extraction + filtering (AC2)
# ═══════════════════════════════════════════════════════════════════════════

def test_discovery_extracts_and_filters_dom_results():
    """REQ-19 AC2: real result links kept; engine's own domain + ads dropped."""
    sess = _FakeDiscoverySession("j1", "https://www.bing.com/", "boss tower builds")
    sess.settled_html = _RESULTS_HTML

    result = asyncio.run(discover_urls_via_vision(
        "boss tower builds", "j1", session_cls=lambda *a, **k: sess,
    ))

    assert result.urls == [
        "https://real-source.example/article-one",
        "https://real-source.example/article-two",
    ]
    assert "https://www.bing.com/" not in result.urls
    assert not any("doubleclick.net" in u for u in result.urls)
    assert result.used_vision_fallback is False
    # AC2: type the query then submit — both actions performed.
    assert [a.kind for a in sess.acts] == ["type", "click"]
    assert sess.acts[0].value == "boss tower builds"
    assert sess.closed is True


def test_discovery_respects_max_results():
    """REQ-19 AC4: at most `max_results` candidate URLs returned."""
    html = "".join(
        f'<li class="b-algo"><a href="https://real-source.example/p{i}">p{i}</a></li>'
        for i in range(10)
    )
    sess = _FakeDiscoverySession("j2", "https://www.bing.com/", "q")
    sess.settled_html = html

    result = asyncio.run(discover_urls_via_vision(
        "q", "j2", session_cls=lambda *a, **k: sess, max_results=3,
    ))
    assert len(result.urls) == 3


def test_discovery_falls_back_to_vision_when_dom_yields_nothing():
    """REQ-19 AC2 fallback: DOM extraction empty -> vision read_text is asked."""
    sess = _FakeDiscoverySession("j3", "https://www.bing.com/", "q")
    sess.settled_html = "<html><body>no results found</body></html>"
    provider = _FakeProvider(read_text_value="See https://real-source.example/found for details.")

    result = asyncio.run(discover_urls_via_vision(
        "q", "j3", session_cls=lambda *a, **k: sess, provider=provider,
    ))

    assert result.urls == ["https://real-source.example/found"]
    assert result.used_vision_fallback is True
    assert provider.read_text_calls == 1, (
        "DOM extraction succeeded silently reusing a fixture — the fallback "
        "tier must only run when DOM extraction yields nothing"
    )


def test_discovery_does_not_call_vision_when_dom_succeeds():
    """The fallback tier (vision) must NOT run when the cheap DOM read
    already found results — vision is the fallback, not the default (AC2)."""
    sess = _FakeDiscoverySession("j4", "https://www.bing.com/", "q")
    sess.settled_html = _RESULTS_HTML
    provider = _FakeProvider(read_text_value="https://should-not-be-used.example/")

    result = asyncio.run(discover_urls_via_vision(
        "q", "j4", session_cls=lambda *a, **k: sess, provider=provider,
    ))

    assert provider.read_text_calls == 0
    assert "https://should-not-be-used.example/" not in result.urls


# ═══════════════════════════════════════════════════════════════════════════
# REQ-19 AC5: search-engine CAPTCHA is parked, NEVER solved
# ═══════════════════════════════════════════════════════════════════════════

def test_discovery_wall_on_search_engine_is_reported_not_solved():
    """A CAPTCHA on the SEARCH ENGINE itself must be surfaced as a wall, with
    zero URLs harvested — the module must never attempt to pass it."""
    sess = _FakeDiscoverySession("j5", "https://www.bing.com/", "q")
    sess.wall_result = WallKind.CAPTCHA
    sess.settled_html = _RESULTS_HTML  # even if content-shaped, wall wins

    result = asyncio.run(discover_urls_via_vision(
        "q", "j5", session_cls=lambda *a, **k: sess,
    ))

    assert result.wall == "captcha"
    assert result.urls == []
    # No action beyond type+submit — the module never probes further to
    # "solve" the wall.
    assert [a.kind for a in sess.acts] == ["type", "click"]


def test_orchestrator_parks_search_engine_wall_and_dispatches_nothing(monkeypatch):
    """CT-12: the orchestrator routes a discovery wall through the EXISTING
    `_park_source` (REQ-13) — one question raised, no fabricated URLs."""
    from backend.agent.tools.ask_user_tool import (
        get_parked_source_registry,
        reset_ask_user_tool_for_testing,
    )

    reset_ask_user_tool_for_testing()
    get_parked_source_registry().clear()

    async def _fake_discover(query, job_id, _emit=None, **kw):
        return DiscoveryResult(wall="captcha", engine_url="https://www.bing.com/")

    import backend.vision.search_discovery as sd_mod
    monkeypatch.setattr(sd_mod, "discover_urls_via_vision", _fake_discover)

    orch = CrawlOrchestrator()
    urls = asyncio.run(orch._discover_urls_via_vision("q", "run-captcha", lambda *a: None))

    assert urls == [], "a walled search engine must never yield fabricated URLs"
    parked = get_parked_source_registry().pending("run-captcha")
    assert len(parked) == 1
    assert parked[0].wall_kind == "captcha"
    reset_ask_user_tool_for_testing()
    get_parked_source_registry().clear()


# ═══════════════════════════════════════════════════════════════════════════
# click_discovered_result — the "click a specific result" ask
# ═══════════════════════════════════════════════════════════════════════════

def test_click_discovered_result_clicks_and_settles():
    sess = _FakeDiscoverySession("j6", "https://www.bing.com/", "q")
    sess.settled_html = "<html><body>destination page</body></html>"

    dom = asyncio.run(click_discovered_result(sess, "https://real-source.example/article-one"))

    assert "destination page" in dom
    assert sess.acts and sess.acts[0].kind == "click"
    assert sess.acts[0].target == "a[href='https://real-source.example/article-one']"


def test_click_discovered_result_never_raises_on_failure():
    class _BrokenSession(_FakeDiscoverySession):
        async def act(self, action):
            raise RuntimeError("element not found")

    sess = _BrokenSession("j7", "https://www.bing.com/", "q")
    dom = asyncio.run(click_discovered_result(sess, "https://real-source.example/x"))
    assert dom == ""


# ═══════════════════════════════════════════════════════════════════════════
# REQ-19 AC3: discovered URLs enter the NORMAL dispatch path
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clean_registry():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


def _page(url, markdown="", error=None):
    return PageData(
        url=url, title="t", markdown=markdown, html=None,
        metadata={}, error=error, html_bytes=len(markdown or ""),
    )


def test_discovered_urls_reach_the_real_fetch_crawl_capability(monkeypatch):
    """REQ-19 AC3: discovered URLs are dispatched through the REAL
    `FetchCrawlCapability` — the exact call site
    (`CrawlOrchestrator.fetch_url`) test_stealth_contract.py's
    `test_robots_gate_still_consulted_before_every_fetch` pins as
    robots-checked on every call. No second/bypassing fetch path exists for
    discovered URLs (design D2/D4) — proven by construction: the SAME
    capability instance planned URLs would use is the one invoked here.
    """
    register_capability(FetchCrawlCapability())  # the REAL capability, not a fake

    fetch_url_calls: list[str] = []

    import backend.crawler.orchestrator as orch_mod

    async def _fake_fetch_url(self_or_none, url, **kwargs):
        fetch_url_calls.append(url)
        return CrawlResult(
            query=url, pages=[_page(url, "")],  # unusable -> still proves reach
            duration_ms=1, crawled_at="", error=None,
        )

    monkeypatch.setattr(orch_mod.CrawlOrchestrator, "fetch_url", _fake_fetch_url)

    orch = CrawlOrchestrator()
    orch._backend_override = None  # force the T12 capability dispatch path

    async def _empty_plan(q):
        return CrawlPlan(urls=[], instructions="", result_type="mixed", title="t")

    monkeypatch.setattr(orch, "_plan", _empty_plan)

    async def _fake_discover(query, job_id, _emit=None, **kw):
        return DiscoveryResult(urls=[
            "https://real-source.example/one", "https://real-source.example/two",
        ])

    import backend.vision.search_discovery as sd_mod
    monkeypatch.setattr(sd_mod, "discover_urls_via_vision", _fake_discover)

    import backend.crawler.source_registry as sr_mod

    async def _no_history(query, quick=False):
        return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    sr_mod.get_source_registry = lambda: type("R", (), {"resolve": _no_history})()

    result = asyncio.run(orch.research("obscure niche query", mode="agent"))

    assert set(fetch_url_calls) == {
        "https://real-source.example/one", "https://real-source.example/two",
    }, "discovered URLs never reached the real fetch.crawl -> fetch_url call site"


def test_stamp_discovery_provenance_marks_only_discovered_urls():
    """REQ-19 AC6: only vision-discovered URLs are stamped
    `url_origin=vision_discovered`; planner-supplied URLs are untouched —
    provenance follows the same `page.metadata` pattern `_stamp_evidence`
    already uses for `content_origin` (REQ-18 AC2)."""
    fetched = CrawlResult(
        query="q",
        pages=[_page("https://real-source.example/one"), _page("https://planned.example/x")],
        duration_ms=1, crawled_at="",
    )
    CrawlOrchestrator._stamp_discovery_provenance(fetched, {"https://real-source.example/one"})
    by_url = {p.url: p for p in fetched.pages}
    assert by_url["https://real-source.example/one"].metadata["url_origin"] == "vision_discovered"
    assert "url_origin" not in by_url["https://planned.example/x"].metadata


def test_discovery_runs_at_most_once_per_run(monkeypatch):
    """REQ-19 AC7: even when BOTH the initial plan AND the broadened re-plan
    come back empty, discovery is attempted exactly once."""
    register_capability(FetchCrawlCapability())

    import backend.crawler.orchestrator as orch_mod

    async def _fake_fetch_url(self_or_none, url, **kwargs):
        return CrawlResult(query=url, pages=[_page(url, "")], duration_ms=1, crawled_at="", error=None)

    monkeypatch.setattr(orch_mod.CrawlOrchestrator, "fetch_url", _fake_fetch_url)

    orch = CrawlOrchestrator()
    orch._backend_override = None

    async def _always_empty_plan(q):
        return CrawlPlan(urls=[], instructions="", result_type="mixed", title="t")

    monkeypatch.setattr(orch, "_plan", _always_empty_plan)

    discovery_calls = []

    async def _fake_discover(query, job_id, _emit=None, **kw):
        discovery_calls.append(query)
        return DiscoveryResult(urls=["https://real-source.example/x"])

    import backend.vision.search_discovery as sd_mod
    monkeypatch.setattr(sd_mod, "discover_urls_via_vision", _fake_discover)

    import backend.crawler.source_registry as sr_mod

    async def _no_history(query, quick=False):
        return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    sr_mod.get_source_registry = lambda: type("R", (), {"resolve": _no_history})()

    asyncio.run(orch.research("q", mode="agent"))

    assert len(discovery_calls) == 1, (
        f"discovery ran {len(discovery_calls)}x — REQ-19 AC7 bounds it to once per run"
    )
