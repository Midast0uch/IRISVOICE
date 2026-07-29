"""Generic long-running tool narration heartbeat.

Blueprint-pure (see docs/architecture/der-coupled-action-cycle-blueprint.md):
narration is NOT a mode-driven override. It is a tool CAPABILITY (`long_running`
on ToolSpec) that the DER operator's tool layer (execute_tool) reads uniformly.
Any slow tool (crawler_query today, others later) gets a periodic TTS heartbeat
while it runs, so the user hears progress instead of silence during a long
operation. All speech funnels through the SpeakTool singleton, which serializes
playback via the narration lock — so web-search progress and step-level
narration stay isolated yet intersect safely at the TTS boundary.

pin_9e97e21340e7.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("iris.agent.narration")

# REQ-9: narration + TTS observability log. Every narration decision
# (including SILENCE) is recorded with structured fields, scoped by
# conversation_id, so a later pass can reconstruct per-thread trigger
# frequency + intervals and tune the narration policy. Split/collapse
# entries carry u/ξ. Writes are fire-and-forget async (off the
# critical path) to a per-conversation JSONL file.
_NARRATION_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "narration_logs"
)


class NarrationLog:
    """REQ-9: structured, conversation-scoped narration observability log.

    One JSONL file per conversation_id under data/narration_logs/.
    Each entry: ts, conversation_id, step_id, decision (silence|brief|
    incremental), signal (None|avoided|retried|crystallized), u, xi,
    text (the spoken line, or "" on silence), tts_played (bool).
    """

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id or "unknown"
        self._path = os.path.join(
            _NARRATION_LOG_DIR, f"{self.conversation_id}.jsonl"
        )

    def _write(self, entry: dict) -> None:
        try:
            os.makedirs(_NARRATION_LOG_DIR, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("[narration] log write failed: %s", exc)

    async def record(
        self,
        step_id: str,
        decision: str,
        signal: Optional[str],
        u: Optional[float],
        xi: Optional[float],
        text: str,
        tts_played: bool,
    ) -> None:
        """Append one structured entry. Fire-and-forget (off critical path)."""
        entry = {
            "ts": time.time(),
            "conversation_id": self.conversation_id,
            "step_id": step_id,
            "decision": decision,  # silence | brief | incremental
            "signal": signal,  # None | avoided | retried | crystallized
            "u": u,
            "xi": xi,
            "text": text or "",
            "tts_played": bool(tts_played),
        }
        # ── REQ-9: structured log for narration observability ──
        logger.info(
            "Narration spoken",
            extra={
                "context": "narration",
                "text": text or "",
                "decision": decision,
                "signal": signal,
                "conversation_id": self.conversation_id,
                "step_id": step_id,
            },
        )

        # Off the critical path: schedule the file write, don't await it.
        try:
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, self._write, entry)
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("[narration] log schedule failed: %s", exc)

# W5 (T35): speak heartbeat at most once per 25s while a long tool runs.
_HEARTBEAT_INTERVAL_S = 25

# W5 (T37): removed "Still researching" — page-specific snippets are spoken
# directly by _on_page_done in tool_bridge.py. The heartbeat is a safety net
# only for very long crawls with no page data to narrate.
_TOOL_VERB = {
    "crawler_query": "reading",
    "web_search": "searching",
}


async def run_with_narration(
    coro_factory: Callable[[], Awaitable[object]],
    speak: Callable[[str, str], object],
    tool_name: str,
    status_fn: Optional[Callable[[], str]] = None,
    interval_s: float = _HEARTBEAT_INTERVAL_S,
    should_narrate: bool = True,  # T4.4: task-level gate — agent decides per task
    conversation_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> object:
    """Run ``coro_factory()`` as a task and speak a periodic heartbeat until done.

    Args:
        coro_factory: zero-arg callable returning the tool's awaitable.
        speak: ``SpeakTool.speak`` (or compatible) — ``speak(text, priority)``.
        tool_name: the tool being run (used for a generic status verb).
        status_fn: optional callable returning a short progress detail string
            (e.g. page count). When provided, the heartbeat includes it.
        interval_s: heartbeat period.
        should_narrate: task-level gate. When False, the heartbeat is suppressed
            entirely regardless of the global may_narrate gate. The agent decides
            per task whether narration is needed (REQ-7 AC1/AC2, T4.4).
        conversation_id: scope for the REQ-9 observability log line. Missing
            scope is logged explicitly as "unknown" (REQ-9 edge case), never
            silently dropped.
        turn_id: turn scope for the REQ-9 observability log line. Same
            "unknown" fallback as conversation_id.

    Returns:
        The tool coroutine's result.

    The heartbeat respects the SpeakTool rate limiter (1 speak / interval_s, well
    under MAX_PENDING=3/10s) and uses priority="low" so it never interrupts the
    agent's final answer.
    """
    verb = _TOOL_VERB.get(tool_name, "working on that")
    conv_id = conversation_id or "unknown"
    turn_id_ = turn_id or "unknown"

    async def _heartbeat() -> None:
        try:
            while not run_task.done():
                await asyncio.sleep(interval_s)
                if run_task.done():
                    break
                detail = ""
                if status_fn is not None:
                    try:
                        detail = status_fn() or ""
                    except Exception:  # pragma: no cover - best effort
                        detail = ""
                # W5 (T37/T38): conversational snippet heartbeat, never "Still researching".
                msg = detail if detail else f"{verb}…"
                if should_narrate and may_narrate():
                    # REQ-9: structured log for narration heartbeat. Guarded so a
                    # logging fault can never silently cancel the heartbeat loop
                    # (that is exactly how this heartbeat previously went mute:
                    # an unguarded NameError here propagated out of _heartbeat()
                    # and was swallowed by the outer finally-clause await).
                    try:
                        logger.info("Narration heartbeat", extra={
                            "context": "narration", "text": msg,
                            "tool_name": tool_name, "conversation_id": conv_id,
                            "turn_id": turn_id_,
                        })
                    except Exception as exc:  # pragma: no cover - best effort
                        logger.debug("[narration] heartbeat log failed: %s", exc)
                    try:
                        speak(msg, "low")
                    except Exception as exc:  # pragma: no cover - best effort
                        logger.debug("[narration] heartbeat speak failed: %s", exc)
        except asyncio.CancelledError:
            pass

    run_task = asyncio.create_task(coro_factory())
    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        return await run_task
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass


# ── Shared narration gate (cooldown across ALL narration sources) ─────────
# Every source (heartbeat, page-done, "Searching the web for...") checks this
# gate before speaking.  This prevents multiple TTS utterances from stacking
# when two different narration mechanisms fire in quick succession.
_NARRATION_GATE_INTERVAL = 18.0  # max one narration utterance per 18s
_narration_gate_lock = threading.Lock()
_narration_gate_last = 0.0


def may_narrate() -> bool:
    """Return True if no other narration source has spoken in the last
    _NARRATION_GATE_INTERVAL seconds.  Thread-safe (used from both sync
    tool_bridge.py and async narration.py contexts)."""
    global _narration_gate_last
    now = time.time()
    with _narration_gate_lock:
        if now - _narration_gate_last >= _NARRATION_GATE_INTERVAL:
            _narration_gate_last = now
            return True
        return False
