"""Regression (execution audit, 2026-09-29): a developer-mode CHAT message
binds the open project folder, the same way /run does.

Before, only dev_cli called set_session_workdir, so plain developer chat ran
every tool against the IRIS repo. bind_chat_workdir did not exist.
"""

from unittest.mock import MagicMock, patch

from backend.dev.orchestrator import bind_chat_workdir


def _bridge():
    bridge = MagicMock()
    return bridge, patch("backend.agent.tool_bridge.get_agent_tool_bridge", return_value=bridge)


def test_developer_chat_binds_an_existing_folder(tmp_path):
    bridge, p = _bridge()
    with p, patch("backend.capabilities.CapabilitySet.is_developer", return_value=True):
        assert bind_chat_workdir("sess", str(tmp_path)) is True
    bridge.set_session_workdir.assert_called_once_with("sess", str(tmp_path))


def test_personal_mode_never_binds(tmp_path):
    bridge, p = _bridge()
    with p, patch("backend.capabilities.CapabilitySet.is_developer", return_value=False):
        assert bind_chat_workdir("sess", str(tmp_path)) is False
    bridge.set_session_workdir.assert_not_called()


def test_missing_folder_is_refused(tmp_path):
    bridge, p = _bridge()
    with p, patch("backend.capabilities.CapabilitySet.is_developer", return_value=True):
        assert bind_chat_workdir("sess", str(tmp_path / "nope")) is False
    bridge.set_session_workdir.assert_not_called()
