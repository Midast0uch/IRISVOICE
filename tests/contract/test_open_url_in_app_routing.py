"""REQ-16 + REQ-17 + REQ-18 (T34): browser-routing and module-seam coverage.

Brings the three seams TOGETHER in one drive:

  - REQ-16 routing: ``open_url``/``search`` are intercepted in-app
    (``_execute_open_url`` / ``_execute_web_search``) BEFORE the MCP dispatch
    table — the raw ``BrowserServer`` branches and ``ToolExecutor`` fallback
    are dead-code-guarded and never call ``webbrowser.open`` (T27/T28).
  - REQ-17 seam: the same generic dispatch path (registry -> execute_tool)
    serves the module with zero DER control-flow change (T30).
  - REQ-18 trace: the navigation's target surface + job_id/HAR path are
    recorded in the per-task trace (T31) — the acceptance record, not just
    the routing.

Assertions that would go RED if any seam regressed:
  - a routing change that let open_url reach webbrowser.open (boom fires)
  - a trace removal that dropped the navigation surface entry
  - an internet-gate removal that let open_url run with the gate closed
"""

import asyncio

import pytest

import backend.agent.tool_registry as r
from backend.agent.agent_kernel import AgentKernel
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
            "webbrowser.open called — the OS browser must never be launched "
            "for agent-initiated navigation (REQ-16)"
        )

    monkeypatch.setattr(webbrowser, "open", boom)


@pytest.fixture(autouse=True)
def _permissive_gates(monkeypatch):
    import backend.agent.tool_registry as tr
    import backend.capabilities as caps

    monkeypatch.setattr(tr, "_internet_provider", lambda: True)
    monkeypatch.setattr(tr, "_desktop_provider", lambda: True)
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


# ── REQ-16 routing: never webbrowser.open, gate applies ────────────────────


def test_open_url_routed_in_app_never_desktop(monkeypatch):
    """open_url executes in-app (open_tab broadcast + headless fetch); the OS
    browser is never launched (boom would fire)."""
    ws = _patch_ws(monkeypatch)
    _patch_crawl(
        monkeypatch,
        _FakeCrawlResult(pages=[_FakePage("https://example.com/x", "content")]),
    )
    result = asyncio.run(
        AgentToolBridge().execute_tool("open_url", {"url": "example.com/x"}, "s1")
    )
    assert result.get("success") is True
    assert ws.broadcasts and ws.broadcasts[0][1]["type"] == "open_tab"


def test_internet_gate_applies_to_open_url(monkeypatch):
    """REQ-16 AC3: with the internet gate closed, open_url is denied before
    any routing — matching search/crawler_query."""
    monkeypatch.setattr(r, "_internet_provider", lambda: False)
    monkeypatch.setattr(r, "_desktop_provider", lambda: True)
    result = asyncio.run(
        AgentToolBridge().execute_tool("open_url", {"url": "https://x"}, "s1")
    )
    assert result.get("success") is False
    assert "Internet access is disabled" in result.get("error", "")


def test_raw_browser_server_branches_guarded(monkeypatch):
    """The raw MCP branches are dead-code-guarded: even a direct call returns
    in-app guidance, never webbrowser.open."""
    server = BrowserServer()
    for name, args in (("open_url", {"url": "https://x"}),
                       ("search", {"query": "iris voice"})):
        result = asyncio.run(server.execute_tool(name, args))
        assert result.get("success") is False
        assert "in-app" in (result.get("error") or "").lower()


def test_tool_executor_fallback_guarded(monkeypatch):
    """REQ-16 AC2: the ToolExecutor fallback (bridge-failure path) never
    launches the OS browser."""
    executor = ToolExecutor()
    monkeypatch.setattr(
        "backend.agent.tool_bridge.get_agent_tool_bridge",
        lambda: _FailingBridge(),
    )
    executor.validate_parameters = _permissive_validate
    result = asyncio.run(executor.execute("open_url", {"url": "https://x"}))
    assert result.success is True  # handler ran (returned dict)
    assert result.output["success"] is False  # tool-level guard: in-app only
    assert "in-app" in (result.output["error"] or "").lower()


# ── REQ-17 seam: generic dispatch, zero DER change ─────────────────────────


def test_generic_dispatch_serves_open_url(monkeypatch):
    """The module attaches declaratively: the SAME generic execute_tool path
    (registry -> gate -> interceptor) serves open_url — no DER loop branch."""
    import inspect

    from backend.agent import agent_kernel

    src = inspect.getsource(
        agent_kernel.AgentKernel._der_run_step_execution_async
    )
    assert "execute_tool(" in src
    assert 'if item.tool == "open_url"' not in src
    assert 'if tool_name == "open_url"' not in src


# ── REQ-18 trace: navigation surface + job_id/HAR recorded ─────────────────


def test_nav_trace_records_surface_and_provenance(monkeypatch):
    """REQ-18 AC5 (T34): executing open_url through the DER step path records
    the navigation surface (in-app) + job_id/HAR in the per-task trace."""
    from backend.agent.der_trace import clear_traces, get_der_trace

    clear_traces()
    try:
        k = AgentKernel.__new__(AgentKernel)
        k.conversation_id = "conv_t34"
        k.session_id = "sess_t34"
        k.mark_external_tool = lambda *a, **kw: None
        k._capture_tool_result = lambda *a, **kw: None
        k._format_tool_result = lambda raw: "formatted"

        class _Bridge:
            async def execute_tool(self, tool_name, params, session_id="", plan_title=""):
                return {"success": True, "url": "https://example.com/x",
                        "job_id": "job-34", "har_path": "data/har/job-34.har"}

        k._tool_bridge = _Bridge()

        from types import SimpleNamespace as NS

        item = NS(tool="open_url", params={"url": "https://example.com/x"},
                  step_id="s1", step_number=1, description="open page",
                  expected_output=None)
        plan = NS(plan_title="T")
        asyncio.run(k._der_run_step_execution_async(item, {}, "sess_t34", "t1", plan))

        nav = get_der_trace(k._der_trace_task_id()).entries("navigation")
        assert nav, "navigation trace entry missing"
        last = nav[-1]
        assert last["surface"] == "in-app"
        assert last["tool"] == "open_url"
        assert last["url"] == "https://example.com/x"
        assert last["job_id"] == "job-34"
        assert last["har_path"] == "data/har/job-34.har"
    finally:
        clear_traces()


# ── helpers ────────────────────────────────────────────────────────────────


class _FailingBridge:
    async def execute_tool(self, tool_name, params, session_id="unknown", plan_title=""):
        return {"success": False, "error": f"bridge failed for {tool_name}"}


def _permissive_validate(tool_name, parameters, sanitize=True):
    return True, None, parameters
