"""Contract test: T20 — effective permission mode is truthful (REQ-16 AC3/AC4).

- Absent / malformed / unreadable config FAILS CLOSED to "developer" (the
  restrictive policy that requires approval for SIDE_EFFECT tools), never to
  "personal" (the most permissive policy that auto-approves).
- An explicitly selected mode is honoured verbatim.
- In developer mode every tool is allowed through the [13.3] capability gate
  (is_tool_allowed True), so it reaches Phase 4 and is gated there.
"""
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


def test_absent_mode_fails_closed_to_developer(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, json.dumps({"other_key": True}))
    assert _caps.CapabilitySet.get_mode() == "developer"


def test_malformed_mode_fails_closed_to_developer(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, "{bad json")
    assert _caps.CapabilitySet.get_mode() == "developer"


def test_unreadable_config_fails_closed_to_developer(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, None)
    assert _caps.CapabilitySet.get_mode() == "developer"


def test_explicit_personal_honoured(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "personal"}))
    assert _caps.CapabilitySet.get_mode() == "personal"


def test_explicit_developer_honoured(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "developer"}))
    assert _caps.CapabilitySet.get_mode() == "developer"


def test_developer_mode_allows_every_tool_through_capability_gate(tmp_path, monkeypatch):
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "developer"}))
    # In developer mode the [13.3] gate must not block repo/terminal tools,
    # so they reach Phase 4 and are gated there (REQ-16 AC4).
    for tool in _caps.CapabilitySet._REPO_TOOLS | _caps.CapabilitySet._TERMINAL_TOOLS:
        assert _caps.CapabilitySet.is_tool_allowed(tool) is True


def test_gated_call_logs_resolved_action(caplog, tmp_path, monkeypatch):
    """REQ-16 AC5: every gated tool call logs its resolved action (allow/ask)."""
    import asyncio
    import logging

    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
    from backend.agent.tool_bridge import AgentToolBridge

    monkeypatch.setattr(_perm, "PERMISSION_TIMEOUT_SIDE_EFFECT", 0.2)
    _write_cfg(monkeypatch, tmp_path, json.dumps({"mode": "developer"}))

    bus = get_event_bus()
    bus.subscribe(IRISStreamEvent.PERMISSION_REQUEST, lambda e: None)
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    bridge._initialized = True

    with caplog.at_level(logging.INFO, logger="backend.agent.tool_bridge"):
        asyncio.run(
            bridge.execute_tool(
                "edit_file",
                {"path": str(tmp_path / "x.txt"), "content": "hi"},
                session_id="log-probe",
                _skip_resilience=True,
            )
        )

    assert any("gated_call" in r.message for r in caplog.records)
    assert any("action=require_approval" in r.message for r in caplog.records)
