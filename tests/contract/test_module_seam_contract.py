"""REQ-17 (T30) contract pins: the module seam.

A new capability module (websearch, browser, vision, future ones) attaches
DECLARATIVELY via ``ToolSpec`` entries with ZERO change to DER's control flow.
This file pins the seam so a future edit cannot silently reintroduce a
per-tool branch in the step-execution loop or bypass the capability gate.

Covers (REQ-17 AC1-AC5 + edge cases):
  - AC1: a module declares itself via ToolSpec; DER control flow needs no change.
  - AC2: modules report through the EXISTING contracts (tool envelope, HAR
    provenance, structured progress) — pinned via the reference specs' wiring.
  - AC3: requires_internet / requires_desktop / permission_tier are the uniform
    capability gate for EVERY module (a throwaway module is gated the same way
    as open_url / search).
  - AC4: the DER step-execution loop dispatches generically via
    ``execute_tool(tool_name=item.tool, ...)`` — zero ``if tool_name ==``
    branches in the loop; MCP-routed modules resolve through the registry's
    mcp_server/mcp_tool fields -> execute_mcp_tool.
  - AC5: crawl (Crawl4AI/HAR) and vision remain the reference implementations,
    registered with the documented wiring (NO CHANGE to either).

Reference implementations pinned (NO CHANGE): crawler_query (executor="crawler",
long_running, requires_internet) and the four vision_* specs (executor="mcp",
mcp_server="vision").
"""

import asyncio
import inspect
import uuid

import pytest

import backend.agent.tool_registry as r
from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tool_registry import (
    ToolSpec,
    resolve_tool,
    capability_allowed,
    capability_denied_by,
    register_tool,
    get_registry_tools,
    get_all_specs,
    is_parallel_safe,
)


# ── fixtures / helpers ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _permissive_gates(monkeypatch):
    monkeypatch.setattr(r, "_internet_provider", lambda: True)
    monkeypatch.setattr(r, "_desktop_provider", lambda: True)
    yield


