"""
ContextControlHandler — scans agent output for MCM: prefixed control codes.

Codes (MCM: prefix required — collision-proof against Mycelium coordinates):
  MCM:999 <reason>   → DCP prune — strip tool-call history, keep reasoning
  MCM:998 <artifact> → Pin artifact to mycelium_pins (is_permanent=True)
  MCM:997 <summary>  → MCM compress + inject_recovery (context condensation)
  MCM:996 <update>   → Broadcast coordinate update to collective brain

Safety guarantee: all Mycelium coordinate values are normalized floats [0.0, 1.0]
(chrono [0,24], capability [0,5]); gate numbers 1–5; DER steps max 40.
999/998/997/996 cannot appear in any coordinate or NBL string.
MCM: prefix additionally prevents false-positive matches in prose.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from .constants import CTRL_CODE_RE_PATTERN

logger = logging.getLogger(__name__)
_CODE_RE = re.compile(CTRL_CODE_RE_PATTERN, re.MULTILINE)


@dataclass
class ContextControlResult:
    fired:      list[str] = field(default_factory=list)
    pruned:     bool = False
    pinned:     bool = False
    compressed: bool = False
    broadcast:  bool = False


class ContextControlHandler:
    """
    Passively scans response text for MCM: control codes and executes them.
    Called from AgentKernel._handle_control_codes() after every response.
    Never raises — all failures are debug-logged only.
    """

    def __init__(self, memory_interface, mcm_instance, session_id: str) -> None:
        self._mi        = memory_interface
        self._mcm       = mcm_instance
        self.session_id = session_id

    def scan_and_execute(self, response_text: str,
                         messages: list[dict], task: str) -> ContextControlResult:
        """Find MCM: codes in response_text and execute each action."""
        result = ContextControlResult()
        if not response_text:
            return result
        for match in _CODE_RE.finditer(response_text):
            code_num  = match.group(1)        # "999" | "998" | "997" | "996"
            code_body = match.group(2).strip()
            result.fired.append(f"MCM:{code_num}")
            try:
                if code_num == "999":
                    self._prune_tools(messages)
                    result.pruned = True
                elif code_num == "998":
                    self._pin_artifact(code_body)
                    result.pinned = True
                elif code_num == "997":
                    self._compress(messages, task, code_body)
                    result.compressed = True
                elif code_num == "996":
                    self._broadcast_coordinate(code_body)
                    result.broadcast = True
            except Exception as exc:
                logger.debug("[ctrl] MCM:%s execution error: %s", code_num, exc)
        if result.fired:
            logger.info("[ctrl] Codes fired this turn: %s", result.fired)
        return result

    # ── Action handlers ───────────────────────────────────────────────────

    def _prune_tools(self, messages: list[dict]) -> None:
        """MCM:999 — strip tool-call history from messages in-place via DCP."""
        try:
            from backend.agent.dcp import DCP
            pruned, stats = DCP().prune(messages)
            messages[:] = pruned
            logger.debug("[ctrl:999] DCP pruned: %s", stats)
        except Exception as exc:
            logger.debug("[ctrl:999] DCP unavailable: %s", exc)

    def _pin_artifact(self, artifact_text: str) -> None:
        """MCM:998 — pin artifact to mycelium_pins with is_permanent=True."""
        try:
            conn = self._get_conn()
            if not conn:
                return
            pin_id = str(uuid.uuid4())
            now = time.time()
            conn.execute(
                """INSERT OR REPLACE INTO mycelium_pins
                   (pin_id, title, pin_type, content, tags,
                    file_refs, project_id, origin_id,
                    created_at, updated_at, is_permanent)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (pin_id, artifact_text[:120], "fragment", artifact_text,
                 json.dumps(["swarm", "ctrl_998", "auto_pin"]),
                 "[]", "IRISVOICE", self.session_id,
                 now, now, 1),
            )
            conn.commit()
            logger.debug("[ctrl:998] Pinned artifact pin_id=%s", pin_id)
        except Exception as exc:
            logger.debug("[ctrl:998] pin failed: %s", exc)

    def _compress(self, messages: list[dict], task: str, summary: str) -> None:
        """MCM:997 — trigger MCM compression + inject_recovery."""
        try:
            if self._mcm is None:
                return
            compressed = self._mcm.compress(
                active_task=task or summary,
                active_files=[],
                unverified_edits=[],
                warnings=[summary] if summary else [],
            )
            if compressed and messages:
                recovery = self._mcm.inject_recovery(messages, compressed)
                messages[:] = recovery
            logger.debug("[ctrl:997] MCM compress fired")
        except Exception as exc:
            logger.debug("[ctrl:997] compress failed: %s", exc)

    def _broadcast_coordinate(self, update_text: str) -> None:
        """MCM:996 — log coordinate broadcast; Mycelium traversal cycle picks it up."""
        logger.info("[ctrl:996] Coordinate broadcast queued: %s", update_text[:120])

    def _get_conn(self):
        try:
            return getattr(getattr(self._mi, "_mycelium", None), "_conn", None)
        except Exception:
            return None
