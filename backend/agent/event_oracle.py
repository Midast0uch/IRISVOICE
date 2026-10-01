"""Oracle shadow consumers for events rules cannot type (docs/Design/EVENT_TAXONOMY.md section 6).

Three consumers, all SHADOW (CLAUDE.md "THE ORACLE EARNS ITS JOBS": nothing here
changes a decision; no enforced mode exists):

  ``user_feedback``      every USER MESSAGE: confirmation | correction | preference |
                         refinement | new_request | none. The previous assistant turn
                         is part of the frame (a correction is relative to what the
                         agent said). The Oracle label becomes a ``memory_events`` row.
  ``event_family``       the 9 alphabet families, for Layer-3 events (family NULL) and
                         for a sample of rule-labeled events (the rule's family is the
                         exact reference label - free).
  ``event_type:<family>`` the registered labels of one family, same two populations.

Every decision writes ONE shadow row through the installed sink (the kernel installs
its ledger sink, like ``click_safety_shadow``). The Brain labels a bounded SAMPLE as the
reference label (default 1 in 3, and always when the Oracle's top probability is low),
on the light path (``infer``: the router chokepoint; a lane thread is BACKGROUND, so
the call is gated, never privileged). Scoring runs on the ``event_oracle`` lane and the
event write on the ``memory_events`` lane (one writer per resource): never on the answer
path, so a stalled Oracle or Brain costs the reply nothing.

Calibration honesty: the frame for an EVENT never carries the label or the fields the
registry derives from it (actor, valence). A rule-labeled calibration row would
otherwise be answered by reading the label, and precision measured that way would not
transfer to the unlabeled Layer-3 events the consumer exists for.

Layer-3 events are scored by a bounded pass over rows newer than a process-local
watermark (events written since this process started; a restart never rescores).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("event_oracle")

USER_FEEDBACK = "user_feedback"
USER_OPTIONS = ("confirmation", "correction", "preference", "refinement", "new_request", "none")
# user_feedback option -> registered event label. "none" writes no event.
USER_LABELS: Dict[str, str] = {
    "confirmation": "CONFIRMATION",
    "correction": "CORRECTION",
    "preference": "PREFERENCE_STATED",
    "refinement": "GOAL_REFINED",
    "new_request": "GOAL_SET",
}
USER_INSTRUCTION = (
    "How does the user message relate to the previous assistant message? "
    "Is it a confirmation, a correction, a standing preference, a refinement of the "
    "goal, a new request, or none of these?"
)

EVENT_FAMILY = "event_family"
# The alphabet's families in the taxonomy's order (a frozenset has none; the menu
# needs a stable order). A test pins this tuple to event_alphabet.FAMILIES.
FAMILY_ORDER = (
    "intent", "control", "problem", "knowledge", "feedback",
    "delivery", "memory", "safety", "environment",
)
FAMILY_INSTRUCTION = "Which family of events does this event belong to?"
TYPE_INSTRUCTION = "Which label names this event within its family?"

# Defaults; each is read from the environment on every use so it stays configurable.
BRAIN_RATE_ENV, BRAIN_RATE_DEFAULT = "IRIS_EVENT_ORACLE_BRAIN_RATE", 1.0 / 3.0
LOW_CONF_ENV, LOW_CONF_DEFAULT = "IRIS_EVENT_ORACLE_LOW_CONF", 0.5
RULE_SAMPLE_ENV, RULE_SAMPLE_DEFAULT = "IRIS_EVENT_ORACLE_RULE_SAMPLE", 0.1

_PREV_HALF = 200      # chars kept from each end of the previous assistant message
_TEXT_MAX = 400       # chars of the user message the frame carries
PASS_LIMIT = 50       # events one pass reads
PASS_MIN_INTERVAL_S = 20.0

# Sentinel: adopt the module-level engine singleton. ``ENGINE = None`` means NO ENGINE -
# never "resolve the singleton", or a shadow scorer would silently load the model on
# first use. Tests replace ENGINE with a fake.
AUTO_ENGINE = object()
ENGINE: Any = AUTO_ENGINE

_ROW_SINK: Optional[Callable[[dict], None]] = None


def set_row_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Install (or clear) the process-wide row sink. Test seam / ledger wiring."""
    global _ROW_SINK
    _ROW_SINK = sink


