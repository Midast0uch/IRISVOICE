#!/usr/bin/env python3
"""
Tests for the Tool Registry (Phase 1 of the Agent + DER Unification Plan).

Verifies:
  * All core tools are registered (single source of truth).
  * Alias resolution normalizes legacy names (web_search/google_search -> search).
  * capability_allowed gates internet/desktop tools via injectable providers
    (no agent_kernel import required -> no import cycle, unit-testable).
  * get_registry_tools mirrors get_available_tools gating (internet + CapabilitySet).
  * permission_tier uses the live PermissionTier vocabulary.
  * critical / parallel_safe flags are set sensibly for later phases.
"""

import sys
import pytest

import backend.agent.tool_registry as r
from backend.agent.tool_registry import (
    ToolSpec,
    register_tool,
    resolve_tool,
    capability_allowed,
    capability_denied_by,
    set_capability_providers,
    get_all_specs,
    get_registry_tools,
    is_parallel_safe,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reset_providers(monkeypatch):
    """Each test starts with permissive providers; restore after."""
    monkeypatch.setattr(r, "_internet_provider", lambda: True)
    monkeypatch.setattr(r, "_desktop_provider", lambda: True)
    yield
    # monkeypatch auto-restores


@pytest.fixture
def _allow_all_caps(monkeypatch):
    """Make CapabilitySet.is_tool_allowed return True so only the internet/
    desktop gate is exercised by get_registry_tools tests."""
    import backend.capabilities as caps
    monkeypatch.setattr(caps.CapabilitySet, "is_tool_allowed", staticmethod(lambda name: True))
    yield


# ── Registration completeness ─────────────────────────────────────────────────
def test_registry_populated_on_import():
    specs = get_all_specs()
    assert len(specs) >= 40, f"expected >=40 tools, got {len(specs)}"
    names = {s.name for s in specs}
    # Spot-check the canonical names from get_available_tools()
    for expected in (
        "search", "crawler_query", "read_file", "write_file", "git_status",
        "git_commit", "run_command", "recall_memory", "improve_self",
        "ask_user_question", "speak", "open_url", "take_screenshot",
        "vision_analyze_screen", "github_list_repos",
    ):
        assert expected in names, f"tool '{expected}' not registered"


def test_no_duplicate_names():
    names = [s.name for s in get_all_specs()]
    assert len(names) == len(set(names)), "duplicate tool names registered"


def test_alias_index_consistent():
    for spec in get_all_specs():
        for alias in spec.aliases:
            assert resolve_tool(alias) is spec, f"alias {alias} -> {resolve_tool(alias).name}, expected {spec.name}"


# ── Alias resolution ───────────────────────────────────────────────────────────
def test_resolve_tool_canonical():
    assert resolve_tool("search").name == "search"


def test_resolve_tool_aliases():
    assert resolve_tool("web_search").name == "search"
    assert resolve_tool("google_search").name == "search"


def test_resolve_tool_unknown_returns_none():
    assert resolve_tool("definitely_not_a_tool") is None


def test_register_tool_is_idempotent():
    # Use a throwaway name so we don't corrupt a real registered tool.
    name = "_idempotent_probe"
    before = len(get_all_specs())
    register_tool(ToolSpec(name=name, description="first"))
    register_tool(ToolSpec(name=name, description="second"))  # re-register same name
    after = len(get_all_specs())
    # Re-registering the same name must NOT add a new entry (count stable).
    assert after == before + 1, f"re-registering same name added entries: {before} -> {after}"
    # Last registration wins for the shared name.
    assert resolve_tool(name).description == "second"


# ── Capability gating (injectable providers, no agent_kernel import) ───────────
def test_capability_allowed_internet_gate_off():
    monkeypatch_internet(False)
    spec = resolve_tool("search")
    assert spec.requires_internet is True
    assert capability_allowed(spec) is False


def test_capability_allowed_internet_gate_on():
    monkeypatch_internet(True)
    assert capability_allowed(resolve_tool("search")) is True


def test_capability_allowed_desktop_gate_off():
    monkeypatch_desktop(False)
    assert capability_allowed(resolve_tool("open_url")) is False


def test_capability_allowed_desktop_gate_on():
    monkeypatch_desktop(True)
    assert capability_allowed(resolve_tool("open_url")) is True


def test_open_url_requires_internet_and_desktop():
    """REQ-16 AC3 (T29): open_url carries BOTH capability flags so the internet
    gate applies to it exactly as it applies to other network tools, while the
    existing desktop gate is preserved."""
    spec = resolve_tool("open_url")
    assert spec.requires_internet is True
    assert spec.requires_desktop is True


def test_capability_denied_by_names_true_blocker(monkeypatch):
    """When both flags are set, capability_denied_by() reports the ACTUAL
    denying capability — internet vs desktop — not the first flag in
    declaration order (REQ-16/T29 latent-gate fix)."""
    spec = resolve_tool("open_url")
    # internet off, desktop on -> internet is the blocker
    monkeypatch.setattr(r, "_internet_provider", lambda: False)
    monkeypatch.setattr(r, "_desktop_provider", lambda: True)
    assert capability_denied_by(spec) == "internet"
    # internet on, desktop off -> desktop is the blocker
    monkeypatch.setattr(r, "_internet_provider", lambda: True)
    monkeypatch.setattr(r, "_desktop_provider", lambda: False)
    assert capability_denied_by(spec) == "desktop"
    # both on -> allowed
    monkeypatch.setattr(r, "_internet_provider", lambda: True)
    monkeypatch.setattr(r, "_desktop_provider", lambda: True)
    assert capability_denied_by(spec) is None


def test_capability_allowed_non_gated_tool_always_allowed():
    # read_file needs neither internet nor desktop
    assert capability_allowed(resolve_tool("read_file")) is True


def test_no_agent_kernel_import_from_registry_module():
    # tool_registry must not import agent_kernel at module load (avoid cycle).
    # It may already be imported via backend.agent package __init__, so we only
    # assert the registry module itself does not reference it at definition time
    # by confirming capability_allowed imports it lazily (not at import).
    src = (r.__file__ and open(r.__file__, encoding="utf-8").read()) or ""
    # The lazy import must live INSIDE capability_allowed, not at module top.
    assert "from backend.agent.agent_kernel import" not in src.split("def capability_allowed")[0], \
        "agent_kernel must not be imported at tool_registry module top-level"


# ── get_registry_tools mirrors get_available_tools gating ─────────────────────
def test_get_registry_tools_includes_search_when_internet_on(_allow_all_caps):
    monkeypatch_internet(True)
    names = {t["name"] for t in get_registry_tools()}
    assert "search" in names
    assert "crawler_query" in names


def test_get_registry_tools_excludes_search_when_internet_off(_allow_all_caps):
    monkeypatch_internet(False)
    names = {t["name"] for t in get_registry_tools()}
    assert "search" not in names
    assert "crawler_query" not in names
    # Non-internet tools still present
    assert "read_file" in names


def test_get_registry_tools_shape_matches_llm_schema(_allow_all_caps):
    monkeypatch_internet(True)
    tools = get_registry_tools()
    assert isinstance(tools, list) and tools
    for t in tools:
        assert set(["name", "description", "parameters", "category"]).issubset(t.keys())
    # search should carry its server tag like get_available_tools did
    search = next(t for t in tools if t["name"] == "search")
    assert search["category"] == "web"


# ── Permission tier vocabulary (live PermissionTier values) ───────────────────
def test_permission_tiers_use_live_vocabulary():
    valid = {"read_only", "side_effect", "destructive"}
    for spec in get_all_specs():
        assert spec.permission_tier in valid, f"{spec.name} has bad tier {spec.permission_tier!r}"


def test_destructive_tools_flagged():
    destructive = {s.name for s in get_all_specs() if s.permission_tier == "destructive"}
    assert "delete_file" in destructive
    assert "shutdown" in destructive
    assert "lock_screen" in destructive


# ── Later-phase flags ──────────────────────────────────────────────────────────
def test_critical_flags_set_for_core_info_tools():
    critical = {s.name for s in get_all_specs() if s.critical}
    for core in ("search", "crawler_query", "read_file", "recall_memory", "git_status"):
        assert core in critical, f"{core} should be marked critical"


def test_parallel_safe_flags_set_for_read_only_tools():
    parallel = {s.name for s in get_all_specs() if s.parallel_safe}
    # read-only, no shared state -> parallel safe
    for safe in ("search", "read_file", "list_directory", "recall_memory", "git_status", "speak"):
        assert safe in parallel, f"{safe} should be parallel_safe"
    # mutating tools must NOT be parallel safe
    for unsafe in ("write_file", "git_commit", "run_command", "delete_file", "crawler_query"):
        assert unsafe not in parallel, f"{unsafe} must NOT be parallel_safe"


def test_is_parallel_safe_function_gate():
    """The DER loop calls is_parallel_safe(tool) to decide concurrency.

    This is the authoritative gate (Phase 4b) — verify it matches the
    registry flags and fails closed on unknown/None tools.
    """
    # Read-only / independent tools AND any MCP-routed tool -> safe to run concurrently.
    # MCP routing is the general rule: a tool executed by a registered/connected
    # MCP server is parallel_safe (independent server process) even when mutating.
    for safe in (
        "search", "read_file", "list_directory", "recall_memory", "git_status",
        "vision_analyze_screen", "vision_detect_element", "vision_get_context",
        "github_get_user", "github_list_repos", "github_get_repo_branches",
        "write_file", "delete_file", "create_skill", "open_url", "create_directory",
    ):
        assert is_parallel_safe(safe) is True, f"{safe} should be parallel_safe"
    # Non-MCP mutating / stateful / desktop-control tools -> serial (no races).
    # Destructive SYSTEM-control MCP tools (shutdown/restart/lock) also stay serial.
    for unsafe in (
        "git_commit", "run_command", "crawler_query",
        "gui_click", "gui_type", "gui_press_key", "take_screenshot",
        "shutdown", "restart", "lock_screen",
    ):
        assert is_parallel_safe(unsafe) is False, f"{unsafe} must NOT be parallel_safe"
    # Fail-closed: unknown / None / empty -> False (never parallelize blindly)
    assert is_parallel_safe(None) is False
    assert is_parallel_safe("") is False
    assert is_parallel_safe("totally_unknown_tool_xyz") is False
    # Alias resolution: web_search -> search (parallel_safe)
    assert is_parallel_safe("web_search") is True


# ── Helpers ────────────────────────────────────────────────────────────────────
def monkeypatch_internet(value: bool):
    r._internet_provider = lambda: value


def monkeypatch_desktop(value: bool):
    r._desktop_provider = lambda: value
