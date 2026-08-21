"""PERMISSION MODE BINDING — specs/task-card-v2-liquid-ink.

Pins the CORRECTED behavior after T20 (2026-08-19, session 240). The
user-reported symptom "the permission gate has never once asked me" was
caused by three silent-permissive paths; T20 closed two of them:

  1. CapabilitySet.get_mode() now FAILS CLOSED to "developer" (the more
     restrictive policy that requires approval for SIDE_EFFECT tools) when
     the mode key is absent, malformed, or the config is unreadable — never
     to "personal" (the most permissive policy).
  2. permission_level_from_config() (orphaned, always "developer") was
     DELETED; the live gate uses CapabilitySet.get_mode() exclusively.

The third path (Phase 4 fails open on exception) is addressed by REQ-17/T22,
not T20. The [13.3] hard-deny is addressed by REQ-18/T23.

Sanctioned edit by T20: the three "resolves_to_personal" assertions were
inverted to "resolves_to_developer", and the two orphaned-resolver tests
were removed because the function no longer exists.
"""

from __future__ import annotations

import ast
import json
import os

import pytest

from backend import capabilities as _caps
from backend.agent import permissions as _perm


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
_TOOL_BRIDGE_PATH = os.path.join(_REPO_ROOT, "backend", "agent", "tool_bridge.py")
_PERMISSIONS_PATH = os.path.join(_REPO_ROOT, "backend", "agent", "permissions.py")


# ── Isolation ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset the permission-system singleton and event-bus subscribers per
    test. Never touches the real data/iris_config.json — every test that
    needs a config points CapabilitySet at a tmp_path file via monkeypatch."""
    from backend.agent import event_bus as _eb

    _perm.reset_permission_system_for_testing()
    _eb.reset_event_bus_for_testing()
    yield
    _perm.reset_permission_system_for_testing()
    _eb.reset_event_bus_for_testing()


def _write_cfg(monkeypatch, tmp_path, content: str | None, filename: str = "cfg.json"):
    """Point CapabilitySet at a tmp config file. `content=None` means the
    file is never created (absent-file case)."""
    cfg_path = tmp_path / filename
    if content is not None:
        cfg_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(_caps, "_CFG_PATH", str(cfg_path))
    return cfg_path


# ── 1. Missing/absent/malformed mode -> "personal" (most permissive) ───

def test_missing_mode_key_resolves_to_developer(tmp_path, monkeypatch):
    """REQ-16 AC3: absent mode key must NOT resolve to the most permissive
    policy ("personal"). Fail CLOSED to "developer" (asks for SIDE_EFFECT)."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({"other_key": True}))
    assert _caps.CapabilitySet.get_mode() == "developer"


def test_absent_config_file_resolves_to_developer(tmp_path, monkeypatch):
    """REQ-16 edge case: unreadable/absent config fails CLOSED to developer."""
    _write_cfg(monkeypatch, tmp_path, content=None)  # file never created
    assert _caps.CapabilitySet.get_mode() == "developer"


def test_malformed_config_resolves_to_developer(tmp_path, monkeypatch):
    """REQ-16 edge case: malformed config fails CLOSED to developer."""
    _write_cfg(monkeypatch, tmp_path, content="{not valid json,,,")
    assert _caps.CapabilitySet.get_mode() == "developer"


def test_missing_mode_consequence_side_effect_tools_auto_approve():
    """The consequence, driven off the real module constants: EVERY tool in
    permissions.py's `_SIDE_EFFECT_TOOLS` classifies as SIDE_EFFECT, and
    SIDE_EFFECT auto-approves in "personal" mode."""
    for tool_name in _perm._SIDE_EFFECT_TOOLS:
        tier = _perm.classify_tool(tool_name, {})
        assert tier == _perm.PermissionTier.SIDE_EFFECT, (
            f"{tool_name} did not classify as SIDE_EFFECT: {tier}"
        )
        action = _perm.get_permission_action(tier, "personal")
        assert action == _perm.PermissionAction.AUTO_APPROVE, (
            f"{tool_name}: expected AUTO_APPROVE in personal mode, got {action}"
        )
    # write_file is the headline example named in the spec.
    assert "write_file" in _perm._SIDE_EFFECT_TOOLS


