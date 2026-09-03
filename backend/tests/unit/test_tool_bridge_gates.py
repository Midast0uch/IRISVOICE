#!/usr/bin/env python3
"""
Phase 2 tests: execute_tool routes through the Tool Registry.

Verifies the dispatcher:
  * Resolves legacy aliases (web_search / google_search -> search) via the registry.
  * Applies the consolidated internet/desktop gate via capability_allowed().
  * Still dispatches to the right executor when the gate passes.

Real network / MCP servers are faked so these are fast and deterministic.
"""

import pytest

import backend.agent.tool_registry as r
from backend.agent.tool_bridge import AgentToolBridge


@pytest.fixture(autouse=True)
def _gate_env(monkeypatch):
    """Permissive providers + allow all tools via CapabilitySet by default."""
    monkeypatch.setattr(r, "_internet_provider", lambda: True)
    monkeypatch.setattr(r, "_desktop_provider", lambda: True)
    import backend.capabilities as caps
    monkeypatch.setattr(caps.CapabilitySet, "is_tool_allowed", staticmethod(lambda name: True))
    yield


def _make_bridge():
    return AgentToolBridge()


@pytest.mark.asyncio
async def test_alias_web_search_resolves_and_dispatches(monkeypatch):
    bridge = _make_bridge()
    # Fake the search executor so no real network call happens.
    captured = {}

    async def fake_search(params, sid):
        captured["params"] = params
        return {"success": True, "fake": True}

    monkeypatch.setattr(bridge, "_execute_web_search", fake_search)

    result = await bridge.execute_tool("web_search", {"query": "ai chips"}, session_id="t")
    assert result.get("fake") is True, f"expected dispatched to search, got {result}"
    assert captured["params"] == {"query": "ai chips"}


@pytest.mark.asyncio
async def test_alias_google_search_resolves_to_search(monkeypatch):
    bridge = _make_bridge()
    captured = {}

    async def fake_search(params, sid):
        captured["hit"] = True
        return {"success": True, "fake": True}

    monkeypatch.setattr(bridge, "_execute_web_search", fake_search)
    await bridge.execute_tool("google_search", {"query": "x"}, session_id="t")
    assert captured.get("hit") is True


@pytest.mark.asyncio
async def test_internet_gate_blocks_search_when_off(monkeypatch):
    r._internet_provider = lambda: False
    bridge = _make_bridge()
    result = await bridge.execute_tool("web_search", {"query": "x"}, session_id="t")
    assert result.get("success") is False
    assert "Internet access is disabled" in result.get("error", "")


@pytest.mark.asyncio
async def test_internet_gate_blocks_crawler_when_off(monkeypatch):
    r._internet_provider = lambda: False
    bridge = _make_bridge()
    result = await bridge.execute_tool("crawler_query", {"query": "x"}, session_id="t")
    assert result.get("success") is False
    assert "Internet access is disabled" in result.get("error", "")


@pytest.mark.asyncio
async def test_internet_gate_blocks_open_url_when_off(monkeypatch):
    """REQ-16 AC3 (T29): open_url is gated by the internet-access capability
    exactly like search/crawler_query. With the internet gate closed, the call
    is denied with the internet error BEFORE the desktop gate — matching the
    other network tools' behavior."""
    r._internet_provider = lambda: False
    r._desktop_provider = lambda: True  # desktop open — only internet denies
    bridge = _make_bridge()
    result = await bridge.execute_tool("open_url", {"url": "https://x"}, session_id="t")
    assert result.get("success") is False
    assert "Internet access is disabled" in result.get("error", "")


@pytest.mark.asyncio
async def test_desktop_gate_blocks_open_url_when_off(monkeypatch):
    r._desktop_provider = lambda: False
    bridge = _make_bridge()
    result = await bridge.execute_tool("open_url", {"url": "https://x"}, session_id="t")
    assert result.get("success") is False
    assert "Desktop control is disabled" in result.get("error", "")


@pytest.mark.asyncio
async def test_desktop_gate_dispatches_when_on(monkeypatch):
    """REQ-16 (T27/T28): with the desktop gate open, open_url is dispatched
    IN-APP (intercepted by _execute_open_url before the MCP dispatch table),
    never to execute_mcp_tool -> BrowserServer -> webbrowser.open.

    TEST CHANGE (called out per AGENTS.md): this test previously asserted the
    pre-REQ-16 contract — that open_url reached ``execute_mcp_tool("browser",
    "open_url")``. REQ-16 AC1/AC2 + T28 explicitly require that path to be
    removed (the OS browser is never launched for agent-initiated navigation),
    so the assertion now pins the NEW contract: ``_execute_open_url`` runs and
    ``execute_mcp_tool`` is NOT reached. The gate check itself is unchanged.
    """
    r._desktop_provider = lambda: True
    bridge = _make_bridge()
    captured = {}

    async def fake_inapp(params, sid):
        captured["params"] = params
        return {"success": True, "in_app": True}

    async def boom(*args, **kwargs):
        raise AssertionError(
            "open_url must never reach execute_mcp_tool (REQ-16 in-app only)"
        )

    monkeypatch.setattr(bridge, "_execute_open_url", fake_inapp)
    monkeypatch.setattr(bridge, "execute_mcp_tool", boom)
    result = await bridge.execute_tool("open_url", {"url": "https://x"}, session_id="t")
    assert result.get("in_app") is True
    assert captured.get("params") == {"url": "https://x"}


@pytest.mark.asyncio
async def test_unknown_tool_not_resolved_but_still_runs_dispatch(monkeypatch):
    """An unknown tool name has no spec; execute_tool should fall through to its
    normal 'Unknown tool' outcome rather than crashing on the registry lookup."""
    bridge = _make_bridge()
    result = await bridge.execute_tool("totally_unknown_tool_xyz", {}, session_id="t")
    assert result.get("error") is not None
    assert "Unknown tool" in result.get("error", "")
