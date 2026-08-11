"""Contract tests for T11 (REQ-5): stealth headers, run-scoped cookie jar,
randomised delay — WITHOUT weakening robots_checker (REQ-5 AC3, CT-8).

Hermetic: crawl4ai is mocked at the import/launch seam; no live browser.
"""

import asyncio
from unittest import mock

from backend.crawler import crawler_engine as ce
from backend.crawler.crawler_engine import RunCookieJar, _jittered_delay_ms


# ---------------------------------------------------------------------------
# Stealth headers applied at BrowserConfig level (the ONLY supported seam)
# ---------------------------------------------------------------------------

def test_stealth_headers_passed_to_browser_config():
    """_STEALTH_EXTRA_HEADERS reach BrowserConfig at launch (REQ-5 AC2)."""

    captured = {}

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeCrawler:
        def __init__(self, config=None):
            captured["config"] = config

        async def start(self):
            pass

        async def close(self):
            pass

    fake_crawl4ai = mock.Mock()
    fake_crawl4ai.AsyncWebCrawler = FakeCrawler
    fake_crawl4ai.BrowserConfig = FakeBrowserConfig

    engine = ce.CrawlerEngine()

    async def run():
        with mock.patch.dict("sys.modules", {"crawl4ai": fake_crawl4ai}):
            async with engine:
                pass

    asyncio.run(run())
    assert "headers" in captured
    assert captured["headers"] == dict(ce._STEALTH_EXTRA_HEADERS)


def test_headers_not_passed_to_run_config():
    """CrawlerRunConfig must NOT receive headers (would raise TypeError)."""
    import inspect

    from crawl4ai import CrawlerRunConfig  # real lib, param check only

    sig = inspect.signature(CrawlerRunConfig.__init__)
    assert "headers" not in sig.parameters


# ---------------------------------------------------------------------------
# Run-scoped cookie jar
# ---------------------------------------------------------------------------

def test_cookie_jar_scopes_to_domain():
    jar = RunCookieJar("job-1")
    jar.record_set_cookie("https://a.example/page", {"Set-Cookie": "sid=abc; Path=/"})
    jar.record_set_cookie("https://b.example/page", {"Set-Cookie": "tok=xyz; Path=/"})
    assert len(jar.domain_cookies("https://a.example/x")) == 1
    assert jar.domain_cookies("https://a.example/x")[0]["value"] == "abc"
    assert len(jar.domain_cookies("https://b.example/x")) == 1
    assert len(jar.domain_cookies("https://c.example/x")) == 0


def test_cookie_jar_ignores_non_set_cookie_headers():
    jar = RunCookieJar("job-1")
    jar.record_set_cookie("https://a.example/", {"Content-Type": "text/html"})
    assert jar.is_empty


def test_cookie_jar_never_raises_on_bad_input():
    jar = RunCookieJar("job-1")
    jar.record_set_cookie("https://a.example/", None)  # no headers
    jar.record_set_cookie("https://a.example/", {"Set-Cookie": None})  # empty value
    jar.record_set_cookie("not a url", {"Set-Cookie": "a=b"})  # parse failure path
    assert jar.is_empty is False or jar.is_empty is True  # never raised


def test_cookie_jar_clear_is_full_reset():
    jar = RunCookieJar("job-1")
    jar.record_set_cookie("https://a.example/", {"Set-Cookie": "sid=abc"})
    assert not jar.is_empty
    jar.clear()
    assert jar.is_empty


def test_cookie_jar_is_run_scoped_instance_state():
    """Two jars (two runs) share nothing — no cross-run identity (REQ-5)."""
    jar_a = RunCookieJar("job-a")
    jar_b = RunCookieJar("job-b")
    jar_a.record_set_cookie("https://a.example/", {"Set-Cookie": "sid=abc"})
    assert jar_b.is_empty  # run B never sees run A's cookies


# ---------------------------------------------------------------------------
# Randomised delay (jitter)
# ---------------------------------------------------------------------------

def test_jittered_delay_within_range():
    base = 1000.0
    lo = base * (1 - ce._DELAY_JITTER)
    hi = base * (1 + ce._DELAY_JITTER)
    for _ in range(200):
        d = _jittered_delay_ms(1000)
        assert lo <= d <= hi


def test_jittered_delay_respects_zero_jitter():
    assert _jittered_delay_ms(500, jitter=0.0) == 500.0


# ---------------------------------------------------------------------------
# Robots checker NOT weakened (REQ-5 AC3 / CT-8)
# ---------------------------------------------------------------------------

def test_robots_gate_still_consulted_before_every_fetch():
    """The crawl loop still asks robots.is_allowed per URL (CT-8 pin)."""

    calls = []

    class FakeRobots:
        async def is_allowed(self, url, ua):
            calls.append((url, ua))
            return True

    class FakeResult:
        status_code = 200
        response_headers = {}
        markdown_v2 = None
        markdown = "some markdown " * 30
        metadata = {"title": "T"}
        html = "<html>ok</html>"

    class FakeCrawler:
        def __init__(self, config=None):
            pass

        async def start(self):
            pass

        async def close(self):
            pass

        async def arun(self, url, config):
            return FakeResult()

    fake_crawl4ai = mock.Mock()
    fake_crawl4ai.AsyncWebCrawler = FakeCrawler
    fake_crawl4ai.BrowserConfig = lambda **kw: mock.Mock()
    fake_crawl4ai.CrawlerRunConfig = lambda **kw: mock.Mock()
    fake_crawl4ai.content_filter_strategy = mock.Mock()
    fake_crawl4ai.markdown_generation_strategy = mock.Mock()

    engine = ce.CrawlerEngine()

    async def run():
        with mock.patch.dict("sys.modules", {"crawl4ai": fake_crawl4ai}), \
             mock.patch("backend.crawler.crawler_engine.get_robots_checker", return_value=FakeRobots()):
            async with engine:
                await engine.crawl("q", ["https://a.example/1", "https://b.example/2"], "instr", max_pages=2, delay_ms=0)

    asyncio.run(run())
    assert len(calls) == 2
    assert calls[0][0] == "https://a.example/1"
    assert calls[1][0] == "https://b.example/2"