# ── 2. (removed by T20) orphaned permission_level_from_config() deleted ──

# ── 3. Phase 4 uses get_mode(), not the orphaned resolver ──────────────

def _find_phase4_try(tree: ast.AST) -> ast.Try:
    """Locate the Phase 4 permission check's try/except by its unique
    warning string, independent of line numbers."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            for stmt in ast.walk(handler):
                if (
                    isinstance(stmt, ast.Call)
                    and isinstance(stmt.func, ast.Attribute)
                    and stmt.func.attr == "warning"
                ):
                    for arg in stmt.args:
                        if (
                            isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)
                            and "Permission check failed" in arg.value
                        ):
                            return node
    raise AssertionError(
        "Could not locate the Phase 4 permission try/except in "
        f"{_TOOL_BRIDGE_PATH} — has the warning message changed?"
    )


def _call_attr_names(stmts: list) -> set[str]:
    """All `<obj>.<name>(...)` call attribute names across a list of
    statements (e.g. `try_node.body`, which is not itself an ast.AST node
    and can't be passed to ast.walk directly)."""
    names: set[str] = set()
    for stmt in stmts:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                names.add(sub.func.attr)
    return names


def test_phase4_uses_get_mode_not_config_resolver():
    with open(_TOOL_BRIDGE_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=_TOOL_BRIDGE_PATH)

    phase4 = _find_phase4_try(tree)
    called = _call_attr_names(phase4.body)  # try body only, not the except handler

    assert "get_mode" in called, "Phase 4 must call CapabilitySet.get_mode()"
    assert "permission_level_from_config" not in called

    # request_permission() must be called with an explicit `level=` kwarg —
    # this is WHY the orphaned resolver's internal fallback never fires from
    # the live path.
    found_level_kwarg = False
    for stmt in ast.walk(phase4):
        if (
            isinstance(stmt, ast.Call)
            and isinstance(stmt.func, ast.Attribute)
            and stmt.func.attr == "request_permission"
        ):
            found_level_kwarg = any(kw.arg == "level" for kw in stmt.keywords)
    assert found_level_kwarg, "request_permission(...) must pass level= explicitly"


# ── 3b. The gate fails open ─────────────────────────────────────────────

def test_phase4_fails_open_on_any_exception():
    with open(_TOOL_BRIDGE_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=_TOOL_BRIDGE_PATH)

    phase4 = _find_phase4_try(tree)

    assert len(phase4.handlers) == 1
    handler = phase4.handlers[0]
    # `except Exception:` — catches everything, no filtering by type.
    assert isinstance(handler.type, ast.Name) and handler.type.id == "Exception"

    # Does not re-raise...
    raises = [n for n in ast.walk(handler) if isinstance(n, ast.Raise)]
    assert raises == [], "Phase 4's except handler must not re-raise"

    # ...and FAILS CLOSED: it returns a denial (success=False), never silently
    # permits the tool. T22 inverted the old fail-open (which fell through to
    # execute_tool and permitted the tool).
    returns = [n for n in ast.walk(handler) if isinstance(n, ast.Return)]
    assert returns != [], "Phase 4's except handler must return a denial (fail closed)"
    fail_closed = False
    for ret in returns:
        val = ret.value
        if isinstance(val, ast.Dict):
            keys = [k.value for k in val.keys if isinstance(k, ast.Constant)]
            if "success" in keys and "permission_response" in keys:
                fail_closed = True
    assert fail_closed, "Phase 4's except handler must return a failure dict (fail closed)"


# ── 4. End-to-end symptom ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_file_reaches_permission_gate_in_absent_mode(tmp_path, monkeypatch):
    """T20 INVERTS the old silent-block. With no "mode" key the backend now
    fails CLOSED to "developer" (REQ-16 AC3), so write_file CLEARS the [13.3]
    capability gate (is_tool_allowed True) and REACHES Phase 4, which emits a
    PERMISSION_REQUEST — the gate now ASKS instead of silently blocking.

    The permission timeout is shortened so the test does not wait 30s for a
    real user response that never arrives in a headless probe.
    """
    monkeypatch.setattr(_perm, "PERMISSION_TIMEOUT_SIDE_EFFECT", 0.2)
    _write_cfg(monkeypatch, tmp_path, json.dumps({}))
    assert _caps.CapabilitySet.get_mode() == "developer"

    from backend.agent.tool_bridge import AgentToolBridge
    from backend.mcp.builtin_servers import FileManagerServer
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    try:
        target = tmp_path / "out.txt"
        await bridge.execute_tool(
            "write_file",
            {"path": str(target), "content": "hello"},
            session_id="baseline-probe",
            _skip_resilience=True,
        )
    finally:
        bus.unsubscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)

    # The gate is now REACHED and ASKS (was silently blocked before T20).
    assert len(seen) == 1
    assert seen[0].event == IRISStreamEvent.PERMISSION_REQUEST


