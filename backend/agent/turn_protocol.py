"""Turn protocol — one envelope shape for every chat turn (execution audit, Phase 3).

Every turn reaches the frontend as::

    turn.start                    once, before any part
    turn.part  (seq = 1, 2, ...)  zero or more, numbered in emit order
    turn.end                      exactly once: status ok | error | cancelled

Before this module one reply travelled in three couriers (chat_chunk /
chat_message / text_response, plus task:*, tool:*, document:render from the
event bridge) and the chat view guessed which envelopes belonged together by
matching turn ids as strings. Now the backend numbers the parts of a turn and
guarantees its end; the frontend turn store (lib/turns/turnStore.ts) only
files them.

The schema below (``SCHEMA``) is the single source of truth: the TypeScript
types in ``lib/turns/protocol.ts`` are GENERATED from it by
``scripts/gen_turn_protocol_ts.py`` and a contract test keeps them in step.

Wire format (WebSocket): ``{"type": "turn.start" | "turn.part" | "turn.end",
"payload": {...}}`` — the same ``{type, payload}`` envelope every other WS
message uses.

Threading: parts are emitted from executor threads (the DER loop, the event
bridge) and from the main loop (the gateway). ``TurnEmitter`` takes a SYNC
``send`` callable that must be thread-safe (the gateway passes one that
schedules the WS send on the main loop). The seq counter and the end guard
are protected by one lock, so seq numbers are dense and ``turn.end`` is sent
exactly once whatever thread races to finish the turn.

Strands (owner, 2026-10-06): a thread holds many chats ("strands") that share
one memory. ``turn.start`` already carries ``strand_id`` / ``author`` / ``to``
/ ``refs`` so the turn store can file turns per strand; until strands exist in
the conversation store, ``strand_id`` equals ``conversation_id``, ``author``
is ``"user"`` and ``to`` is ``["@iris"]``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1

# Message types on the wire.
TURN_START = "turn.start"
TURN_PART = "turn.part"
TURN_END = "turn.end"

# Terminal statuses of a turn.
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"
END_STATUSES = (STATUS_OK, STATUS_ERROR, STATUS_CANCELLED)

# Bounds (quality check: memory footprint bounded, one part never floods the wire).
MAX_DELTA_CHARS = 64_000      # one text/reasoning delta
MAX_TEXT_CHARS = 400_000      # the final text on turn.end
MAX_ACTIVE_TURNS = 256        # registry of live turns (stale ones are evicted)

# ── The schema: single source of truth for the generated TypeScript ─────────
#
# Field spec: "name": "type" where type is one of
#   string | number | boolean | string[] | json   ("?" suffix = optional)
# A part's "type" field is implied by its key.
SCHEMA: Dict[str, Any] = {
    "version": PROTOCOL_VERSION,
    "start": {
        "v": "number",
        "turn_id": "string",
        "conversation_id": "string",
        "strand_id": "string",
        "author": "string",
        "to": "string[]",
        "refs": "string[]",
        "mode": "string",
        "prompt": "string",
        "client_ref": "string?",
        "ts": "number",
    },
    "part_envelope": {
        "v": "number",
        "turn_id": "string",
        "conversation_id": "string",
        "seq": "number",
        "ts": "number",
    },
    # Part types. Text/reasoning are DELTAS (append in seq order).
    "parts": {
        "text": {"delta": "string"},
        "reasoning": {"delta": "string"},
        "tool_call": {"name": "string", "call_id": "string?", "data": "json"},
        "tool_result": {"name": "string", "call_id": "string?", "ok": "boolean", "data": "json"},
        # Task-card lifecycle (task:start/progress/milestone/done/fail/paused/
        # resumed, memory:event, task:learning). ``event`` is the bus name.
        "todo": {"event": "string", "data": "json"},
        # A card the agent made (create_artifact -> document:render).
        "card": {"data": "json"},
        # Permission / question prompts and their answers, anchored in the turn.
        "interaction": {"event": "string", "data": "json"},
        # A visible notice that is not a failure of the turn
        # (validation_failed, budget_exhausted, recovery_start, ...).
        "notice": {"event": "string", "message": "string", "data": "json"},
        # A failure the user must see. The turn may still end ok (a node
        # error the loop recovered from) or end with status "error".
        "error": {"code": "string", "message": "string", "recoverable": "boolean"},
    },
    "end": {
        "v": "number",
        "turn_id": "string",
        "conversation_id": "string",
        "status": "string",
        "parts": "number",
        "text": "string",
        "speak": "string",
        "error": "string?",
        "ts": "number",
    },
}

PART_TYPES = tuple(SCHEMA["parts"].keys())


def _clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    return text if len(text) <= limit else text[:limit]


class TurnEmitter:
    """Numbers the parts of one turn and guarantees exactly one ``turn.end``.

    ``send`` receives the full ``{"type", "payload"}`` message. It is called
    with the emitter's lock RELEASED (a slow transport never blocks another
    thread's ``part()`` beyond the seq increment) — so delivery order may
    differ from seq order; the frontend store orders by ``seq``.
    """

    def __init__(
        self,
        send: Callable[[Dict[str, Any]], None],
        *,
        turn_id: str,
        conversation_id: str,
        strand_id: Optional[str] = None,
        author: str = "user",
        to: Optional[List[str]] = None,
        refs: Optional[List[str]] = None,
        mode: str = "personal",
        prompt: str = "",
        client_ref: Optional[str] = None,
    ) -> None:
        self._send = send
        self.turn_id = str(turn_id)
        self.conversation_id = str(conversation_id)
        self.strand_id = str(strand_id or conversation_id)
        self.author = author or "user"
        self.to = list(to) if to else ["@iris"]
        self.refs = list(refs or [])
        self.mode = mode if mode in ("personal", "developer") else "personal"
        self.prompt = prompt or ""
        self.client_ref = client_ref
        self._lock = threading.Lock()
        self._seq = 0
        self._started = False
        self._ended = False
        self.status: Optional[str] = None
        self.dropped_after_end = 0  # counted, never silent (HIDDEN FAILURES rule 4)
        # Reasoning characters this turn carried: the gateway files the kernel's
        # final thinking only when nothing was streamed (no duplicate).
        self.reasoning_chars = 0
        # Replay fixtures from REAL turns: IRIS_TURN_RECORD_DIR=<dir> writes each
        # turn's messages to <dir>/<turn_id>.jsonl on an ordered lane (off by default).
        self._record_dir = os.environ.get("IRIS_TURN_RECORD_DIR") or None

    # ── lifecycle ──────────────────────────────────────────────────────────
    @property
    def ended(self) -> bool:
        return self._ended

    @property
    def seq(self) -> int:
        return self._seq

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        _register(self)
        payload: Dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "turn_id": self.turn_id,
            "conversation_id": self.conversation_id,
            "strand_id": self.strand_id,
            "author": self.author,
            "to": self.to,
            "refs": self.refs,
            "mode": self.mode,
            "prompt": self.prompt,
            "ts": time.time(),
        }
        if self.client_ref:
            payload["client_ref"] = str(self.client_ref)
        self._deliver({"type": TURN_START, "payload": payload})

    def part(self, part_type: str, **fields: Any) -> Optional[int]:
        """Emit one part. Returns its seq, or None when it was not sent."""
        if part_type not in PART_TYPES:
            logger.warning("[Turn %s] unknown part type %r dropped", self.turn_id, part_type)
            return None
        if part_type in ("text", "reasoning"):
            fields["delta"] = _clip(fields.get("delta"), MAX_DELTA_CHARS)
            if not fields["delta"]:
                return None
        with self._lock:
            if self._ended:
                self.dropped_after_end += 1
                drop = True
            else:
                drop = False
                self._seq += 1
                seq = self._seq
        if drop:
            logger.info(
                "[Turn %s] %s part after turn.end dropped (count=%d)",
                self.turn_id, part_type, self.dropped_after_end,
            )
            return None
        if not self._started:
            # A part before start would be an orphan on the frontend.
            self.start()
        body = {"type": part_type, **fields}
        self._deliver({
            "type": TURN_PART,
            "payload": {
                "v": PROTOCOL_VERSION,
                "turn_id": self.turn_id,
                "conversation_id": self.conversation_id,
                "seq": seq,
                "ts": time.time(),
                "part": body,
            },
        })
        return seq

    def text(self, delta: str) -> Optional[int]:
        return self.part("text", delta=delta)

    def reasoning(self, delta: str) -> Optional[int]:
        seq = self.part("reasoning", delta=delta)
        if seq is not None:
            self.reasoning_chars += len(delta or "")
        return seq

    def error(self, message: str, code: str = "turn_error", recoverable: bool = False) -> Optional[int]:
        return self.part("error", code=code, message=_clip(message, 2_000), recoverable=bool(recoverable))

    def end(
        self,
        status: str = STATUS_OK,
        *,
        text: str = "",
        speak: str = "",
        error: Optional[str] = None,
    ) -> bool:
        """Send ``turn.end``. Only the FIRST call sends; later calls return False."""
        if status not in END_STATUSES:
            logger.warning("[Turn %s] bad end status %r -> error", self.turn_id, status)
            status = STATUS_ERROR
        with self._lock:
            if self._ended:
                return False
            self._ended = True
            self.status = status
            parts = self._seq
            started = self._started
            self._started = True
        if not started:
            # An end with no start (the turn failed before its first part)
            # still needs a start, or the frontend has nothing to close.
            self._deliver({"type": TURN_START, "payload": {
                "v": PROTOCOL_VERSION, "turn_id": self.turn_id,
                "conversation_id": self.conversation_id, "strand_id": self.strand_id,
                "author": self.author, "to": self.to, "refs": self.refs,
                "mode": self.mode, "prompt": self.prompt, "ts": time.time(),
                **({"client_ref": str(self.client_ref)} if self.client_ref else {}),
            }})
        payload: Dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "turn_id": self.turn_id,
            "conversation_id": self.conversation_id,
            "status": status,
            "parts": parts,
            "text": _clip(text, MAX_TEXT_CHARS),
            "speak": _clip(speak, 4_000),
            "ts": time.time(),
        }
        if error:
            payload["error"] = _clip(error, 2_000)
        self._deliver({"type": TURN_END, "payload": payload})
        _unregister(self)
        return True

    # ── guard: the turn ends exactly once, whatever happens ───────────────
    def __enter__(self) -> "TurnEmitter":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._ended:
            return False
        import asyncio as _asyncio

        if exc_type is not None and issubclass(exc_type, (_asyncio.CancelledError, KeyboardInterrupt)):
            self.end(STATUS_CANCELLED, error="cancelled")
        elif exc is not None:
            msg = f"{type(exc).__name__}: {exc}"
            self.error(msg, code="turn_exception")
            self.end(STATUS_ERROR, error=msg)
        else:
            # Body returned without ending the turn: still close it, and say so.
            logger.warning("[Turn %s] body exited without turn.end -> ended ok by guard", self.turn_id)
            self.end(STATUS_OK)
        return False  # never swallow the exception

    def _deliver(self, msg: Dict[str, Any]) -> None:
        try:
            self._send(msg)
        except Exception as exc:  # noqa: BLE001 — a transport failure never breaks the turn
            logger.warning("[Turn %s] %s send failed: %s", self.turn_id, msg.get("type"), exc)
        if self._record_dir:
            _record(self._record_dir, self.turn_id, msg)


def _append_line(path: str, line: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _record(directory: str, turn_id: str, msg: Dict[str, Any]) -> None:
    """Queue one message for the turn's recording. File I/O never runs on the
    caller (the main loop or the DER thread): it rides the turn_record lane."""
    try:
        safe = "".join(ch for ch in turn_id if ch.isalnum() or ch in "-_") or "turn"
        line = json.dumps(msg, ensure_ascii=False, default=str)
        path = os.path.join(directory, safe + ".jsonl")
        try:
            from backend.utils.durability_queue import lane
        except Exception:  # noqa: BLE001 — no lane (tests load this file alone)
            _append_line(path, line)
            return
        if not lane("turn_record").submit(f"turn_record:{safe}", _append_line, path, line):
            logger.info("[Turn %s] recording dropped (lane full)", turn_id)
    except Exception as exc:  # noqa: BLE001 — recording is a dev aid, never a failure
        logger.debug("[Turn %s] recording failed: %s", turn_id, exc)


# ── Registry of live turns: lets the event bridge file bus events into the turn ──

_registry_lock = threading.Lock()
_by_turn: Dict[str, TurnEmitter] = {}
_by_conversation: Dict[str, TurnEmitter] = {}


def _register(em: TurnEmitter) -> None:
    with _registry_lock:
        if len(_by_turn) >= MAX_ACTIVE_TURNS:
            # Evict the oldest (dict keeps insertion order). A turn this old
            # never ended — count it in the log; its guard will still end it.
            old_id = next(iter(_by_turn))
            old = _by_turn.pop(old_id)
            if _by_conversation.get(old.conversation_id) is old:
                _by_conversation.pop(old.conversation_id, None)
            logger.warning("[Turn] registry full; evicted turn %s", old_id)
        _by_turn[em.turn_id] = em
        _by_conversation[em.conversation_id] = em


def _unregister(em: TurnEmitter) -> None:
    with _registry_lock:
        if _by_turn.get(em.turn_id) is em:
            _by_turn.pop(em.turn_id, None)
        if _by_conversation.get(em.conversation_id) is em:
            _by_conversation.pop(em.conversation_id, None)


def active_turn(turn_id: Optional[str] = None, conversation_id: Optional[str] = None) -> Optional[TurnEmitter]:
    """The live turn an event belongs to: by turn id first, else the
    conversation's current turn. None when no turn is open."""
    with _registry_lock:
        if turn_id and turn_id in _by_turn:
            return _by_turn[turn_id]
        if conversation_id and conversation_id in _by_conversation:
            return _by_conversation[conversation_id]
    return None


