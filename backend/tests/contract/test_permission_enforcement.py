"""Contract tests: T22 — permission enforcement is proven (REQ-17 AC1/AC2/AC3/AC4/AC5).

CT-11  PERMISSION GATE REACHED — a gated SIDE_EFFECT call emits PERMISSION_REQUEST,
        blocks until answered, and a DENY prevents execution. Approve/deny both reach
        respond_to_permission (the card's click path). A permission-check exception
        fails CLOSED (blocks the tool), never silently proceeds.
CT-12  TIER SET vs RUNTIME REGISTRY — every registered tool resolves to a tier, and the
        destructive tools that actually exist in the runtime registry are covered by the
        destructive tier set (so real destructive tools are gated).
CT-13  MODE BINDING — the effective permission mode derives from the user's selection; an
        absent "mode" key does NOT resolve to the most permissive policy ("personal").
"""
import asyncio
import json

import pytest

from backend import capabilities as _caps
from backend.agent import permissions as _perm
from backend.agent import tool_registry as _r


def _write_cfg(monkeypatch, tmp_path, content):
    cfg_path = tmp_path / "cfg.json"
    if content is not None:
        cfg_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(_caps, "_CFG_PATH", str(cfg_path))
    return cfg_path


@pytest.mark.asyncio
async def test_ct11_gate_reached_denial_blocks_approval_runs(tmp_path, monkeypatch):
    """REQ-17 AC1/AC2/AC4: gated call emits PERMISSION_REQUEST, blocks until answered;
    DENY prevents execution; APPROVE lets it proceed; both reach respond_to_permission."""
    monkeypatch.setattr(_perm, "PERMISSION_TIMEOUT_SIDE_EFFECT", 5)
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "developer"}))

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent.permissions import get_permission_system

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    # --- DENY path ---
    task = asyncio.create_task(
        bridge.execute_tool(
            "edit_file", {"path": str(tmp_path / "x.txt"), "content": "hi"},
            session_id="ct11-deny", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1
    assert seen[0].event == IRISStreamEvent.PERMISSION_REQUEST
    rid = seen[0].data["request_id"]

    get_permission_system().respond_to_permission(rid, approved=False)
    result = await task
    assert result.get("success") is False
    assert result.get("permission_response") == "denied"
    assert not (tmp_path / "x.txt").exists()  # tool did not run

    # --- APPROVE path ---
    seen.clear()
    task2 = asyncio.create_task(
        bridge.execute_tool(
            "edit_file", {"path": str(tmp_path / "y.txt"), "content": "hi"},
            session_id="ct11-approve", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1
    rid2 = seen[0].data["request_id"]
    get_permission_system().respond_to_permission(rid2, approved=True)
    result2 = await task2
    # Approved -> gate allows; edit_file has no real dispatcher so it falls through to
    # "Unknown tool" (not a permission failure) — proving the gate did NOT block.
    assert result2.get("permission_response") != "denied"
    assert "Permission denied" not in result2.get("error", "")


@pytest.mark.asyncio
async def test_ct11_fail_closed_on_permission_error(tmp_path, monkeypatch):
    """REQ-17: the gate must NOT silently bypass on error — an exception inside the
    permission check blocks the tool (fail closed), it does not proceed."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "developer"}))

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge

    bus = get_event_bus()
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, lambda e: None)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    # Force an exception inside Phase 4's permission check
    system = _perm.get_permission_system()
    real_request = system.request_permission

    def _boom(*a, **k):
        raise RuntimeError("injected permission failure")

    monkeypatch.setattr(system, "request_permission", _boom)
    try:
        result = await bridge.execute_tool(
            "edit_file", {"path": str(tmp_path / "z.txt"), "content": "hi"},
            session_id="ct11-failclosed", _skip_resilience=True,
        )
    finally:
        monkeypatch.setattr(system, "request_permission", real_request)

    assert result.get("success") is False
    assert result.get("permission_response") == "error"
    assert not (tmp_path / "z.txt").exists()  # tool did not run


def test_ct12_tier_set_vs_runtime_registry(monkeypatch):
    """REQ-17 AC5: every registered tool resolves to a tier, and the destructive tools
    that actually exist in the runtime registry are covered by the destructive tier set."""
    monkeypatch.setattr(_r, "_internet_provider", lambda: True)
    monkeypatch.setattr(_r, "_desktop_provider", lambda: True)
    registered = {t["name"] for t in _r.get_registry_tools()}

    # Every registered tool resolves to a valid tier
    for name in registered:
        tier = _perm.classify_tool(name, {})
        assert tier in (
            _perm.PermissionTier.READ_ONLY,
            _perm.PermissionTier.SIDE_EFFECT,
            _perm.PermissionTier.DESTRUCTIVE,
        ), f"{name} does not resolve to a tier"

    # Destructive tools that exist in the registry must be gated (in _DESTRUCTIVE_TOOLS)
    registry_destructive = {
        n for n in registered
        if _perm.classify_tool(n, {}) == _perm.PermissionTier.DESTRUCTIVE
    }
    assert registry_destructive <= _perm._DESTRUCTIVE_TOOLS, (
        f"Registry destructive tools not covered by _DESTRUCTIVE_TOOLS: "
        f"{registry_destructive - _perm._DESTRUCTIVE_TOOLS}"
    )


def test_ct13_mode_binding_absent_not_permissive(tmp_path, monkeypatch):
    """REQ-17 AC3: an absent 'mode' key does NOT resolve to the most permissive policy
    ('personal'); it fails CLOSED to 'developer' (which requires approval)."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"other": True}))
    assert _caps.CapabilitySet.get_mode() == "developer"
    # And developer mode requires approval for SIDE_EFFECT (the gate asks)
    assert _perm.get_permission_action(
        _perm.PermissionTier.SIDE_EFFECT, "developer"
    ).value == "require_approval"


@pytest.mark.asyncio
async def test_ct11_timeout_treated_as_denied(tmp_path, monkeypatch):
    """REQ-17 edge: a gated call whose permission times out is treated as denied —
    the tool does NOT execute."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "developer"}))
    # Make the permission wait time out fast so the test does not hang.
    monkeypatch.setattr(_perm, "PERMISSION_TIMEOUT_SIDE_EFFECT", 0.2)

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.mcp.builtin_servers import FileManagerServer

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    target = tmp_path / "out.txt"
    # Do NOT respond — let the permission request time out.
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "hi"},
            session_id="ct11-timeout", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1
    result = await asyncio.wait_for(task, timeout=5)
    assert result.get("success") is False
    assert result.get("permission_response") == "timed_out"
    assert not target.exists()
