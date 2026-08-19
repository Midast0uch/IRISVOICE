"""BASELINE — Wave 0, specs/task-card-v2-liquid-ink.

Pins behavior as of 2026-08-19. Asserts what the code DOES today, including
the defects. EXPECTED TO FAIL once T20 lands. Editing this file is
sanctioned ONLY by T20, and that edit MUST be called out in that task's
report.

Pins the user-reported symptom: "the permission gate has never once asked
me." Three independent silent-permissive paths, verified against source:

  1. backend/capabilities.py CapabilitySet.get_mode() (~line 66) — an
     ABSENT, missing, or malformed "mode" key resolves to "personal", the
     MOST PERMISSIVE policy, instead of failing safe.
  2. backend/agent/permissions.py permission_level_from_config() (~line 191)
     is an orphaned resolver that unconditionally returns "developer" (both
     branches). The LIVE gate (tool_bridge.py Phase 4) uses
     CapabilitySet.get_mode() instead — the two resolvers disagree, and the
     permissive one (get_mode -> "personal" -> SIDE_EFFECT auto-approves) is
     the one that actually runs.
  3. backend/agent/tool_bridge.py Phase 4 (~lines 1168-1210) wraps the whole
     permission check in a bare `except Exception` that logs a warning and
     falls through — any error inside the gate silently PERMITS execution.

Inverted by: T20
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

def test_missing_mode_key_resolves_to_personal(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, json.dumps({"other_key": True}))
    assert _caps.CapabilitySet.get_mode() == "personal"


def test_absent_config_file_resolves_to_personal(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, content=None)  # file never created
    assert _caps.CapabilitySet.get_mode() == "personal"


def test_malformed_config_resolves_to_personal(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, content="{not valid json,,,")
    assert _caps.CapabilitySet.get_mode() == "personal"


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


# ── 2. Orphaned, divergent level resolver ───────────────────────────────

def test_permission_level_from_config_disagrees_with_get_mode(tmp_path, monkeypatch):
    """permission_level_from_config() always says "developer"; get_mode()
    (fed the same absent-mode config) says "personal". The two resolvers
    disagree, and Phase 4 (test below) uses the permissive one."""
    _write_cfg(monkeypatch, tmp_path, json.dumps({}))
    assert _perm.permission_level_from_config() == "developer"
    assert _caps.CapabilitySet.get_mode() == "personal"


def test_permission_level_from_config_has_no_external_caller():
    """Grep the backend/ tree: the only call site is permissions.py's own
    internal fallback (`level or permission_level_from_config()` inside
    `request_permission`), which the live gate never hits because Phase 4
    always passes `level=` explicitly (see test below). No file outside
    permissions.py calls it."""
    this_file = os.path.abspath(__file__)
    callers = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(_REPO_ROOT, "backend")):
        if "__pycache__" in dirpath:
            continue
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fname)
            if fpath in (_PERMISSIONS_PATH, this_file):
                continue  # the resolver's own file + this test (which names it in prose)
            with open(fpath, "r", encoding="utf-8") as f:
                src = f.read()
            if "permission_level_from_config(" in src:
                callers.append(fpath)
    assert callers == [], f"Unexpected external callers of the orphaned resolver: {callers}"


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
    assert raises == [], "Phase 4's except handler must not re-raise (pinning fail-open)"

    # ...and does not return a failure — execution falls through to the
    # rest of execute_tool, silently permitting the tool.
    returns = [n for n in ast.walk(handler) if isinstance(n, ast.Return)]
    assert returns == [], "Phase 4's except handler must not return (pinning fail-open)"


# ── 4. End-to-end symptom ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_file_no_permission_request_with_absent_mode(tmp_path, monkeypatch):
    """Drive the real tool_bridge path for write_file with a config
    carrying no "mode", subscribed to the event bus.

    REALITY DIFFERS FROM THE NAIVE READING OF THE SYMPTOM: write_file is
    also listed in capabilities.py's `_REPO_TOOLS`, so in "personal" mode
    (what get_mode() resolves to with no "mode" key) it is blocked by the
    EARLIER [13.3] capability gate (tool_bridge.py ~line 1109) before
    Phase 4's permission check ever runs. So for write_file specifically:
    NO PERMISSION_REQUEST is emitted (true, as expected) AND the tool does
    NOT proceed — it is rejected with an error, not silently executed.
    Phase 4 is simply unreached for this tool in personal mode; the "never
    asks" symptom is real but its immediate cause here is the [13.3] gate,
    not Phase 4 silently approving. Every OTHER real, dispatchable
    SIDE_EFFECT tool in personal mode (e.g. run_command, create_directory)
    is likewise blocked by [13.3] before reaching Phase 4 — they are all
    also members of capabilities.py's _REPO_TOOLS / _TERMINAL_TOOLS. This
    is reported as a discrepancy from the task brief, which assumed
    write_file would silently AUTO-APPROVE and proceed.
    """
    _write_cfg(monkeypatch, tmp_path, json.dumps({}))

    from backend.agent.tool_bridge import AgentToolBridge
    from backend.mcp.builtin_servers import FileManagerServer
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    bridge = AgentToolBridge()
    bridge._mcp_servers = {"file_manager": FileManagerServer()}
    bridge._initialized = True

    bus = get_event_bus()
    seen = []
    listener = seen.append
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, listener)
    try:
        target = tmp_path / "out.txt"
        result = await bridge.execute_tool(
            "write_file",
            {"path": str(target), "content": "hello"},
            session_id="baseline-probe",
            _skip_resilience=True,
        )
    finally:
        bus.unsubscribe(IRISStreamEvent.PERMISSION_REQUEST, listener)

    # No permission request — but NOT because the gate auto-approved. It
    # never ran: the [13.3] capability gate rejected the tool first.
    assert seen == []
    assert result.get("success") is False
    assert "personal mode" in result.get("error", "")
    assert not target.exists()


@pytest.mark.asyncio
async def test_side_effect_tool_reaching_phase4_auto_approves_silently(tmp_path, monkeypatch):
    """A SIDE_EFFECT-classified tool name that is NOT one of capabilities.py's
    blocked _REPO_TOOLS/_TERMINAL_TOOLS DOES reach Phase 4 in personal mode
    (with no "mode" key) and is auto-approved with no PERMISSION_REQUEST —
    this is the actual Phase-4-silently-approves symptom the brief
    describes, demonstrated on a tool that clears the earlier [13.3] gate.
    `edit_file` is in permissions.py's `_SIDE_EFFECT_TOOLS` but not in
    capabilities.py's blocked sets, and is not wired to a real dispatcher in
    tool_bridge.py, so it falls through to the "Unknown tool" branch AFTER
    Phase 4 has already silently approved it — proving the gate itself
    never asked.
    """
    _write_cfg(monkeypatch, tmp_path, json.dumps({}))
    assert "edit_file" not in (_caps.CapabilitySet._REPO_TOOLS | _caps.CapabilitySet._TERMINAL_TOOLS)
    assert "edit_file" in _perm._SIDE_EFFECT_TOOLS

    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    bus = get_event_bus()
    seen = []
    listener = seen.append
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, listener)
    try:
        result = await bridge.execute_tool(
            "edit_file", {"path": str(tmp_path / "x.txt"), "content": "hi"},
            session_id="baseline-probe-2", _skip_resilience=True,
        )
    finally:
        bus.unsubscribe(IRISStreamEvent.PERMISSION_REQUEST, listener)

    # Phase 4 ran, classified SIDE_EFFECT, auto-approved in personal mode —
    # no PERMISSION_REQUEST — and the tool "proceeded" past the gate (it
    # just has no real dispatcher wired, an unrelated gap).
    assert seen == []
    assert result.get("success") is not True
    assert "Unknown tool" in result.get("error", "")


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
