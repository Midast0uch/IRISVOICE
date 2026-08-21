"""Contract test: T23 — capability denial escalates to a permission request (REQ-18).

When a tool is capability-blocked in personal mode ([13.3] gate), the system escalates
to a permission request instead of returning a silent error. Approval executes the
tool; denial/timeout does not. Developer mode and the internet/desktop gate are
unchanged (AC4/AC5).
"""
import asyncio
import json

import pytest

from backend import capabilities as _caps
from backend.agent import permissions as _perm


def _write_cfg(monkeypatch, tmp_path, content):
    cfg_path = tmp_path / "cfg.json"
    if content is not None:
        cfg_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(_caps, "_CFG_PATH", str(cfg_path))
    return cfg_path


@pytest.mark.asyncio
async def test_t23_capability_denial_escalates_to_permission(tmp_path, monkeypatch):
    """REQ-18 AC1/AC2/AC3: capability-blocked tool in personal mode escalates to a
    permission request; approval executes the tool; denial does not."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "personal"}))
    assert _caps.CapabilitySet.get_mode() == "personal"
    assert _caps.CapabilitySet.is_tool_allowed("write_file") is False  # capability-blocked

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.mcp.builtin_servers import FileManagerServer
    from backend.agent.permissions import get_permission_system

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    target = tmp_path / "out.txt"

    # --- DENY path: escalation denied -> tool does NOT execute ---
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "hi"},
            session_id="t23-deny", _skip_resilience=True,
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
    assert not target.exists()  # AC3: not executed

    # --- APPROVE path: escalation approved -> tool executes ---
    seen.clear()
    target2 = tmp_path / "out2.txt"
    task2 = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target2), "content": "hi"},
            session_id="t23-approve", _skip_resilience=True,
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
    assert result2.get("success") is True  # AC2: executed
    assert target2.exists()


@pytest.mark.asyncio
async def test_t23_internet_gate_not_escalated(tmp_path, monkeypatch):
    """REQ-18 AC5: the internet/desktop capability gate is unchanged — a tool blocked
    by it (not a permission question) is denied, not escalated to a permission request."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "personal"}))
    from backend.agent import tool_registry as _r
    monkeypatch.setattr(_r, "_internet_provider", lambda: False)

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    result = await bridge.execute_tool(
        "search", {"query": "x"}, session_id="t23-inet", _skip_resilience=True
    )
    # Denied by the internet/desktop gate, NOT escalated to a permission request
    assert result.get("success") is False
    assert seen == []  # no PERMISSION_REQUEST emitted


@pytest.mark.asyncio
async def test_t23_developer_mode_not_escalated(tmp_path, monkeypatch):
    """REQ-18 AC4: in developer mode a repo/terminal tool is NOT capability-denied by
    [13.3] (is_tool_allowed is True there) — it reaches Phase 4 and prompts there,
    instead of being escalated by the [13.3] gate. Developer behaviour is unchanged."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "developer"}))
    assert _caps.CapabilitySet.get_mode() == "developer"
    assert _caps.CapabilitySet.is_tool_allowed("write_file") is True  # [13.3] won't block

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.mcp.builtin_servers import FileManagerServer
    from backend.agent.permissions import get_permission_system

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    target = tmp_path / "out.txt"
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "hi"},
            session_id="t23-dev", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    # [13.3] does NOT deny in developer mode; the tool reaches Phase 4 and prompts
    # (SIDE_EFFECT requires approval in developer). A PERMISSION_REQUEST IS emitted,
    # but it originates from Phase 4, not the [13.3] escalation.
    assert len(seen) == 1
    rid = seen[0].data["request_id"]
    get_permission_system().respond_to_permission(rid, approved=True)
    result = await task
    assert result.get("success") is True  # approved -> executes
    assert target.exists()


@pytest.mark.asyncio
async def test_t23_both_gates_blocked_nonpermission_wins(tmp_path, monkeypatch):
    """REQ-18 edge: a tool blocked by BOTH [13.3] (capability) and the internet/desktop
    gate -> the non-permission (internet/desktop) denial takes precedence after the
    capability escalation is approved (it is not a permission question)."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "personal"}))
    # search requires internet (blocked by the internet gate by default in tests);
    # force it ALSO capability-blocked so [13.3] escalates first. This exercises the
    # real internet/desktop gate rather than a stubbed one.
    monkeypatch.setattr(
        _caps.CapabilitySet, "is_tool_allowed", classmethod(lambda cls, name: False)
    )

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent.permissions import get_permission_system

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    task = asyncio.create_task(
        bridge.execute_tool(
            "search", {"query": "x"},
            session_id="t23-both", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # [13.3] escalates (force=True)
    rid = seen[0].data["request_id"]
    get_permission_system().respond_to_permission(rid, approved=True)  # approve escalation
    result = await task
    # Non-permission (internet/desktop) gate wins -> denied, not executed
    assert result.get("success") is False
    assert "Internet access is disabled" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_t23_param_pattern_escalation_on_clearing_tool(tmp_path, monkeypatch):
    """REQ-18 edge: a tool that CLEARS [13.3] (not capability-blocked) but carries a
    destructive param pattern still escalates via Phase 4 (classify_tool -> DESTRUCTIVE)."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "personal"}))
    # search is READ_ONLY -> clears [13.3]; a destructive param pattern must still escalate.
    assert _caps.CapabilitySet.is_tool_allowed("search") is True
    from backend.agent import tool_registry as _r
    monkeypatch.setattr(_r, "_internet_provider", lambda: True)  # let search reach Phase 4

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent.permissions import get_permission_system, classify_tool

    # classify_tool escalates the tier on the destructive param pattern
    assert classify_tool("search", {"query": "rm -rf /tmp/foo"}) == _perm.PermissionTier.DESTRUCTIVE

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    task = asyncio.create_task(
        bridge.execute_tool(
            "search", {"query": "rm -rf /tmp/foo"},
            session_id="t23-param", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    # Personal mode: DESTRUCTIVE -> REQUIRE_APPROVAL, so Phase 4 prompts (escalation
    # works on a tool that clears [13.3]).
    assert len(seen) == 1
    rid = seen[0].data["request_id"]
    get_permission_system().respond_to_permission(rid, approved=False)
    result = await task
    assert result.get("success") is False