@pytest.mark.asyncio
async def test_side_effect_tool_reaching_phase4_asks_in_developer_mode(tmp_path, monkeypatch):
    """T20 INVERTS the old silent-approve. A SIDE_EFFECT tool that clears the
    [13.3] gate now reaches Phase 4 and REQUIRES_APPROVAL (emits a
    PERMISSION_REQUEST) in developer mode — it no longer auto-approves
    silently. `edit_file` is in `_SIDE_EFFECT_TOOLS` but not in the blocked
    sets, so it clears [13.3] and exercises Phase 4 directly.
    """
    monkeypatch.setattr(_perm, "PERMISSION_TIMEOUT_SIDE_EFFECT", 0.2)
    _write_cfg(monkeypatch, tmp_path, json.dumps({}))
    assert "edit_file" not in (_caps.CapabilitySet._REPO_TOOLS | _caps.CapabilitySet._TERMINAL_TOOLS)
    assert "edit_file" in _perm._SIDE_EFFECT_TOOLS
    assert _caps.CapabilitySet.get_mode() == "developer"

    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)
    try:
        await bridge.execute_tool(
            "edit_file", {"path": str(tmp_path / "x.txt"), "content": "hi"},
            session_id="baseline-probe-2", _skip_resilience=True,
        )
    finally:
        bus.unsubscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)

    # Phase 4 ran, classified SIDE_EFFECT, and REQUIRES_APPROVAL in developer
    # mode — a PERMISSION_REQUEST is emitted (was silent before T20).
    assert len(seen) == 1
    assert seen[0].event == IRISStreamEvent.PERMISSION_REQUEST


# ── 5. Contrast case: the gate is not simply dead ───────────────────────

def test_destructive_requires_approval_in_personal_mode():
    action = _perm.get_permission_action(_perm.PermissionTier.DESTRUCTIVE, "personal")
    assert action == _perm.PermissionAction.REQUIRE_APPROVAL


def test_destructive_param_pattern_escalates_tier():
    """Driven off the real module constant so the test tracks the list."""
    assert len(_perm._DESTRUCTIVE_PARAM_PATTERNS) > 0
    for pattern in _perm._DESTRUCTIVE_PARAM_PATTERNS:
        tier = _perm.classify_tool("write_file", {"command": f"please {pattern} now"})
        assert tier == _perm.PermissionTier.DESTRUCTIVE, (
            f"pattern {pattern!r} did not escalate write_file to DESTRUCTIVE: {tier}"
        )
