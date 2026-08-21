"""Contract tests: T24 — approval classes + per-session approval cache (REQ-19 AC1/AC2/AC7/AC8).

AC1  approval_class derives ALWAYS_ASK / SESSION_APPROVABLE / UNGATED from the
     existing tier/capability constants (no standalone hardcoded list).
AC2  a SESSION_APPROVABLE tool approved once is not asked again for the rest of
     the session, and the approval is discarded on restart (in-memory only).
AC7  precedence: ALWAYS_ASK always prompts (session approval never suppresses it).
AC8  ALWAYS_ASK tools never enter the cache — approving one records nothing, so
     the next call prompts again.
"""
import asyncio

import pytest

from backend.agent import permissions as _perm
from backend.agent.permissions import (
    ApprovalClass,
    SessionApprovalCache,
    approval_class,
)
from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.tool_bridge import AgentToolBridge
from backend.mcp.builtin_servers import FileManagerServer


def _clear_cache():
    _perm._session_approval_cache.clear_all()


@pytest.fixture(autouse=True)
def _clean_cache():
    _clear_cache()
    yield
    _clear_cache()


# ── AC1: derivation from tier/capability constants ──────────────────────────

def test_ac1_approval_class_derivation():
    """ALWAYS_ASK = destructive ∪ terminal; SESSION_APPROVABLE = repo − always_ask;
    everything else UNGATED. Derived, never a literal list."""
    # DESTRUCTIVE -> ALWAYS_ASK
    assert approval_class("delete_file") == ApprovalClass.ALWAYS_ASK
    assert approval_class("force_delete") == ApprovalClass.ALWAYS_ASK
    # TERMINAL -> ALWAYS_ASK
    assert approval_class("run_command") == ApprovalClass.ALWAYS_ASK
    assert approval_class("shutdown") == ApprovalClass.ALWAYS_ASK
    # REPO but not destructive/terminal -> SESSION_APPROVABLE
    assert approval_class("write_file") == ApprovalClass.SESSION_APPROVABLE
    assert approval_class("git_commit") == ApprovalClass.SESSION_APPROVABLE
    # READ_ONLY / ungated -> UNGATED
    assert approval_class("search") == ApprovalClass.UNGATED
    assert approval_class("read_file") == ApprovalClass.UNGATED


def test_ac1_classes_cannot_drift_from_tiers():
    """Because the classes are derived from the tier sets, a tool added to
    _DESTRUCTIVE_TOOLS automatically becomes ALWAYS_ASK (no second list to update)."""
    assert "delete_file" in _perm._DESTRUCTIVE_TOOLS
    # delete_file is in both _DESTRUCTIVE_TOOLS and _REPO_TOOLS, yet resolves to
    # ALWAYS_ASK (the union wins), proving the derivation is live, not duplicated.
    assert approval_class("delete_file") == ApprovalClass.ALWAYS_ASK
    assert "delete_file" not in _perm._SESSION_APPROVABLE_TOOLS


# ── AC8: ALWAYS_ASK never enters the cache ──────────────────────────────────

def test_ac8_always_ask_refused_by_cache():
    """Approving an ALWAYS_ASK tool records nothing; the cache write path refuses it."""
    cache = SessionApprovalCache()
    cache.record_approval("sess-1", "delete_file")
    cache.record_approval("sess-1", "run_command")
    assert cache.is_approved("sess-1", "delete_file") is False
    assert cache.is_approved("sess-1", "run_command") is False


# ── AC2: SESSION_APPROVABLE approved once per session ──────────────────────

@pytest.mark.asyncio
async def test_ac2_session_approvable_asked_once_per_session(tmp_path, monkeypatch):
    """A SESSION_APPROVABLE tool (write_file) approved in a session is not asked
    again for that session; a new session prompts again."""
    from backend import capabilities as _caps

    _write_cfg = tmp_path / "cfg.json"
    _write_cfg.write_text('{"mode": "developer"}', encoding="utf-8")
    monkeypatch.setattr(_caps, "_CFG_PATH", str(_write_cfg))

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    target = tmp_path / "out.txt"

    # First call in session S1 -> prompts, user approves -> cached.
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "hi"},
            session_id="S1", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1
    _perm.get_permission_system().respond_to_permission(seen[0].data["request_id"], approved=True)
    result = await task
    assert result.get("success") is True
    seen.clear()

    # Second call in the SAME session S1 -> cache hit, no prompt.
    task2 = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "again"},
            session_id="S1", _skip_resilience=True,
        )
    )
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 0  # session approval beats prompting
    result2 = await task2
    assert result2.get("success") is True

    # A DIFFERENT session S2 -> not cached, prompts again.
    task3 = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "s2"},
            session_id="S2", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # new session -> prompts
    _perm.get_permission_system().respond_to_permission(seen[0].data["request_id"], approved=True)
    result3 = await task3
    assert result3.get("success") is True


@pytest.mark.asyncio
async def test_ac2_approval_discarded_on_restart(tmp_path, monkeypatch):
    """The cache is in-memory only; a fresh process (empty cache) prompts again."""
    from backend import capabilities as _caps

    _write_cfg = tmp_path / "cfg.json"
    _write_cfg.write_text('{"mode": "developer"}', encoding="utf-8")
    monkeypatch.setattr(_caps, "_CFG_PATH", str(_write_cfg))

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    target = tmp_path / "out.txt"

    # Approve in session S, then simulate restart by clearing the module cache.
    task = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "hi"},
            session_id="S", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1
    _perm.get_permission_system().respond_to_permission(seen[0].data["request_id"], approved=True)
    await task
    seen.clear()

    # "Restart": clear the in-memory cache.
    _perm._session_approval_cache.clear_all()

    # Same session S now prompts again (cache was discarded on restart).
    task2 = asyncio.create_task(
        bridge.execute_tool(
            "write_file", {"path": str(target), "content": "after-restart"},
            session_id="S", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # cache discarded -> prompts again


# ── AC7: precedence — ALWAYS_ASK always prompts (cache never suppresses) ─────

@pytest.mark.asyncio
async def test_ac7_always_ask_beats_session_cache(tmp_path, monkeypatch):
    """An ALWAYS_ASK tool (run_command) is asked every time, even if a prior
    approval was recorded (it never is) — session approval never suppresses it."""
    from backend import capabilities as _caps

    _write_cfg = tmp_path / "cfg.json"
    _write_cfg.write_text('{"mode": "developer"}', encoding="utf-8")
    monkeypatch.setattr(_caps, "_CFG_PATH", str(_write_cfg))

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    # First call: prompts (ALWAYS_ASK). Approve.
    task = asyncio.create_task(
        bridge.execute_tool(
            "run_command", {"command": "echo hi"},
            session_id="S", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1
    _perm.get_permission_system().respond_to_permission(seen[0].data["request_id"], approved=True)
    await task
    seen.clear()

    # Second call in same session: ALWAYS_ASK -> prompts AGAIN (cache refused it).
    task2 = asyncio.create_task(
        bridge.execute_tool(
            "run_command", {"command": "echo again"},
            session_id="S", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # ALWAYS_ASK always prompts
    _perm.get_permission_system().respond_to_permission(seen[0].data["request_id"], approved=True)
    await task2
