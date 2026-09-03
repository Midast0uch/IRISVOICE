"""Contract tests: T25 — persist + re-validate standing approved-tools list (REQ-19 AC3/AC4/AC6).

AC3  a tool on the standing list is auto-approved for every session (no prompt).
AC4  an ALWAYS_ASK tool named on the standing list (even hand-edited into the
     config) is rejected at READ time and still prompts.
AC6  an unreadable config yields an empty standing list and the system still
     prompts — never 'everything approved'.
Edge the standing list is re-read on every call, so a mid-session edit takes effect.
"""
import asyncio
import json

import pytest

from backend.agent import permissions as _perm
from backend.agent.permissions import ApprovalClass
from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.tool_bridge import AgentToolBridge
from backend.mcp.builtin_servers import FileManagerServer
from backend.capabilities import CapabilitySet


def _write_cfg(monkeypatch, tmp_path, data: dict):
    p = tmp_path / "iris_config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("backend.capabilities._CFG_PATH", str(p))


@pytest.fixture(autouse=True)
def _clean_cache():
    _perm._session_approval_cache.clear_all()
    yield
    _perm._session_approval_cache.clear_all()


# ── AC4: ALWAYS_ASK on the standing list is rejected on read ────────────────

def test_ac4_always_ask_rejected_on_read(monkeypatch, tmp_path):
    """A hand-edited config naming an ALWAYS_ASK tool must be dropped at read time."""
    _write_cfg(monkeypatch, tmp_path, {"mode": "personal", "approved_tools": ["delete_file", "run_command"]})
    standing = _perm._get_standing_approved_tools()
    assert "delete_file" not in standing
    assert "run_command" not in standing
    assert standing == set()


async def test_ac4_always_ask_not_honoured_via_standing_list(monkeypatch, tmp_path):
    """delete_file (ALWAYS_ASK) on the standing list still prompts — never auto-approved."""
    _write_cfg(monkeypatch, tmp_path, {"mode": "personal", "approved_tools": ["delete_file"]})
    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True
    task = asyncio.create_task(
        bridge.execute_tool("delete_file", {"path": "x"}, session_id="t25-ac4", _skip_resilience=True)
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # still prompts
    rid = seen[0].data["request_id"]
    _perm.get_permission_system().respond_to_permission(rid, approved=False)
    result = await task
    assert result.get("success") is False


# ── AC6: unreadable config -> empty list, still prompt ──────────────────────

async def test_ac6_unreadable_config_empty_and_prompts(monkeypatch, tmp_path):
    """An unreadable config yields an empty standing list; a SESSION_APPROVABLE tool
    still prompts (never 'everything approved')."""
    monkeypatch.setattr("backend.capabilities._CFG_PATH", str(tmp_path))  # a directory -> open() fails
    assert _perm._get_standing_approved_tools() == set()

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": "y", "content": "z"},
            session_id="t25-ac6", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # still prompts (not auto-approved)
    rid = seen[0].data["request_id"]
    _perm.get_permission_system().respond_to_permission(rid, approved=True)
    result = await task
    assert result.get("success") is True


# ── AC3: standing list persisted -> tool auto-approved (no prompt) ──────────

async def test_ac3_standing_list_auto_approves(monkeypatch, tmp_path):
    """A SESSION_APPROVABLE tool on the standing list is auto-approved every session."""
    _write_cfg(monkeypatch, tmp_path, {"mode": "personal", "approved_tools": ["write_file"]})
    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": "w", "content": "v"},
            session_id="t25-ac3", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 0  # no prompt — auto-approved from standing list
    result = await task
    assert result.get("success") is True


# ── Edge: standing list edited mid-session -> next call uses the new list ──

async def test_edge_standing_list_reread_mid_session(monkeypatch, tmp_path):
    """The standing list is re-read on every call, so a mid-session edit takes effect."""
    p = tmp_path / "iris_config.json"
    p.write_text(json.dumps({"mode": "personal", "approved_tools": ["write_file"]}), encoding="utf-8")
    monkeypatch.setattr("backend.capabilities._CFG_PATH", str(p))

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    # First call: write_file is on the standing list -> auto-approved (no prompt)
    task1 = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": "a", "content": "1"},
            session_id="t25-edge", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 0
    await task1

    # Edit the config to remove write_file; the next call re-reads and now prompts
    p.write_text(json.dumps({"mode": "personal", "approved_tools": []}), encoding="utf-8")
    task2 = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": "b", "content": "2"},
            session_id="t25-edge", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # now prompts (list changed mid-session)
    rid = seen[0].data["request_id"]
    _perm.get_permission_system().respond_to_permission(rid, approved=True)
    result2 = await task2
    assert result2.get("success") is True
