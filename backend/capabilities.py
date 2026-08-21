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
        """Read the persisted launcher mode from iris_config.json.

        REQ-16 AC3 + edge case: an ABSENT or unreadable config must NOT resolve
        to the most permissive policy ("personal", which AUTO_APPROVES
        SIDE_EFFECT tools). Fail CLOSED to "developer" — the more restrictive
        policy that requires approval for SIDE_EFFECT tools.
        """
        try:
            with open(_CFG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            mode = cfg.get("mode")
            if mode in ("personal", "developer"):
                return mode
            # Absent / malformed mode value -> fail closed to the restrictive policy
            return "developer"
        except Exception:
            # Unreadable config -> fail CLOSED to the more restrictive policy
            return "developer"

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
    def blocked_tools(cls) -> Set[str]:
        """Return the set of tool names BLOCKED in the current mode.

        NOTE: historically named `allowed_tools` but it actually returned the
        BLOCKED set (developer -> empty = block nothing). Renamed to
        `blocked_tools` in T20 to remove the inverted-name trap. Its only
        caller reads it correctly as `blocked = CapabilitySet.blocked_tools()`.
        """
        mode = cls.get_mode()
        if mode == "developer":
            # All tools allowed -> nothing blocked
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
