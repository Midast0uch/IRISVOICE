"""REQ-16 (T28) contract pins: no code path calls ``webbrowser.open`` for
agent-initiated navigation.

Covers every dispatch surface that previously could launch the OS browser:

  1. ``AgentToolBridge.execute_tool("open_url")`` — intercepted in-app
     (``_execute_open_url``); ``webbrowser.open`` is monkeypatched to raise,
     so any OS-browser escape would fail the test.
  2. ``ToolExecutor.execute("open_url")`` fallback path — when the bridge
     returns a failure, the legacy ``_open_url`` handler runs; it is
     dead-code-guarded (AC2) and must NOT call ``webbrowser.open``.
  3. ``BrowserServer.execute_tool("open_url"/"search")`` raw MCP branches —
     dead-code-guarded to an in-app-only error; never ``webbrowser.open``.

The crawler and WS manager are deterministic seams (no live web, no OS
browser). ``webbrowser.open`` is replaced by a boom across every test.
"""

import asyncio

import pytest

from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tool_executor import ToolExecutor
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.mcp.builtin_servers import BrowserServer


# ── fakes / seams ──────────────────────────────────────────────────────────


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
def _no_os_browser(monkeypatch):
    """Any webbrowser.open call during these tests blows up."""
    import webbrowser

    def boom(*args, **kwargs):
        raise AssertionError(
            "webbrowser.open was called — the OS browser must never be "
            "launched for agent-initiated navigation (REQ-16)"
        )

    monkeypatch.setattr(webbrowser, "open", boom)


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
        return result

    monkeypatch.setattr(CrawlOrchestrator, "fetch_url", fake_fetch_url)


def _patch_ws(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr("backend.ws_manager.get_websocket_manager", lambda: ws)
    return ws


# ── 1. AgentToolBridge live path ───────────────────────────────────────────


def test_bridge_open_url_never_calls_webbrowser(monkeypatch):
    _patch_ws(monkeypatch)
    _patch_crawl(
        monkeypatch, _FakeCrawlResult(pages=[_FakePage("https://example.com/x", "content")])
    )

    result = asyncio.run(
        AgentToolBridge().execute_tool("open_url", {"url": "https://example.com/x"}, "s1")
    )

    assert result.get("success") is True  # in-app fetch served content
    assert "url" in result  # envelope from _execute_open_url


# ── 2. ToolExecutor fallback path (AC2 duplicate) ──────────────────────────


def test_tool_executor_open_url_fallback_never_calls_webbrowser(monkeypatch):
    executor = ToolExecutor()
    # Force the bridge to fail so the legacy _open_url handler runs — the exact
    # fallback path AC2 says must never launch the OS browser.
    fake_bridge = _FakeBridgeFailure()
    monkeypatch.setattr(
        "backend.agent.tool_bridge.get_agent_tool_bridge", lambda: fake_bridge
    )
    # Make validation permissive so _execute_locally actually reaches the handler.
    executor.validate_parameters = _permissive_validate

    result = asyncio.run(executor.execute("open_url", {"url": "https://example.com/x"}))

    # The executor-level success=True means the handler RAN (returned a dict,
    # did not raise). The guard lives in the tool-level output: an in-app
    # guidance error, NOT a browser launch — webbrowser.open boom never fired.
    assert result.success is True  # handler executed via the fallback path
    assert result.output["success"] is False  # tool-level guard: in-app only
    assert "in-app" in (result.output["error"] or "").lower()
    assert fake_bridge.calls == ["execute_tool"]


# ── 3. Raw BrowserServer branches (unreachable from agent, still guarded) ───


@pytest.mark.asyncio
async def test_browser_server_open_url_never_calls_webbrowser():
    server = BrowserServer()
    result = await server.execute_tool("open_url", {"url": "https://example.com/x"})

    assert result.get("success") is False
    assert "in-app" in (result.get("error") or "").lower()
    assert result.get("url") == "https://example.com/x"  # scheme normalized


@pytest.mark.asyncio
async def test_browser_server_search_never_calls_webbrowser():
    server = BrowserServer()
    result = await server.execute_tool("search", {"query": "iris voice"})

    assert result.get("success") is False
    assert "in-app" in (result.get("error") or "").lower()
    assert result.get("query") == "iris voice"


# ── helpers ────────────────────────────────────────────────────────────────


class _FakeBridgeFailure:
    """A bridge that always fails — forces ToolExecutor's local fallback."""

    def __init__(self):
        self.calls = []

    async def execute_tool(self, tool_name, params, session_id="unknown", plan_title=""):
        self.calls.append("execute_tool")
        return {"success": False, "error": f"bridge failed for {tool_name}"}


def _permissive_validate(tool_name, parameters, sanitize=True):
    return True, None, parameters
