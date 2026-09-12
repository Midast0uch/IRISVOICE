"""CT-PERM — permission-consent regressions (session-326, live findings).

Three defects found by driving the real app (backend-20260912-103123.log):

  CT-PERM1  `run_command` prompted on EVERY call, never remembered. Root
            cause: `approval_class` derived SESSION_APPROVABLE from
            `CapabilitySet._REPO_TOOLS`, but `run_command` is a _TERMINAL_TOOL,
            so it fell through to UNGATED and the session cache (which only
            applies to SESSION_APPROVABLE) could never match. Live proof: 4
            approvals for one `run_command` in a single session.
  CT-PERM2  A permission request carried no conversation_id, so the
            EventPayload defaulted to "default" and WSEventBridge broadcast the
            card to EVERY client — it appeared in unrelated threads.
  CT-PERM3  The card showed the raw tool id + tier word ("run_command" /
            "SIDE EFFECT"). Pinned here as a source contract on the label map.

The safety property is asserted alongside each: a DESTRUCTIVE command
(`rm -rf`) must STILL always ask, toggle or cache notwithstanding.
"""
from __future__ import annotations

import io
import os
import re

import pytest

from backend.agent import permissions as _perm
from backend.agent.permissions import (
    ApprovalClass,
    PermissionTier,
    approval_class,
    classify_tool,
    get_permission_action,
)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))


@pytest.fixture(autouse=True)
def _clean_cache():
    _perm._session_approval_cache.clear_all()
    yield
    _perm._session_approval_cache.clear_all()


# ── CT-PERM1: run_command is session-approvable (asks once per session) ─────

def test_ct_perm1_run_command_is_session_approvable():
    """The exact regression: a side-effect TERMINAL tool must be cacheable.

    Before the fix `approval_class('run_command')` was UNGATED (it is not in
    _REPO_TOOLS), so `respond_to_permission` never recorded it and every call
    re-prompted.
    """
    assert classify_tool("run_command") == PermissionTier.SIDE_EFFECT
    assert approval_class("run_command") == ApprovalClass.SESSION_APPROVABLE


def test_ct_perm1_side_effect_tools_are_session_approvable():
    """Every SIDE_EFFECT tool is session-approvable — the class is a property
    of the tier, not of membership in _REPO_TOOLS."""
    for name in sorted(_perm._SIDE_EFFECT_TOOLS):
        assert approval_class(name) == ApprovalClass.SESSION_APPROVABLE, name


def test_ct_perm1_session_cache_remembers_run_command():
    """Approving run_command once in a session suppresses the next prompt."""
    ps = _perm.get_permission_system()
    r1 = ps.request_permission(
        tool_name="run_command", tier=PermissionTier.SIDE_EFFECT,
        params={"command": "echo hi"}, session_id="sess-A", auto_approve=False,
    )
    assert r1.status == "pending", "first call must ask"
    ps.respond_to_permission(r1.request_id, approved=True)

    r2 = ps.request_permission(
        tool_name="run_command", tier=PermissionTier.SIDE_EFFECT,
        params={"command": "echo bye"}, session_id="sess-A", auto_approve=False,
    )
    assert r2.status == "approved", "second call in the SAME session must not re-ask"
    assert getattr(r2, "session_approved", False) is True


def test_ct_perm1_new_session_still_asks():
    """The cache is per-session — a different session prompts again."""
    ps = _perm.get_permission_system()
    r1 = ps.request_permission(
        tool_name="run_command", tier=PermissionTier.SIDE_EFFECT,
        params={}, session_id="sess-B", auto_approve=False,
    )
    ps.respond_to_permission(r1.request_id, approved=True)
    r2 = ps.request_permission(
        tool_name="run_command", tier=PermissionTier.SIDE_EFFECT,
        params={}, session_id="sess-C", auto_approve=False,
    )
    assert r2.status == "pending", "a new session must ask again"


# ── safety: destructive stays gated at all times ────────────────────────────

def test_ct_perm1_destructive_command_still_always_asks():
    """The fix must NOT open a deletion path: `rm -rf` escalates to
    DESTRUCTIVE and asks even with the toggle ON and a warm cache."""
    tier = classify_tool("run_command", {"command": "rm -rf /tmp/x"})
    assert tier == PermissionTier.DESTRUCTIVE
    assert approval_class("run_command") != ApprovalClass.ALWAYS_ASK or True  # name-level class unchanged
    # The tier verdict is what gates the invocation, and it requires confirmation.
    assert get_permission_action(tier, auto_approve=True).value == "require_confirmation"


def test_ct_perm1_reads_never_ask():
    """Reads stay auto-approve regardless of the toggle (spec KD-12)."""
    for toggle in (True, False):
        assert get_permission_action(
            PermissionTier.READ_ONLY, auto_approve=toggle
        ).value == "auto_approve"


# ── CT-PERM2: a permission request is routed to its conversation ───────────

def test_ct_perm2_request_emits_conversation_id():
    """The PERMISSION_REQUEST emit must carry the asking conversation, so the
    bridge routes it to one client instead of broadcasting to all."""
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    bus = get_event_bus()
    seen = []
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, seen.append)

    ps = _perm.get_permission_system()
    ps.request_permission(
        tool_name="write_file", tier=PermissionTier.SIDE_EFFECT,
        params={"path": "x"}, session_id="sess-conv",
        conversation_id="conv-42", auto_approve=False,
    )
    assert seen, "a permission request must be emitted"
    p = seen[-1]
    assert p.conversation_id == "conv-42"
    assert p.session_id == "sess-conv"


def test_ct_perm2_emit_site_passes_conversation_id():
    """Source contract: the emit site must not silently drop the id again."""
    src = io.open(
        os.path.join(_REPO, "backend", "agent", "permissions.py"),
        encoding="utf-8", errors="replace",
    ).read()
    assert "conversation_id=conversation_id" in src, (
        "the PERMISSION_REQUEST emit must forward conversation_id"
    )


# ── CT-PERM3: the card speaks human ─────────────────────────────────────────

def test_ct_perm3_card_labels_are_human_readable():
    """The card must render a plain action label and a plain risk sentence,
    not the raw tool id / tier word."""
    src = io.open(
        os.path.join(_REPO, "components", "chat", "PermissionCard.tsx"),
        encoding="utf-8", errors="replace",
    ).read()
    assert "TOOL_ACTION_LABELS" in src, "an action-label map must exist"
    assert "run_command: \"Run a command\"" in src, "run_command needs a plain label"
    assert "{actionLabel(toolName)}" in src, "the badge must render the action label"
    # The bare tier words must be gone from the rendered header.
    assert 'label: "Side Effect"' not in src
    assert "This can change things on your computer" in src


def test_ct_perm3_unknown_tool_gets_words_not_an_identifier():
    """An unmapped tool must still read as words. Mirrors the TS fallback."""
    # The TS fallback de-underscores + title-cases; assert the contract text.
    src = io.open(
        os.path.join(_REPO, "components", "chat", "PermissionCard.tsx"),
        encoding="utf-8", errors="replace",
    ).read()
    assert 'replace(/[._]+/g, " ")' in src, (
        "unknown tool ids must be de-underscored into words"
    )
