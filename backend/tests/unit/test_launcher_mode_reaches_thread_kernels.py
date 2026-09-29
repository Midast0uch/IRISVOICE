"""Regression (execution audit B7, 2026-09-29): developer mode must reach the
kernel that actually serves a conversation.

set_launcher_mode is only called on the "default" kernel; every conversation
kernel starts with _launcher_mode="personal" and nothing copied the mode over.
So the developer block (PROJECT.md, worktree, ladder) never reached a real
thread. The prompt now follows the persisted mode. Fails on the old code.
"""

from unittest.mock import patch

from backend.agent.agent_kernel import AgentKernel

MARKER = "DEV-CONTEXT-MARKER-7f3a"


def _thread_kernel():
    kernel = AgentKernel.__new__(AgentKernel)
    kernel._personality = None
    kernel._launcher_mode = "personal"  # what every conversation kernel starts with
    kernel._developer_context = MARKER  # cached PROJECT.md stand-in
    kernel.session_id = "sess"
    return kernel


def test_developer_mode_in_config_reaches_a_conversation_kernel():
    kernel = _thread_kernel()
    with patch("backend.capabilities.CapabilitySet.get_mode", return_value="developer"):
        prompt = kernel._build_system_prompt()
    assert "DEVELOPER MODE ACTIVE" in prompt
    assert MARKER in prompt


def test_personal_mode_in_config_keeps_the_developer_block_out():
    kernel = _thread_kernel()
    kernel._launcher_mode = "developer"  # a stale copy must not win either
    with patch("backend.capabilities.CapabilitySet.get_mode", return_value="personal"):
        prompt = kernel._build_system_prompt()
    assert "DEVELOPER MODE ACTIVE" not in prompt
    assert MARKER not in prompt