def emit_row(row: Optional[dict]) -> None:
    """Hand a shadow row to the installed sink, else log it. Never raises."""
    if not row:
        return
    sink = _ROW_SINK
    if callable(sink):
        try:
            sink(row)
            return
        except Exception as e:  # noqa: BLE001 - an observer never blocks
            logger.debug("[event_oracle] row sink failed: %r", e)
    logger.info(
        "[event_oracle] shadow row consumer=%s chosen=%s brain=%s conf=%s",
        row.get("consumer_id"), row.get("chosen"), row.get("brain_choice"), row.get("confidence"),
    )


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class _RateGate:
    """Exact 1-in-N sampling without a random source: the same rate on any run, and
    testable. ``take()`` is True on the calls where the running total crosses 1."""

    def __init__(self) -> None:
        self._acc = 0.0
        self._lock = threading.Lock()

    def take(self, rate: float) -> bool:
        with self._lock:
            self._acc += max(0.0, min(1.0, rate))
            if self._acc >= 1.0 - 1e-9:
                self._acc -= 1.0
                return True
            return False


_GATES: Dict[str, _RateGate] = {}
_GATES_LOCK = threading.Lock()


def _brain_sampled(consumer_id: str) -> bool:
    with _GATES_LOCK:
        gate = _GATES.setdefault(consumer_id, _RateGate())
    return gate.take(_env_float(BRAIN_RATE_ENV, BRAIN_RATE_DEFAULT))


def _resolve_engine() -> Any:
    engine = ENGINE
    if engine is AUTO_ENGINE:
        from backend.agent.decision_engine import get_decision_engine

        engine = get_decision_engine()
    return engine


# ── consumer registration ───────────────────────────────────────────────────

def type_consumer_id(family: str) -> str:
    return f"event_type:{family}"


def family_labels(family: str) -> List[str]:
    """The registered labels of one family (Layer 2), in registration order."""
    from backend.memory import event_alphabet as ea

    return [name for name, spec in ea.registered_labels().items() if spec.family == family]


def _register(consumer_id: str, instruction: str, labels: Sequence[str]) -> None:
    """Register fixed-label criteria; replace when the label set moved (a Layer-2 data
    edit adds a label to a family). Registering is not enforcing."""
    from backend.agent.decision_backend_onnx import (
        ConsumerSpec,
        get_consumer_spec,
        register_consumer_spec,
    )

    labels = tuple(labels)
    spec = get_consumer_spec(consumer_id)
    if spec is None or spec.labels != labels or spec.instruction != instruction:
        register_consumer_spec(ConsumerSpec(
            consumer_id=consumer_id, task_name=consumer_id,
            instruction=instruction, labels=labels,
        ))


def register_consumers() -> List[str]:
    """Register ``user_feedback``, ``event_family`` and one ``event_type:<family>`` per
    family. Idempotent. Returns the consumer ids."""
    _register(USER_FEEDBACK, USER_INSTRUCTION, USER_OPTIONS)
    _register(EVENT_FAMILY, FAMILY_INSTRUCTION, FAMILY_ORDER)
    ids = [USER_FEEDBACK, EVENT_FAMILY]
    for fam in FAMILY_ORDER:
        _register(type_consumer_id(fam), TYPE_INSTRUCTION, family_labels(fam))
        ids.append(type_consumer_id(fam))
    return ids


# ── the Brain reference label ───────────────────────────────────────────────

def _parse_choice(raw: str, options: Sequence[str]) -> Optional[str]:
    """The earliest whole-word option in the Brain's reply, or None."""
    text = (raw or "").lower()
    best: Optional[Tuple[int, str]] = None
    for opt in options:
        m = re.search(r"(?<![a-z0-9_])" + re.escape(opt.lower()) + r"(?![a-z0-9_])", text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), opt)
    return best[1] if best else None


def _brain_label(brain: Optional[Callable[[str], str]], prompt: str,
                 options: Sequence[str]) -> Optional[str]:
    if brain is None:
        return None
    try:
        return _parse_choice(brain(prompt), options)
    except Exception as e:  # noqa: BLE001 - the reference is optional
        logger.info("[event_oracle] brain label unavailable: %s", type(e).__name__)
        return None


def brain_for(owner: Any) -> Optional[Callable[[str], str]]:
    """One short Brain call on the LIGHT path (``infer``: the router chokepoint, no
    tools) - the click-safety judge pattern. None when the owner has no ``infer``."""
    infer = getattr(owner, "infer", None)
    if not callable(infer):
        return None

    def _call(prompt: str) -> str:
        resp = infer(prompt, role="reasoning", max_tokens=16, temperature=0.0)
        return getattr(resp, "raw_text", "") or ""

    return _call


