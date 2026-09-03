"""REQ-16 (T27) contract pins: open_url is in-app and never touches the desktop.

Covers:
  - URL normalization (missing scheme -> https://).
  - The in-app surface: an ``open_tab`` WS message (tab_type "browser", the
    url) is broadcast to the session's clients — the existing dashboard
    browser tab renders it with zero dashboard changes.
  - Agent content: the single page is fetched headlessly (CrawlOrchestrator
    single-URL path, no LLM planning) and returned as markdown + sources —
    the same envelope shape as ``search`` so the DER render path works.
  - Dispatch: ``execute_tool`` routes open_url to ``_execute_open_url``
    BEFORE the MCP dispatch table — ``execute_mcp_tool`` is never reached,
    so ``BrowserServer.execute_tool -> webbrowser.open`` is unreachable for
    open_url (the OS browser is never hijacked).
  - Error paths: missing url / fetch failure return honest envelopes.

The crawl and the WS manager are deterministic seams (no live web).
"""

import asyncio

import pytest

from backend.agent.tool_bridge import AgentToolBridge
from backend.crawler.orchestrator import CrawlOrchestrator


# ── fakes ─────────────────────────────────────────────────────────────────


class _FakePage:
    def __init__(self, url, markdown, error=None):
        self.url = url
        self.markdown = markdown
        self.error = error


class _FakeCrawlResult:
    def __init__(self, pages=None, error=None):
        self.pages = pages or []
        self.error = error


class _FakeWS:
    def __init__(self, clients=("c1",)):
        self.clients = list(clients)
        self.broadcasts = []

    def get_clients_for_session(self, session_id):
        return self.clients

    async def broadcast_to_session(self, session_id, message):
        self.broadcasts.append((session_id, message))


@pytest.fixture(autouse=True)
def _permissive_gates(monkeypatch):
    """Same permissive gate env as test_tool_bridge_gates (deterministic)."""
    import backend.agent.tool_registry as r
    import backend.capabilities as caps

    monkeypatch.setattr(r, "_internet_provider", lambda: True)
    monkeypatch.setattr(r, "_desktop_provider", lambda: True)
    monkeypatch.setattr(caps.CapabilitySet, "is_tool_allowed", staticmethod(lambda name: True))
    yield


def _patch_crawl(monkeypatch, result):
    async def fake_fetch_url(self, url, **kwargs):
        fake_fetch_url.called_url = url
        return result

    fake_fetch_url.called_url = None
    monkeypatch.setattr(CrawlOrchestrator, "fetch_url", fake_fetch_url)
    return fake_fetch_url


# ── in-app behavior ───────────────────────────────────────────────────────


def test_open_url_normalizes_and_returns_content(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr("backend.ws_manager.get_websocket_manager", lambda: ws)
    _patch_crawl(
        monkeypatch,
        _FakeCrawlResult(pages=[_FakePage("https://example.com/page", "# Title\n\nBody")]),
    )

    result = asyncio.run(
        AgentToolBridge()._execute_open_url({"url": "example.com/page"}, "s1")
    )

    assert result["success"] is True
    assert result["url"] == "https://example.com/page"  # scheme normalized
    assert "Body" in result["content"]
    assert result["sources"] == ["https://example.com/page"]
    assert result["trust"] == "untrusted"  # external content → reference zone


def test_open_url_fetches_the_normalized_url(monkeypatch):
    monkeypatch.setattr("backend.ws_manager.get_websocket_manager", lambda: _FakeWS())
    fake = _patch_crawl(
        monkeypatch, _FakeCrawlResult(pages=[_FakePage("https://example.com/x", "content")])
    )

    asyncio.run(AgentToolBridge()._execute_open_url({"url": "example.com/x"}, "s1"))

    assert fake.called_url == "https://example.com/x"  # no LLM planning path


def test_open_url_broadcasts_in_app_tab(monkeypatch):
    ws = _FakeWS(clients=("c1", "c2"))
    monkeypatch.setattr("backend.ws_manager.get_websocket_manager", lambda: ws)
    _patch_crawl(
        monkeypatch, _FakeCrawlResult(pages=[_FakePage("https://example.com/x", "content")])
    )

    asyncio.run(AgentToolBridge()._execute_open_url({"url": "https://example.com/x"}, "s1"))

    assert len(ws.broadcasts) == 1
    sid, msg = ws.broadcasts[0]
    assert sid == "s1"
    assert msg["type"] == "open_tab"
    assert msg["tab_type"] == "browser"  # the dashboard's existing browser tab
    assert msg["url"] == "https://example.com/x"
    assert msg["title"] == "https://example.com/x"
    assert msg["id"]


def test_open_url_without_clients_skips_broadcast_but_still_succeeds(monkeypatch):
    ws = _FakeWS(clients=())
    monkeypatch.setattr("backend.ws_manager.get_websocket_manager", lambda: ws)
    _patch_crawl(
        monkeypatch, _FakeCrawlResult(pages=[_FakePage("https://example.com/x", "content")])
    )

    result = asyncio.run(
        AgentToolBridge()._execute_open_url({"url": "https://example.com/x"}, "s1")
    )

    assert result["success"] is True  # headless fetch still serves the agent
    assert ws.broadcasts == []


# ── dispatch: never reaches the MCP table / desktop browser ───────────────


def test_execute_tool_routes_open_url_before_mcp_dispatch(monkeypatch):
    bridge = AgentToolBridge()
    captured = {}

    async def fake_open_url(params, sid):
        captured["params"] = params
        return {"success": True, "fake": True}

    async def boom(*args, **kwargs):
        raise AssertionError("open_url must never reach the MCP dispatch table")

    monkeypatch.setattr(bridge, "_execute_open_url", fake_open_url)
    monkeypatch.setattr(bridge, "execute_mcp_tool", boom)

    result = asyncio.run(bridge.execute_tool("open_url", {"url": "example.com"}, "s1"))

    assert result == {"success": True, "fake": True}
    assert captured["params"] == {"url": "example.com"}


# ── error envelopes ───────────────────────────────────────────────────────


def test_open_url_missing_url():
    result = asyncio.run(AgentToolBridge()._execute_open_url({}, "s1"))
    assert result["success"] is False
    assert "url" in result["error"]


def test_open_url_fetch_error_returns_honest_envelope(monkeypatch):
    monkeypatch.setattr("backend.ws_manager.get_websocket_manager", lambda: _FakeWS())
    _patch_crawl(monkeypatch, _FakeCrawlResult(error="connection refused"))

    result = asyncio.run(
        AgentToolBridge()._execute_open_url({"url": "https://example.com/x"}, "s1")
    )

    assert result["success"] is False
    assert result["error"] == "connection refused"