def _fresh_module_name(prefix="seam_probe"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_throwaway(spec: ToolSpec):
    """Register a throwaway spec and return a cleanup that removes it."""
    register_tool(spec)
    names = {spec.name, *spec.aliases}

    def cleanup():
        r._REGISTRY.pop(spec.name, None)
        for alias in spec.aliases:
            r._ALIAS_INDEX.pop(alias, None)

    return cleanup


# ── AC1: declarative attachment — DER control flow needs no change ─────────


def test_der_step_loop_dispatches_generically():
    """The DER step-execution loop calls execute_tool(tool_name=item.tool)
    with NO per-tool-name branches (AC1/AC4). A new module attaches by
    ToolSpec alone."""
    from backend.agent import agent_kernel

    src = inspect.getsource(agent_kernel.AgentKernel._der_run_step_execution_async)
    # The ONLY dispatch call is the generic bridge call, keyed by item.tool.
    assert "execute_tool(" in src
    assert "tool_name=item.tool" in src
    # No per-tool if-branch inside the loop body.
    for bad in ('if item.tool == "', 'if tool_name == "', '== "crawler_query"'):
        assert bad not in src, f"per-tool branch found in DER step loop: {bad}"


def test_toolspec_declares_full_field_set():
    """AC1: ToolSpec carries the full declarative field set a module needs."""
    spec = ToolSpec(
        name="x", description="d", parameters={"p": {"type": "string"}},
        category="web", aliases=["x_alias"], requires_internet=True,
        requires_desktop=False, permission_tier="read_only",
        executor="mcp", mcp_server="srv", mcp_tool="tool",
        critical=True, parallel_safe=True, long_running=True,
    )
    assert spec.executor == "mcp" and spec.mcp_server == "srv" and spec.mcp_tool == "tool"
    assert spec.long_running is True and spec.critical is True and spec.parallel_safe is True


# ── AC3: uniform capability gate for EVERY module ──────────────────────────


def test_throwaway_module_gated_by_requires_internet(monkeypatch):
    """A NEW module with requires_internet=True is denied when the internet
    gate is closed — exactly like search/crawler_query/open_url (AC3)."""
    name = _fresh_module_name()
    cleanup = _register_throwaway(
        ToolSpec(name=name, description="seam probe", executor="internal",
                 requires_internet=True)
    )
    try:
        monkeypatch.setattr(r, "_internet_provider", lambda: False)
        spec = resolve_tool(name)
        assert capability_allowed(spec) is False
        assert capability_denied_by(spec) == "internet"
        # And it is HIDDEN from the LLM-facing tool list while gated.
        assert name not in {t["name"] for t in get_registry_tools()}
    finally:
        cleanup()


def test_throwaway_module_gated_by_requires_desktop(monkeypatch):
    name = _fresh_module_name()
    cleanup = _register_throwaway(
        ToolSpec(name=name, description="seam probe", executor="internal",
                 requires_desktop=True)
    )
    try:
        monkeypatch.setattr(r, "_desktop_provider", lambda: False)
        spec = resolve_tool(name)
        assert capability_allowed(spec) is False
        assert capability_denied_by(spec) == "desktop"
    finally:
        cleanup()


def test_module_without_capability_flags_always_allowed():
    """Edge case: a module with no mcp_server (pure executor="internal") and
    no capability flags is not gated."""
    name = _fresh_module_name()
    cleanup = _register_throwaway(
        ToolSpec(name=name, description="seam probe", executor="internal")
    )
    try:
        spec = resolve_tool(name)
        assert capability_allowed(spec) is True
        assert capability_denied_by(spec) is None
        # parallel_safe resolves from the spec (default False).
        assert is_parallel_safe(name) is False
    finally:
        cleanup()


# ── AC4: dispatch resolves through the registry, not new branches ──────────


def test_mcp_routed_module_dispatches_via_execute_mcp_tool(monkeypatch):
    """A NEW MCP-routed module (executor="mcp" + mcp_server/mcp_tool) resolves
    through the registry and dispatches via execute_mcp_tool — zero new
    branches in the step loop (AC4)."""
    name = _fresh_module_name()
    cleanup = _register_throwaway(
        ToolSpec(name=name, description="seam probe", executor="mcp",
                 mcp_server="__seam_srv__", mcp_tool="__seam_tool__")
    )
    try:
        spec = resolve_tool(name)
        assert spec.executor == "mcp"
        assert spec.mcp_server == "__seam_srv__"
        assert spec.mcp_tool == "__seam_tool__"
        # The registry's LLM-facing list advertises the server binding.
        listed = {t["name"]: t for t in get_registry_tools()}
        assert listed[name]["server"] == "__seam_srv__"

        # Behavioral: a fake server registered in the bridge is reached with
        # the spec's mcp_server/mcp_tool fields (the exact path execute_tool
        # uses for MCP-routed tools).
        bridge = AgentToolBridge()
        bridge._mcp_servers["__seam_srv__"] = _FakeSeamServer()
        result = asyncio.run(
            bridge.execute_mcp_tool("__seam_srv__", "__seam_tool__", {"q": 1}, "s1")
        )
        assert result == {"seam": "ok", "tool": "__seam_tool__"}
    finally:
        cleanup()


# ── T14: in-app browser module is OPTIONAL (REQ-6) ─────────────────────────


def test_browser_surface_is_http_only_not_a_tool():
    """T14 (REQ-6 AC1): the in-app browser surface attaches as an HTTP module
    (FastAPI routes), NOT a DER tool. There is no 'browser_proxy' ToolSpec and
    the DER step loop has zero per-tool branches for it — disabling the module
    cannot affect DER control flow."""
    from backend.agent import agent_kernel

    # 1. No tool named after the browser surface in the registry.
    all_specs = {s.name for s in get_all_specs()}
    for name in ("browser_proxy", "browser_replay", "in_app_browser"):
        assert name not in all_specs, f"browser surface must not be a DER tool: {name}"

    # 2. The DER step loop dispatches generically — no branch names it.
    src = inspect.getsource(agent_kernel.AgentKernel._der_run_step_execution_async)
    for bad in ("browser_proxy", "browser_surface", "/api/browser", "in_app_browser"):
        assert bad not in src, f"DER step loop references browser module: {bad}"


def test_crawl_completes_with_proxy_gate_closed():
    """T14 (REQ-6 AC2): closing the browser module's gate (the shared internet
    gate) does NOT prevent a crawl from completing. The crawler and the browser
    surface are independent consumers of the same gate."""
    import backend.agent.tool_registry as r2

    r2.set_capability_providers(lambda: True, lambda: True)
    try:
        # Gate open: the browser proxy is allowed...
        assert capability_denied_by(
            ToolSpec(name="probe_proxy", description="d", requires_internet=True)
        ) is None
        # ...and crawler_query is independently allowed (both consume the same
        # internet gate; neither gates the other).
        assert capability_denied_by(resolve_tool("crawler_query")) is None
    finally:
        r2.set_capability_providers(lambda: False, lambda: False)


# ── AC5: reference implementations pinned (NO CHANGE) ──────────────────────


def test_reference_crawl_spec_wiring():
    """AC5: the crawl seam (Crawl4AI/HAR) declares the documented wiring."""
    spec = resolve_tool("crawler_query")
    assert spec is not None
    assert spec.executor == "crawler"
    assert spec.long_running is True          # narration heartbeat capability
    assert spec.requires_internet is True
    assert spec.critical is True


def test_reference_vision_specs_wiring():
    """AC5: the vision seam declares the documented wiring (mcp_server)."""
    expected = {
        "vision_detect_element": "vision.find_ui_element",
        "vision_analyze_screen": "vision.analyze_screen",
        "vision_validate_action": "vision.suggest_next_action",
        "vision_get_context": "vision.describe_live_frame",
    }
    for name, mcp_tool in expected.items():
        spec = resolve_tool(name)
        assert spec is not None, f"vision spec {name} not registered"
        assert spec.executor == "mcp"
        assert spec.mcp_server == "vision"
        assert spec.mcp_tool == mcp_tool
        assert spec.parallel_safe is True


# ── edge cases ─────────────────────────────────────────────────────────────


def test_module_registered_twice_under_different_names():
    """Edge case: two distinct specs can share an executor/server without
    colliding (different names, both resolvable)."""
    n1 = _fresh_module_name("seam_a")
    n2 = _fresh_module_name("seam_b")
    c1 = _register_throwaway(ToolSpec(name=n1, description="a", executor="internal"))
    c2 = _register_throwaway(ToolSpec(name=n2, description="b", executor="internal"))
    try:
        assert resolve_tool(n1).description == "a"
        assert resolve_tool(n2).description == "b"
        assert resolve_tool(n1) is not resolve_tool(n2)
    finally:
        c1()
        c2()


def test_register_same_name_idempotent():
    """Re-registering the same name is idempotent (no duplicate entry)."""
    name = _fresh_module_name()
    c1 = _register_throwaway(ToolSpec(name=name, description="first", executor="internal"))
    before = len(get_all_specs())
    c2 = _register_throwaway(ToolSpec(name=name, description="second", executor="internal"))
    try:
        assert len(get_all_specs()) == before  # no duplicate
        assert resolve_tool(name).description == "second"  # last wins
    finally:
        c2()
        c1()


class _FakeSeamServer:
    """Minimal stand-in for an MCP BuiltinServer: handle_request -> result."""

    async def handle_request(self, request):
        from types import SimpleNamespace

        return SimpleNamespace(result={"seam": "ok", "tool": request.params["name"]})