def _decide(consumer_id: str, options: Sequence[str], goal: str, instruction: str):
    """One Oracle decision, or None (no engine / no answer). Never raises."""
    try:
        engine = _resolve_engine()
        if engine is None:
            return None
        return engine.decide(consumer_id, list(options), {"goal": goal}, instruction=instruction)
    except Exception as e:  # noqa: BLE001 - a shadow never raises
        logger.debug("[event_oracle] decide failed consumer=%s: %r", consumer_id, e)
        return None


def _row(consumer_id: str, ds: Any, reference: Optional[str]) -> dict:
    row: Dict[str, Any] = {
        "consumer_id": consumer_id,
        "chosen": ds.chosen,
        "confidence": round(float(ds.confidence), 4),
        "engine_latency_ms": ds.engine_latency_ms,
        "shadow": True,
    }
    if reference is not None:
        row["brain_choice"] = reference
    return row


# ── 1. user_feedback: every user message ────────────────────────────────────

def last_assistant_text(owner: Any) -> str:
    """The previous assistant turn from the owner's conversation memory, bounded
    (head + tail). Empty when there is none. Never raises."""
    try:
        for m in reversed(list(getattr(getattr(owner, "_conversation_memory", None), "messages", None) or [])):
            if getattr(m, "role", "") == "assistant":
                text = (getattr(m, "content", "") or "").strip()
                if len(text) > 2 * _PREV_HALF:
                    text = text[:_PREV_HALF] + " ... " + text[-_PREV_HALF:]
                return text
    except Exception:  # noqa: BLE001
        pass
    return ""


def _user_frame(text: str, prev_assistant: str) -> str:
    prev = prev_assistant or "(none: this is the first message)"
    return f"Assistant said: {prev}\nUser replied: {text[:_TEXT_MAX]}"


def _user_prompt(frame: str) -> str:
    return (
        "Label how the user message relates to the previous assistant message.\n"
        "confirmation = the user accepts or confirms the result.\n"
        "correction = the user says the assistant was wrong.\n"
        "preference = a standing rule (always, never).\n"
        "refinement = the user changes or narrows the current goal.\n"
        "new_request = a new, separate goal.\n"
        "none = none of these (chit-chat, thanks without a verdict).\n\n"
        f"{frame}\n\nAnswer with exactly one word: "
        + ", ".join(USER_OPTIONS) + "."
    )


def run_user_feedback(
    text: str,
    prev_assistant: str,
    *,
    brain: Optional[Callable[[str], str]] = None,
    write_event: Optional[Callable[..., None]] = None,
    from_voice: bool = False,
) -> Optional[dict]:
    """Score ONE user message. Blocking (model calls): run it on the ``event_oracle``
    lane. Emits ONE shadow row (when the Oracle answered) and, when the label is not
    ``none``, hands ONE event to ``write_event(**emit_event kwargs)``. Returns a small
    result dict, or None when nothing labeled the message. Never raises."""
    try:
        register_consumers()
        frame = _user_frame(text, prev_assistant)
        ds = _decide(USER_FEEDBACK, USER_OPTIONS, frame, USER_INSTRUCTION)
        sampled = _brain_sampled(USER_FEEDBACK)
        low = ds is None or float(ds.confidence) < _env_float(LOW_CONF_ENV, LOW_CONF_DEFAULT)
        brain_label = (_brain_label(brain, _user_prompt(frame), USER_OPTIONS)
                       if (sampled or low) else None)
        if ds is not None:
            emit_row(_row(USER_FEEDBACK, ds, brain_label))
        final = brain_label or (ds.chosen if ds is not None else None)
        if final is None:
            return None
        label = USER_LABELS.get(final)
        source = "brain" if brain_label else "oracle"
        if label is not None and write_event is not None:
            write_event(
                label=label, evidence="user", label_source=source,
                label_confidence=None if brain_label else round(float(ds.confidence), 4),
                payload={
                    "consumer": USER_FEEDBACK, "oracle": ds.chosen if ds is not None else None,
                    "oracle_p": round(float(ds.confidence), 4) if ds is not None else None,
                    "brain": brain_label, "from_voice": bool(from_voice),
                },
            )
        return {"option": final, "label": label, "label_source": source}
    except Exception as e:  # noqa: BLE001 - never blocks the lane
        logger.warning("[event_oracle] user_feedback failed: %r", e)
        return None


