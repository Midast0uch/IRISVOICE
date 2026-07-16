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
        turn_protection: Optional[int] = None,
        error_age_turns: int = 4,
    ) -> None:
        # DER Phase 0 (D0.10): turn_protection derives from the SAME context-window
        # resource the DER work-unit counter and MCM compress use — no independent budget.
        # Lazy import avoids a heavy agent_kernel load at module import time.
        if turn_protection is None:
            try:
                from backend.agent.agent_kernel import resolve_context_window
                turn_protection = max(4, int(resolve_context_window() / 6000))
            except Exception:
                turn_protection = 6  # safe fallback only if context window unavailable
        self.turn_protection = turn_protection
        self.error_age_turns = error_age_turns

    # ── Public API ────────────────────────────────────────────────────────

    def prune(
        self,
        messages: list[dict],
        session_id: Optional[str] = None,
        traj=None,
    ) -> tuple[list[dict], dict]:
        """
        Run all passes and return (pruned_messages, stats).

        Pass 4 (DER Phase 0, D0.8): before dropping a tool-call message (dedup or error
        purge), write a fan_trace to the trajectory store so the agent still sees the
        fanning after compaction. This is MODE-AGNOSTIC (runs in dev and prod identically);
        `traj` is optional — if None, Pass 4 is a no-op (zero standing token cost).

        stats keys:
          input_count, output_count, dedups, errors_purged, fan_traces
        """
        if not messages:
            return messages, {"input_count": 0, "output_count": 0,
                               "dedups": 0, "errors_purged": 0, "fan_traces": 0}

        original_count = len(messages)
        protected_start = max(0, len(messages) - self.turn_protection)
        protected_zone  = messages[protected_start:]
        work_zone       = list(messages[:protected_start])

        # Pass 2 — dedup in work zone
        work_zone, dedups, deduped_msgs = self._dedup(work_zone)

        # Pass 3 — error purge in work zone
        work_zone, errors_purged, error_msgs = self._purge_errors(work_zone)

        # Pass 4 — fan-trace dropped tool messages (D0.8)
        fan_traces = self._emit_fan_traces(
            deduped_msgs + error_msgs, session_id, traj
        )

        result = work_zone + protected_zone
        return result, {
            "input_count":    original_count,
            "output_count":   len(result),
            "dedups":         dedups,
            "errors_purged":  errors_purged,
            "fan_traces":     fan_traces,
        }

    @staticmethod
    def mark_error(message: dict) -> dict:
        """Tag a message so Pass 3 will purge it once it ages out."""
        message["_dcp_error"] = True
        return message

    # ── Internal passes ───────────────────────────────────────────────────

    def _dedup(self, messages: list[dict]) -> tuple[list[dict], int, list[dict]]:
        """
        Pass 2: deduplicate tool calls by (tool_name, args_json) hash.
        Protected tools are left untouched.
        Keeps the LAST occurrence of each unique call; earlier ones removed.
        Returns (pruned, count, dropped_messages).
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
        dropped = [messages[i] for i in to_drop]
        return pruned, len(to_drop), dropped

    def _purge_errors(self, messages: list[dict]) -> tuple[list[dict], int, list[dict]]:
        """
        Pass 3: remove messages flagged _dcp_error=True.
        Only applies to the work zone (already excludes protected turns).
        The age check is implicit — anything in the work zone is already
        older than turn_protection turns.
        Returns (pruned, count, dropped_messages).
        """
        before = len(messages)
        pruned = [m for m in messages if not m.get("_dcp_error", False)]
        dropped = [m for m in messages if m.get("_dcp_error", False)]
        return pruned, before - len(pruned), dropped

    def _emit_fan_traces(
        self,
        dropped: list[dict],
        session_id: Optional[str],
        traj,
    ) -> int:
        """
        DER Phase 0 (D0.8): for each dropped tool-call message, write a fan_trace to the
        trajectory store. Preserves the fan shape without bloating the prompt. Mode-agnostic;
        no-op if traj is None. Live u/xi pulled from the Caducean FFI if available.
        """
        if traj is None or not dropped:
            return 0
        written = 0
        # Best-effort live Caducean state (None if unavailable — trace still recorded)
        _cad = None
        try:
            from gateway.iris_ffi import ffi_caducean_get_state
            if session_id:
                _cad = ffi_caducean_get_state(session_id)
        except Exception:
            _cad = None
        _u = (_cad or {}).get("u")
        _xi = (_cad or {}).get("xi")
        for msg in dropped:
            _name = self._extract_tool_name(msg)
            if not _name or _name in PROTECTED_TOOLS:
                continue
            _key = self._tool_key(msg) or _name
            _outcome = "error" if msg.get("_dcp_error") else "ok"
            try:
                traj.record_fan_trace(
                    session_id=session_id or "unknown",
                    step_id=msg.get("step_id", "unknown"),
                    tool=_name,
                    args_hash=_key[:12],
                    outcome=_outcome,
                    u=_u,
                    xi=_xi,
                )
                written += 1
            except Exception as exc:
                logger.debug("[DCP] fan_trace write skipped: %s", exc)
        return written

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
