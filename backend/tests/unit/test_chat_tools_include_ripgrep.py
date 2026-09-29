"""Regression (execution audit, 2026-09-29): developer chat can search code.

grep_files / glob_files (ripgrep) were registered for the DER path only; the
chat path's tool list never had them. Fails on that code.
"""

from unittest.mock import patch

from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tool_registry import register_builtin_tools


def _names(developer: bool):
    register_builtin_tools()
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    with patch("backend.capabilities.CapabilitySet.is_developer", return_value=developer), \
         patch("backend.capabilities.CapabilitySet.blocked_tools", return_value=set()):
        return {t["name"] for t in bridge.get_available_tools()}


def test_developer_chat_has_ripgrep_search():
    names = _names(developer=True)
    assert {"grep_files", "glob_files"} <= names


def test_personal_chat_is_unchanged():
    assert "grep_files" not in _names(developer=False)