def observe_user_message(
    owner: Any, text: str, *, thread_id: Optional[str], turn_id: Optional[str] = None,
    from_voice: bool = False,
) -> bool:
    """THE user-message hook (``AgentKernel.process_text_message``: text and voice).

    Cheap and synchronous: read the previous assistant turn, resolve the store, queue
    ONE job. All model work is on the ``event_oracle`` lane, the write on the
    ``memory_events`` lane. Returns whether the job was queued. Never raises."""
    try:
        if not (text or "").strip():
            return False
        from backend.utils.durability_queue import lane

        prev = last_assistant_text(owner)
        brain = brain_for(owner)
        mi = getattr(owner, "_memory_interface", None)
        conn = _resolve_conn(mi)

        def _write_event(**kw: Any) -> None:
            if conn is None:
                return
            lane("memory_events").submit(
                "memory_events:user_feedback", _emit, conn, mi, thread_id, turn_id, kw,
            )

        queued = lane("event_oracle").submit(
            "event_oracle:user_feedback", run_user_feedback, text, prev,
            brain=brain, write_event=_write_event, from_voice=from_voice,
        )
        if conn is not None:
            schedule_pass(conn, brain)
        return bool(queued)
    except Exception as e:  # noqa: BLE001
        logger.debug("[event_oracle] observe skipped: %r", e)
        return False


def _resolve_conn(memory_interface: Any) -> Any:
    from backend.agent.ontology_recall import resolve_mycelium_conn

    return resolve_mycelium_conn(memory_interface)


def _emit(conn: Any, mi: Any, thread_id: Optional[str], episode_id: Optional[str],
          kw: Dict[str, Any]) -> None:
    """The ``memory_events`` lane job: the canonical writer, with the state address."""
    from backend.memory.memory_events import emit_event

    coords = None
    try:
        from backend.agent.caducean_trajectory import latest_coords_str

        coords = latest_coords_str(mi, thread_id or "")
    except Exception:  # noqa: BLE001
        pass
    emit_event(conn, thread_id=thread_id, episode_id=episode_id,
               sigma_from=coords, sigma_to=coords, **kw)


# ── 2. event_family / event_type:<family>: events rules cannot type ─────────

_PASS_STATE: Dict[str, float] = {"watermark": time.time(), "last_pass": 0.0}
_PASS_LOCK = threading.Lock()

_EVENT_COLS = ("event_id, ts, family, label, label_source, evidence, cause_key, outcome_key, "
               "trigger, exec_domain, topic_domain, action_signature")


def _rule_sampled(event_id: str) -> bool:
    """Stable per event (a hash, not a counter): the same event is in or out on every
    pass and on every process."""
    rate = _env_float(RULE_SAMPLE_ENV, RULE_SAMPLE_DEFAULT)
    return int(hashlib.sha1(event_id.encode("utf-8")).hexdigest()[:8], 16) / 2**32 < rate


def _event_frame(ev: Dict[str, Any]) -> str:
    """Structure only: never the label, actor or valence (see the module docstring)."""
    parts = [f"evidence {ev.get('evidence')}"]
    for key in ("cause_key", "outcome_key", "trigger", "exec_domain", "topic_domain"):
        if ev.get(key):
            parts.append(f"{key.replace('_', ' ')} {ev[key]}")
    if ev.get("action_signature"):
        parts.append(f"action {str(ev['action_signature'])[:120]}")
    return "event: " + "; ".join(parts)


def _event_prompt(frame: str, options: Sequence[str], descriptions: Dict[str, str], what: str) -> str:
    menu = "\n".join(f"{o} = {descriptions.get(o, '')}".rstrip(" =") for o in options)
    return f"{frame}\n\nWhich {what} is this event?\n{menu}\n\nAnswer with exactly one word: " + ", ".join(options) + "."


