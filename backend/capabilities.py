"""Launcher mode capability gating — Domain 13.3.

Centralised authority for what is allowed in personal vs developer mode.
"""

from __future__ import annotations

import json
import os
from typing import Set

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "iris_config.json",
)


class CapabilitySet:
    """Named capabilities used across the backend."""

    TTS = "tts"
    VOICE = "voice"
    CHAT = "chat"
    TERMINAL = "terminal"
    REPO_ACCESS = "repo_access"

    # Personal mode gets the basic three
    _PERSONAL: Set[str] = {TTS, VOICE, CHAT}

    # Developer mode gets everything
    _DEVELOPER: Set[str] = {TTS, VOICE, CHAT, TERMINAL, REPO_ACCESS}

    # Tools that require REPO_ACCESS in developer mode
    _REPO_TOOLS: Set[str] = {
        "write_file",
        "create_directory",
        "delete_file",
        "git_status",
        "git_diff",
        "git_log",
        "git_commit",
        "git_create_branch",
        "git_checkout",
        "git_push",
        "github_get_user",
        "github_list_repos",
        "github_get_repo_branches",
        "github_generate_ssh_key",
        "github_list_ssh_keys",
        "github_delete_ssh_key",
        "github_connect_pat",
    }

    # Tools that require TERMINAL in developer mode
    _TERMINAL_TOOLS: Set[str] = {
        "run_command",
        "lock_screen",
        "shutdown",
        "restart",
        "gui_automate_click",
        "gui_automate_type",
    }

    @classmethod
    def get_mode(cls) -> str:
        """Read the persisted launcher mode from iris_config.json."""
        try:
            with open(_CFG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("mode", "personal")
        except Exception:
            return "personal"

    @classmethod
    def is_developer(cls) -> bool:
        return cls.get_mode() == "developer"

    @classmethod
    def check(cls, capability: str) -> bool:
        mode = cls.get_mode()
        allowed = cls._DEVELOPER if mode == "developer" else cls._PERSONAL
        return capability in allowed

    @classmethod
    def require(cls, capability: str) -> None:
        if not cls.check(capability):
            mode = cls.get_mode()
            raise PermissionError(
                f"Capability '{capability}' not allowed in '{mode}' mode"
            )

    @classmethod
    def allowed_tools(cls) -> Set[str]:
        """Return the set of tool names permitted in the current mode."""
        mode = cls.get_mode()
        if mode == "developer":
            # All tools allowed
            return set()
        # Personal mode: block repo and terminal tools
        return cls._REPO_TOOLS | cls._TERMINAL_TOOLS

    @classmethod
    def is_tool_allowed(cls, tool_name: str) -> bool:
        """Check if a specific tool name is allowed in the current mode."""
        mode = cls.get_mode()
        if mode == "developer":
            return True
        blocked = cls._REPO_TOOLS | cls._TERMINAL_TOOLS
        return tool_name not in blocked
