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
    """Goal-contract T18 (REQ-9 AC9.4, KD-12) supersedes the old union rule:
    ALWAYS_ASK = the DESTRUCTIVE tier ONLY (the terminal/GUI tools left
    always-ask and come under the Auto-approve toggle). SESSION_APPROVABLE =
    repo − always_ask; everything else UNGATED. Derived, never a literal list."""
    # DESTRUCTIVE -> ALWAYS_ASK
    assert approval_class("delete_file") == ApprovalClass.ALWAYS_ASK
    assert approval_class("force_delete") == ApprovalClass.ALWAYS_ASK
    # A tool the REGISTRY declares destructive is always-ask too (CT-12): the
    # approval class shares classify_tool's verdict, so the terminal/system
    # tools cannot be UNGATED just because they left CapabilitySet._TERMINAL_TOOLS.
    assert approval_class("shutdown") == ApprovalClass.ALWAYS_ASK
    assert approval_class("lock_screen") == ApprovalClass.ALWAYS_ASK
    # A harmless shell command is NOT destructive -> not always-ask; its
    # consent comes from the Auto-approve toggle (T18).
    assert approval_class("run_command") != ApprovalClass.ALWAYS_ASK
    # REPO but not destructive -> SESSION_APPROVABLE
    assert approval_class("write_file") == ApprovalClass.SESSION_APPROVABLE
    assert approval_class("git_commit") == ApprovalClass.SESSION_APPROVABLE
    # READ_ONLY / ungated -> UNGATED
    assert approval_class("search") == ApprovalClass.UNGATED
    assert approval_class("read_file") == ApprovalClass.UNGATED
    # The always-ask set is exactly the destructive tier (CT-GC10 lock).
    assert _perm._ALWAYS_ASK_TOOLS == set(_perm._DESTRUCTIVE_TOOLS)


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
    """Approving an ALWAYS_ASK (destructive) tool records nothing; the cache
    write path refuses it. A terminal tool is SESSION_APPROVABLE under
    goal-contract T18 and therefore IS cacheable."""
    cache = SessionApprovalCache()
    cache.record_approval("sess-1", "delete_file")
    cache.record_approval("sess-1", "run_command")
    assert cache.is_approved("sess-1", "delete_file") is False
    # run_command left always-ask (T18): it is no longer the DESTRUCTIVE tier,
    # so the cache accepts it (its consent comes from the tier/toggle path).
    assert approval_class("run_command") != ApprovalClass.ALWAYS_ASK
    assert cache.is_approved("sess-1", "run_command") is True


# ── AC2: SESSION_APPROVABLE approved once per session ──────────────────────

@pytest.mark.asyncio
async def test_ac2_session_approvable_asked_once_per_session(
    tmp_path, monkeypatch, approval_ui_attached
):
    """A SESSION_APPROVABLE tool (write_file) approved in a session is not asked
    again for that session; a new session prompts again."""
    from backend import capabilities as _caps

    _write_cfg = tmp_path / "cfg.json"
    # Session-331: explicit auto_approve=False so the session-cache flow under
    # test is exercised (the shipped default is now ON).
    _write_cfg.write_text('{"mode": "developer", "auto_approve": false}', encoding="utf-8")
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
async def test_ac2_approval_discarded_on_restart(
    tmp_path, monkeypatch, approval_ui_attached
):
    """The cache is in-memory only; a fresh process (empty cache) prompts again."""
    from backend import capabilities as _caps

    _write_cfg = tmp_path / "cfg.json"
    # Session-331: explicit auto_approve=False so the restart-cache flow under
    # test is exercised (the shipped default is now ON).
    _write_cfg.write_text('{"mode": "developer", "auto_approve": false}', encoding="utf-8")
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


# ── AC7: precedence — destructive (ALWAYS_ASK) always prompts ───────────────

@pytest.mark.asyncio
async def test_ac7_destructive_beats_session_cache(
    tmp_path, monkeypatch, approval_ui_attached
):
    """Goal-contract T18 (REQ-9 AC9.4): the DESTRUCTIVE tier stays gated at
    all times — a prior approval never suppresses the prompt, even with the
    Auto-approve toggle ON. (run_command with a harmless command left the
    always-ask set; the destructive-command detector is what keeps deletion
    forms gated.)"""
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

    # First call: delete_file is DESTRUCTIVE -> prompts.
    task = asyncio.create_task(
        bridge.execute_tool(
            "delete_file", {"path": "x"},
            session_id="S", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1
    _perm.get_permission_system().respond_to_permission(
        seen[0].data["request_id"], approved=True
    )
    await task
    seen.clear()

    # Second call: DESTRUCTIVE -> prompts AGAIN (never cached).
    task2 = asyncio.create_task(
        bridge.execute_tool(
            "delete_file", {"path": "y"},
            session_id="S", _skip_resilience=True,
        )
    )
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.02)
    assert len(seen) == 1  # destructive always prompts
    _perm.get_permission_system().respond_to_permission(
        seen[0].data["request_id"], approved=True
    )
    await task2
