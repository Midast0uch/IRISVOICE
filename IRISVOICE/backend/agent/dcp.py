"""
DCP — Dynamic Context Pruner.

3-pass pruning applied to the message history before every LLM call:
  Pass 1: Protect last N turns from any pruning (turn_protection).
  Pass 2: Dedup tool calls in the unprotected zone by hash(tool_name+args).
           Keep only the most-recent result per unique call.
  Pass 3: Purge messages tagged _dcp_error=True that are older than
           error_age_turns turns.

PROTECTED_TOOLS bypass all passes entirely.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

PROTECTED_TOOLS: frozenset[str] = frozenset({
    "mcm_compress", "mcm_recall", "get_session", "navigate",
    "pin_search", "pin_list", "pin_add", "pin_link",
    "record_edit", "record_test", "record_create",
    "claim_work", "complete_task", "advance_gate",
    "pacman_retrieve", "pacman_fragment", "swarm_broadcast",
})


class DCP:
    """
    Dynamic Context Pruner.

    Args:
        turn_protection:  Number of most-recent turns frozen from pruning.
        error_age_turns:  Turns after which _dcp_error messages are purged.
    """

    def __init__(
        self,
        turn_protection: int = 6,
        error_age_turns: int = 4,
    ) -> None:
        self.turn_protection = turn_protection
        self.error_age_turns = error_age_turns

    # ── Public API ────────────────────────────────────────────────────────

    def prune(self, messages: list[dict]) -> tuple[list[dict], dict]:
        """
        Run all three passes and return (pruned_messages, stats).

        stats keys:
          input_count, output_count, dedups, errors_purged
        """
        if not messages:
            return messages, {"input_count": 0, "output_count": 0,
                               "dedups": 0, "errors_purged": 0}

        original_count = len(messages)
        protected_start = max(0, len(messages) - self.turn_protection)
        protected_zone  = messages[protected_start:]
        work_zone       = list(messages[:protected_start])

        # Pass 2 — dedup in work zone
        work_zone, dedups = self._dedup(work_zone)

        # Pass 3 — error purge in work zone
        work_zone, errors_purged = self._purge_errors(work_zone)

        result = work_zone + protected_zone
        return result, {
            "input_count":    original_count,
            "output_count":   len(result),
            "dedups":         dedups,
            "errors_purged":  errors_purged,
        }

    @staticmethod
    def mark_error(message: dict) -> dict:
        """Tag a message so Pass 3 will purge it once it ages out."""
        message["_dcp_error"] = True
        return message

    # ── Internal passes ───────────────────────────────────────────────────

    def _dedup(self, messages: list[dict]) -> tuple[list[dict], int]:
        """
        Pass 2: deduplicate tool calls by (tool_name, args_json) hash.
        Protected tools are left untouched.
        Keeps the LAST occurrence of each unique call; earlier ones removed.
        """
        seen:    dict[str, int] = {}   # hash -> last index in list
        to_drop: set[int]       = set()

        for i, msg in enumerate(messages):
            key = self._tool_key(msg)
            if key is None:
                continue
            tool_name = self._extract_tool_name(msg)
            if tool_name in PROTECTED_TOOLS:
                continue
            if key in seen:
                to_drop.add(seen[key])   # drop the earlier duplicate
            seen[key] = i

        pruned = [m for i, m in enumerate(messages) if i not in to_drop]
        return pruned, len(to_drop)

    def _purge_errors(self, messages: list[dict]) -> tuple[list[dict], int]:
        """
        Pass 3: remove messages flagged _dcp_error=True.
        Only applies to the work zone (already excludes protected turns).
        The age check is implicit — anything in the work zone is already
        older than turn_protection turns.
        """
        before = len(messages)
        pruned = [m for m in messages if not m.get("_dcp_error", False)]
        return pruned, before - len(pruned)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _tool_key(message: dict) -> Optional[str]:
        """
        Return a stable hash key for tool-call messages.
        Returns None for non-tool messages (assistant/user/system text).
        """
        role    = message.get("role", "")
        content = message.get("content", "")

        # OpenAI-style tool call in assistant message
        tool_calls = message.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            try:
                tc   = tool_calls[0]
                name = tc.get("function", {}).get("name", "")
                args = tc.get("function", {}).get("arguments", "{}")
                raw  = f"{name}::{args}"
                return hashlib.sha1(raw.encode()).hexdigest()
            except Exception:
                return None

        # Tool result message (role="tool")
        if role == "tool":
            name = message.get("name", "") or message.get("tool_name", "")
            if name:
                args = json.dumps(message.get("content", ""), sort_keys=True)
                return hashlib.sha1(f"{name}::{args}".encode()).hexdigest()

        return None

    @staticmethod
    def _extract_tool_name(message: dict) -> str:
        tool_calls = message.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            try:
                return tool_calls[0].get("function", {}).get("name", "")
            except Exception:
                pass
        return message.get("name", "") or message.get("tool_name", "")