def reset_registry_for_testing() -> None:
    with _registry_lock:
        _by_turn.clear()
        _by_conversation.clear()


# ── Bus event -> turn part (called by WSEventBridge after its own gating) ────

_TODO_EVENTS = frozenset({
    "task:start", "task:progress", "task:milestone", "task:done", "task:fail",
    "task:paused", "task:resumed", "task:learning", "memory:event",
})
_INTERACTION_EVENTS = frozenset({
    "permission:request", "permission:granted", "permission:denied",
    "question:ask", "question:answered", "question:timeout",
    "browser:takeover_requested",
})
_NOTICE_EVENTS = frozenset({
    "plan:validation_failed", "plan:budget_exhausted", "plan:recovery_start",
    "plan:topology_recovery", "vision:unavailable", "steering:ack", "task:blocked",
})


def _event_turn_id(data: Dict[str, Any]) -> Optional[str]:
    for key in ("turn_id", "response_turn_id", "responseTurnId"):
        val = data.get(key)
        if val:
            return str(val)
    return None


def route_bus_event(
    event: str,
    data: Any,
    *,
    turn_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Optional[int]:
    """File one bridged EventBus event into its live turn as a part.

    Returns the part's seq, or None when no turn is open for it (the legacy
    message the bridge already sent still carries the event) or the event is
    not one a turn shows. Never raises.
    """
    try:
        data = data if isinstance(data, dict) else ({"value": data} if data is not None else {})
        em = active_turn(turn_id or _event_turn_id(data), conversation_id or data.get("conversation_id"))
        if em is None:
            return None
        if event == "tool:call":
            return em.part("tool_call", name=str(data.get("tool") or data.get("name") or "tool"),
                           call_id=str(data.get("call_id") or data.get("step_id") or "") or None, data=data)
        if event == "tool:result":
            ok = data.get("success", data.get("ok", True))
            return em.part("tool_result", name=str(data.get("tool") or data.get("name") or "tool"),
                           call_id=str(data.get("call_id") or data.get("step_id") or "") or None,
                           ok=bool(ok), data=data)
        if event == "tool:error":
            return em.part("tool_result", name=str(data.get("tool") or data.get("name") or "tool"),
                           call_id=str(data.get("call_id") or data.get("step_id") or "") or None,
                           ok=False, data=data)
        if event in _TODO_EVENTS:
            return em.part("todo", event=event, data=data)
        if event == "document:render":
            return em.part("card", data=data)
        if event in _INTERACTION_EVENTS:
            return em.part("interaction", event=event, data=data)
        if event in _NOTICE_EVENTS:
            msg = data.get("message") or data.get("reason") or data.get("detail")
            if not msg:
                # No words to show: the raw event name is an engine word, never
                # chat text (live 2026-10-06: a steer printed "steering:ack" as an
                # IRIS line; the composer already shows the steer's receipt).
                logger.debug("[Turn %s] %s notice without text skipped", em.turn_id, event)
                return None
            return em.part("notice", event=event, message=_clip(msg, 2_000), data=data)
        if event == "agent:error":
            msg = data.get("message") or data.get("error") or "agent error"
            return em.error(str(msg), code=str(data.get("code") or "agent_error"),
                            recoverable=bool(data.get("recoverable", False)))
        return None
    except Exception as exc:  # noqa: BLE001 — routing never breaks the bridge
        logger.warning("[Turn] route_bus_event %s failed: %s", event, exc)
        return None
