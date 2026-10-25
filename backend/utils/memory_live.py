"""Live taps for the Memory surface: what IRIS does to its memory, as it happens.

The Memory dashboard shows memory being used from REAL events only
(docs/Design/Memory-Cortex/MEMORY-DASHBOARD-DESIGN.md section 10.1 and 11). Three
messages reach the frontend as the window event ``iris:ws_message`` with
``detail = {type, payload}``. Every message is ONE BATCH: a list plus ``dropped``.

  {"type": "memory_event",    "payload": {"events":    [<memory_event>, ...],    "dropped": int}}
  {"type": "landmark_update", "payload": {"updates":   [<landmark_update>, ...], "dropped": int}}
  {"type": "oracle_decision", "payload": {"decisions": [<oracle_decision>, ...], "dropped": int}}

``memory_event`` item keys (all always present, null when the row has no value):
  event_id, ts, family, label, valence, actor, evidence, episode_id, thread_id,
  topic_domain, landmark_id, recall_trace_id, source, refs
  (``landmark_id`` is the landmark the row names in links/payload; ``recall_trace_id``
  is set on RECALL_* rows; ``source`` + ``refs`` (a list of chain ids) on RECALL_DELIVERED.
  Ids and labels only - never message text.)
``landmark_update`` item keys: landmark_id, kind, activation_count, tier, survivor_id, ts
  kind = activated | promoted | stale | demoted | dissolved | merged
  (``activation_count`` on activated, ``tier`` on activated/promoted/stale/demoted,
  ``survivor_id`` on merged; null otherwise.)
``oracle_decision`` item keys: consumer, job, confidence, chosen, acted, options, ts
  acted = enforced | sampled | shadow;  chosen = a string, or a bool for a yes/no consumer
  job = the consumer's Oracle job (null if unknown); options = [{name, p}], the top OPTIONS_MAX of the row's
  candidate distribution by p ([] when the row carries none - tool_choice's menu is a count of names)

WHERE THE TAPS HOOK (CLAUDE.md: answer path vs side lanes). Each tap is called by an
EXISTING single writer right AFTER its row is written - ``memory_events.emit_event``
(the memory_events lane), the landmark writers (landmark.py, profile.py, the Kyudo
integrity events) and the ledger lane's ``_ingest`` (tool_bridge). A tap that is never
reached (the write raised) broadcasts nothing. No tap runs on the answer path, none
writes anything, none starts a thread per row.

COALESCING. A tap only appends one small dict to a bounded buffer (cost: one lock and
one append). ONE daemon thread wakes every ``TICK_S`` (250 ms) while something is
buffered and sends at most ``MAX_PER_TICK`` (50) items per type as ONE message. The
buffer holds at most ``BUFFER_CAP`` (200) items per type; an item that finds it full is
DROPPED and COUNTED: the next message carries ``dropped`` (the surface knows its stream
has a gap and can re-read the REST snapshot) and the tick logs the count. Evaluation
runs write thousands of rows a minute; the tap never waits and never grows.

Cross-thread: the drain thread hands the message to the main event loop with
``asyncio.run_coroutine_threadsafe(ws_manager.broadcast(msg), loop)`` - the pattern of
tool_bridge / ws_event_bridge. Off switch: ``IRIS_MEMORY_LIVE=0``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

TICK_S = 0.25          # one batched message per type per tick
MAX_PER_TICK = 50      # hard cap of items in one message
BUFFER_CAP = 200       # items waiting per type; beyond it an item is dropped and counted
DRAIN_IDLE_S = 1.0     # the drain re-reads the buffers at least this often, woken or not

# message type -> the payload key that holds its list
_LIST_KEY = {"memory_event": "events", "landmark_update": "updates",
             "oracle_decision": "decisions"}

_lock = threading.Lock()
_bufs: Dict[str, Deque[dict]] = {k: deque() for k in _LIST_KEY}
_dropped: Dict[str, int] = {k: 0 for k in _LIST_KEY}          # since the last message
_stats: Dict[str, int] = {"tapped": 0, "sent_items": 0, "sent_messages": 0,
                          "dropped": 0, "unheard": 0, "send_failed": 0}
_wake = threading.Event()
_thread: Optional[threading.Thread] = None
_thread_lock = threading.Lock()
_tick = 0

# Where a finished message goes. Returns True when handed to a listener. Tests replace it.
_sender: Optional[Callable[[dict], bool]] = None


def enabled() -> bool:
    """False when IRIS_MEMORY_LIVE=0 (read per call: the switch works without a restart)."""
    return os.environ.get("IRIS_MEMORY_LIVE", "1") != "0"


def stats() -> Dict[str, int]:
    """Counters since start: tapped, sent_items, sent_messages, dropped, unheard, send_failed."""
    with _lock:
        return dict(_stats)


def set_sender(fn: Optional[Callable[[dict], bool]]) -> None:
    """Replace the message sender (tests). None restores the WebSocket sender."""
    global _sender
    _sender = fn


def reset() -> None:
    """Empty the buffers and counters (tests)."""
    with _lock:
        for k in _LIST_KEY:
            _bufs[k].clear()
            _dropped[k] = 0
        for k in _stats:
            _stats[k] = 0


# ── the taps (called by the single writers, after their row is written) ─────

def _clip(value: Any, n: int = 64) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    return str(value)[:n]


def _push(kind: str, item: dict) -> None:
    with _lock:
        _stats["tapped"] += 1
        buf = _bufs[kind]
        if len(buf) >= BUFFER_CAP:
            _dropped[kind] += 1
            _stats["dropped"] += 1
            return
        buf.append(item)
    if _thread is None or not _thread.is_alive():
        _start_drain()
    _wake.set()


def _start_drain() -> None:
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_drain_forever, daemon=True, name="iris-memory-live")
        _thread.start()


def memory_event(*, event_id: str, ts: float, family: Optional[str], label: str,
                 valence: Optional[str], actor: Optional[str], evidence: Optional[str],
                 episode_id: Optional[str], thread_id: Optional[str],
                 topic_domain: Optional[str], links: Optional[dict],
                 payload: Optional[dict]) -> None:
    """One new memory_events row. Called by memory_events.emit_event after the write."""
    try:
        if not enabled():
            return
        links = links if isinstance(links, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        delivered = label == "RECALL_DELIVERED"
        refs = payload.get("refs") if delivered else None
        _push("memory_event", {
            "event_id": event_id, "ts": ts, "family": family, "label": label,
            "valence": valence, "actor": actor, "evidence": evidence,
            "episode_id": episode_id, "thread_id": thread_id, "topic_domain": topic_domain,
            "landmark_id": _clip(links.get("landmark_id") or links.get("landmark")
                                 or payload.get("landmark_id") or payload.get("landmark"), 80),
            "recall_trace_id": _clip(links.get("recall_trace_id")) if str(label).startswith("RECALL_") else None,
            "source": _clip(payload.get("source"), 32) if delivered else None,
            "refs": ([str(r)[:64] for r in refs[:8]] if isinstance(refs, list) else None),
        })
    except Exception as exc:  # noqa: BLE001 - a tap never breaks its writer
        logger.warning("[memory_live] tap failed kind=memory_event event=%s: %s", event_id, exc)


def landmark_update(landmark_id: str, kind: str, *, activation_count: Optional[int] = None,
                    tier: Optional[str] = None, survivor_id: Optional[str] = None) -> None:
    """A landmark was activated / promoted / went stale / was demoted, dissolved or merged.
    Called by the landmark writers after their UPDATE."""
    try:
        if not enabled():
            return
        _push("landmark_update", {
            "landmark_id": landmark_id, "kind": kind, "activation_count": activation_count,
            "tier": tier, "survivor_id": survivor_id, "ts": time.time(),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[memory_live] tap failed kind=landmark_update landmark=%s: %s",
                       landmark_id, exc)


_ACTED = {"enforced": "enforced", "engine": "enforced", "sampled": "sampled"}
OPTIONS_MAX = 8      # options drawn per decision: the top of the distribution is the picture


def _options(candidates: Any) -> List[dict]:
    """The top OPTIONS_MAX of a row's candidate distribution, [{name, p}] by p descending. The engine's rows carry
    a list of {name, prob}; a count (tool_choice's menu size) or anything else has no distribution: []."""
    if not isinstance(candidates, (list, tuple)):
        return []
    out = [{"name": _clip(c["name"], 80), "p": round(float(c["prob"]), 4)}
           for c in candidates
           if isinstance(c, dict) and _clip(c.get("name"), 80) is not None
           and isinstance(c.get("prob"), (int, float)) and not isinstance(c.get("prob"), bool)]
    out.sort(key=lambda o: o["p"], reverse=True)
    return out[:OPTIONS_MAX]


def _job_of(decision: dict) -> Optional[str]:
    """The consumer's Oracle job: the row's own, else the decision engine's table (event_type:<family> maps like
    event_type). The ledger's whitelist does not carry "job", so the table is the usual source."""
    job = decision.get("job")
    if isinstance(job, str) and job:
        return job[:40]
    try:
        from backend.agent.decision_engine import oracle_job

        return oracle_job(str(decision.get("consumer_id"))).name
    except Exception:  # noqa: BLE001 - a missing job is null, never a lost decision
        return None


def oracle_decision(decision: dict) -> None:
    """One Oracle decision row (the ledger row's ``decision`` block). Called by the ledger
    lane after the row is ingested. A block without a consumer is not an Oracle decision."""
    try:
        if not enabled() or not isinstance(decision, dict) or not decision.get("consumer_id"):
            return
        conf = decision.get("confidence")
        chosen = decision.get("chosen")
        if not isinstance(chosen, (bool, int, float)):
            chosen = _clip(chosen, 80)          # a tool name or a label; a yes/no consumer keeps its bool
        _push("oracle_decision", {
            "consumer": _clip(decision.get("consumer_id"), 64),
            "confidence": round(float(conf), 4) if isinstance(conf, (int, float)) else None,
            "chosen": chosen,
            "acted": _ACTED.get(str(decision.get("route")), "shadow"),
            "job": _job_of(decision),
            # the engine rows carry the distribution in "candidates"; tool_choice keeps a count there and its
            # distribution in "candidate_probs"
            "options": _options(decision.get("candidates")) or _options(decision.get("candidate_probs")),
            "ts": time.time(),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[memory_live] tap failed kind=oracle_decision: %s", exc)


# ── the drain: one thread, one tick ─────────────────────────────────────────

def _drain_forever() -> None:
    while True:
        # Bounded: a wake that never comes (the event object replaced - the contract tests swap `_wake` per test, and a
        # drain parked on the old object never sent again, 2026-10-25) costs at most one second, then the buffers are
        # read anyway. An idle pass is one lock and nothing to send.
        _wake.wait(DRAIN_IDLE_S)
        time.sleep(TICK_S)          # let one tick's worth of rows gather
        _wake.clear()
        try:
            if flush_once():
                _wake.set()         # a backlog is left: next tick
        except Exception as exc:  # noqa: BLE001 - the drain never dies
            logger.warning("[memory_live] tick failed: %s", exc)


def flush_once() -> bool:
    """Send one tick: up to MAX_PER_TICK items per type, one message per type.
    Returns True when items are still buffered. Public so tests run a tick without sleeping."""
    global _tick
    batches: List[tuple] = []
    more = False
    with _lock:
        _tick += 1
        tick = _tick
        for kind, buf in _bufs.items():
            dropped = _dropped[kind]
            if not buf and not dropped:
                continue
            n = min(MAX_PER_TICK, len(buf))
            items = [buf.popleft() for _ in range(n)]
            _dropped[kind] = 0
            more = more or bool(buf)
            batches.append((kind, items, dropped))
    for kind, items, dropped in batches:
        if dropped:
            logger.warning("[memory_live] tick=%d kind=%s buffer full: dropped %d item(s) "
                           "(cap %d); sent %d", tick, kind, dropped, BUFFER_CAP, len(items))
        if not items:
            continue
        msg = {"type": kind, "payload": {_LIST_KEY[kind]: items, "dropped": dropped}}
        try:
            sent = (_sender or _ws_send)(msg)
        except Exception as exc:  # noqa: BLE001
            sent = False
            with _lock:
                _stats["send_failed"] += 1
            logger.warning("[memory_live] tick=%d kind=%s send failed: %s", tick, kind, exc)
        with _lock:
            if sent:
                _stats["sent_messages"] += 1
                _stats["sent_items"] += len(items)
            else:
                _stats["unheard"] += len(items)
    return more


def _ws_send(msg: dict) -> bool:
    """Hand ``msg`` to the main loop's broadcast. False = nobody to hear it (no loop, no client).
    The gateway is only PEEKED at: this module never constructs it."""
    mod = sys.modules.get("backend.iris_gateway")
    gw = getattr(mod, "_iris_gateway", None)
    loop = getattr(gw, "_main_loop", None)
    ws = getattr(gw, "_ws_manager", None)
    if ws is None or loop is None or not loop.is_running() or ws.get_connection_count() == 0:
        return False
    fut = asyncio.run_coroutine_threadsafe(ws.broadcast(msg), loop)
    fut.add_done_callback(_log_send_error)
    return True


def _log_send_error(fut: "asyncio.Future") -> None:
    try:
        exc = fut.exception()
    except Exception:  # noqa: BLE001 - cancelled
        return
    if exc is not None:
        with _lock:
            _stats["send_failed"] += 1
        logger.warning("[memory_live] broadcast failed: %s", exc)