def score_event(ev: Dict[str, Any], brain: Optional[Callable[[str], str]] = None) -> int:
    """Score ONE event with ``event_family`` and then ``event_type:<family>``; one
    shadow row per decision. A rule-labeled event (family set) carries its rule family
    and label as the free, exact reference. A Layer-3 event (family None) gets the Brain
    reference on a sample or when the Oracle is unsure. Blocking: run on the
    ``event_oracle`` lane. Returns the rows emitted. Never raises."""
    rows = 0
    try:
        from backend.memory import event_alphabet as ea

        register_consumers()
        frame = _event_frame(ev)
        rule_family = ev.get("family") if ev.get("family") in ea.FAMILIES else None

        fam_ds = _decide(EVENT_FAMILY, FAMILY_ORDER, frame, FAMILY_INSTRUCTION)
        fam_ref = rule_family
        if fam_ds is not None:
            if rule_family is None and (
                    _brain_sampled(EVENT_FAMILY)
                    or float(fam_ds.confidence) < _env_float(LOW_CONF_ENV, LOW_CONF_DEFAULT)):
                fam_descr = {f: ", ".join(family_labels(f)[:4]) for f in FAMILY_ORDER}
                fam_ref = _brain_label(
                    brain, _event_prompt(frame, FAMILY_ORDER, fam_descr, "family"), FAMILY_ORDER)
            emit_row(_row(EVENT_FAMILY, fam_ds, fam_ref))
            rows += 1

        family = fam_ref or (fam_ds.chosen if fam_ds is not None else None)
        labels = family_labels(family) if family in ea.FAMILIES else []
        if labels:
            type_id = type_consumer_id(family)
            type_ds = _decide(type_id, labels, frame, TYPE_INSTRUCTION)
            if type_ds is not None:
                type_ref = None
                if rule_family is not None:
                    type_ref = ev.get("label") if ev.get("label") in labels else None
                elif fam_ref is not None and (
                        _brain_sampled(type_id)
                        or float(type_ds.confidence) < _env_float(LOW_CONF_ENV, LOW_CONF_DEFAULT)):
                    descr = {n: s.description for n, s in ea.registered_labels().items()}
                    type_ref = _brain_label(
                        brain, _event_prompt(frame, labels, descr, "label"), labels)
                emit_row(_row(type_id, type_ds, type_ref))
                rows += 1
    except Exception as e:  # noqa: BLE001 - a shadow never raises
        logger.warning("[event_oracle] score_event failed: %r", e)
    return rows


def _collect_pending(conn: Any, brain: Optional[Callable[[str], str]]) -> int:
    """The ``memory_events`` lane job (the connection's single writer reads too): pick
    the events newer than the watermark that need scoring, queue one scoring job each.
    Layer-3 events (family NULL) always; rule-labeled events only when sampled."""
    from backend.utils.durability_queue import lane

    with _PASS_LOCK:
        watermark = _PASS_STATE["watermark"]
    try:
        fetched = conn.execute(
            f"SELECT {_EVENT_COLS} FROM memory_events WHERE ts > ? ORDER BY ts LIMIT ?",
            (watermark, PASS_LIMIT),
        ).fetchall()
    except Exception as e:  # noqa: BLE001 - no table / locked: next pass
        logger.debug("[event_oracle] pending read skipped: %r", e)
        return 0
    if not fetched:
        return 0
    names = [c.strip() for c in _EVENT_COLS.split(",")]
    queued = 0
    for r in fetched:
        ev = dict(zip(names, tuple(r)))
        if ev["family"] is None or (ev["label_source"] == "rule" and _rule_sampled(ev["event_id"])):
            if lane("event_oracle").submit("event_oracle:event", score_event, ev, brain):
                queued += 1
    with _PASS_LOCK:
        _PASS_STATE["watermark"] = max(_PASS_STATE["watermark"], float(fetched[-1][1]))
    return queued


def schedule_pass(conn: Any, brain: Optional[Callable[[str], str]] = None, *,
                  force: bool = False) -> bool:
    """Queue one bounded pass over new events on the ``memory_events`` lane, at most
    once per ``PASS_MIN_INTERVAL_S`` (``force`` skips the throttle). Never blocks."""
    try:
        from backend.utils.durability_queue import lane

        now = time.monotonic()
        with _PASS_LOCK:
            if not force and now - _PASS_STATE["last_pass"] < PASS_MIN_INTERVAL_S:
                return False
            _PASS_STATE["last_pass"] = now
        return bool(lane("memory_events").submit("event_oracle:pass", _collect_pending, conn, brain))
    except Exception as e:  # noqa: BLE001
        logger.debug("[event_oracle] pass submit skipped: %r", e)
        return False
