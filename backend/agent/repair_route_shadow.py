"""repair_route - ONE SHADOW question at each failed check of a Workbench code node (T7.15).

The question (a choice with two fixed labels): after this failed check, does the tool
model try again alone (REPAIR) or does the Brain write a repair brief (ESCALATE)?

Nothing here decides anything. The stated rule decides (node_executor.run_node: the
SECOND failed check calls the escalation hook, once per node). The Oracle scores the
same moment so the pair can earn the bar (docs/architecture/oracle.md); the node's
behaviour is the same with this module absent, failing or slow.

WHERE: ``NodeContext.on_check`` (node_executor.run_node), once per run_python check
result; the kernel's code-mode branch (kernel/der/node.py) owns one ``RepairTracker``
per node execution.

FRAME (job ``judge_repair``): attempt (the failed attempt's number), error_type (the
body's exception type, or CheckFailed when the body ran), check_error (the worker's
check message, <= 200 chars) and failure_rows (the typed BUG / OBSTACLE / DEAD_END
event counts for this thread, read ON THE LANE from memory_events; the field is
LEFT OUT when the read is unavailable - never a made-up 0). Never the script, the
digest, the brief, or anything from the Brain's repair note.

LABEL (outside: the harness's own check, never the Oracle's guess or the Brain's say-so),
joined at the FIRST PASSING check after the row:
  REPAIR    = it passed and NO Brain brief was injected between the row and the pass
              (the tool model alone fixed it);
  ESCALATE  = it passed and a Brain brief WAS injected between the row and the pass
              (the tool model had failed on its own; the brief's attempt passed);
  none      = no check passed after the row before the node ended (nobody fixed it:
              neither answer is shown right), reason ``no_pass_after``.
WHAT IT CANNOT SEE: the rule always escalates at the second failure, so a row for
attempt >= 2 can only ever be labelled ESCALATE (or none) - whether the tool model
alone would also have passed is never observed. Attempt 1 rows are the only ones that
can be REPAIR. Read the bar per attempt, never pooled.

Both the score and the label run on ``lane("oracle_shadow")`` (ordered: the label job
is FIFO behind its score job), never on the node's path. Bounded: the held rows are a
drop-oldest map; every drop and failure is counted (``stats``).
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("repair_route_shadow")

CONSUMER_ID = "repair_route"
REPAIR = "REPAIR"
ESCALATE = "ESCALATE"
LABELS = (REPAIR, ESCALATE)
INSTRUCTION = ("After this failed check, should the tool model try again alone (REPAIR) "
               "or should the Brain write a repair brief (ESCALATE)?")
VERSION = "repair_route/v1"
ESCALATE_AT = 2   # the stated rule: node_executor escalates on the 2nd failed check

_CHECK_ERROR_CAP = 200
_ERROR_TYPE_CAP = 60
_STATE_CAP = 1200
_FAILURE_LABELS = ("BUG", "OBSTACLE", "DEAD_END")
_FAILURE_WINDOW = 50      # the newest events of the thread that are looked at
_HELD_CAP = 256           # rows awaiting their label

# Sentinel: adopt the module-level engine singleton. ``ENGINE = None`` means NO
# ENGINE - a shadow scorer never loads the model. Tests replace ENGINE.
AUTO_ENGINE = object()
ENGINE: Any = AUTO_ENGINE

_ROW_SINK: Optional[Callable[[dict], None]] = None
_LOCK = threading.Lock()
_HELD: "OrderedDict[str, dict]" = OrderedDict()
_STATS: Dict[str, int] = {
    "queued": 0, "lane_dropped": 0, "no_score": 0, "held_dropped": 0,
    "labelled": 0, "unlabelled": 0, "sink_failed": 0, "failure_rows_unavailable": 0,
    "errors": 0,
}


def _count(key: str, n: int = 1) -> None:
    with _LOCK:
        _STATS[key] = _STATS.get(key, 0) + n


def set_row_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Install (or clear) the process-wide row sink (the kernel's ledger)."""
    global _ROW_SINK
    _ROW_SINK = sink


def emit_row(row: Optional[dict]) -> None:
    """Hand a row to the installed sink, else log it. Never raises; a sink that
    raises is COUNTED (sink_failed) and the row is logged instead."""
    if not row:
        return
    sink = _ROW_SINK
    if callable(sink):
        try:
            sink(row)
            return
        except Exception as e:  # noqa: BLE001 - an observer never blocks
            _count("sink_failed")
            logger.warning("[repair_route] row sink failed consumer=%s: %r",
                           row.get("consumer_id"), e)
    logger.info("[repair_route] row chosen=%s conf=%s attempt=%s label=%s",
                row.get("chosen"), row.get("confidence"), row.get("attempt"),
                row.get("outside_label"))


def rule_choice(attempt: int, can_escalate: bool = True) -> str:
    """What the STATED rule does at this failed check (the incumbent)."""
    return ESCALATE if (can_escalate and attempt == ESCALATE_AT) else REPAIR


def _register() -> None:
    from backend.agent.decision_engine import (
        get_consumer_spec,
        needs_upgrade,
        register_declared,
    )

    if needs_upgrade(get_consumer_spec(CONSUMER_ID)):
        register_declared(CONSUMER_ID, INSTRUCTION, LABELS)


def _scope_now() -> Dict[str, str]:
    """The turn/step ids as VALUES on the caller's thread (the lane's own context
    says nothing)."""
    try:
        from backend.agent.decision_engine import scope_now

        return dict(scope_now() or {})
    except Exception:  # noqa: BLE001 - scope is best-effort
        return {}


def failure_rows(conn: Any, thread_id: str) -> str:
    """"BUG=2 OBSTACLE=0 DEAD_END=1" - the typed failure events among this thread's
    newest ``_FAILURE_WINDOW`` memory_events, or "" when they cannot be read.
    Blocking (lane only). The inner query rides idx_memory_events_thread_ts
    (thread_id, ts): one index range, <= 50 rows."""
    if conn is None or not thread_id:
        return ""
    try:
        counts = dict(conn.execute(
            "SELECT label, COUNT(*) FROM (SELECT label FROM memory_events "
            "WHERE thread_id = ? ORDER BY ts DESC LIMIT ?) "
            "WHERE label IN ('BUG', 'OBSTACLE', 'DEAD_END') GROUP BY label",
            (thread_id, _FAILURE_WINDOW)).fetchall())
        return " ".join(f"{k}={int(counts.get(k, 0))}" for k in _FAILURE_LABELS)
    except Exception as e:  # noqa: BLE001 - counted; the field is left out
        _count("failure_rows_unavailable")
        logger.debug("[repair_route] failure rows unreadable: %r", e)
        return ""


def _score_job(consult_id: str, attempt: int, error_type: str, check_error: str,
               conn: Any, thread_id: str, scope: Dict[str, str], rule: str) -> None:
    """Lane job 1: read the typed failure rows, score the question, hold the row."""
    try:
        engine = ENGINE
        if engine is AUTO_ENGINE:
            from backend.agent.decision_engine import get_decision_engine

            engine = get_decision_engine()
        if engine is None:
            _count("no_score")
            return
        _register()
        frame: Dict[str, Any] = {
            "attempt": str(attempt), "error_type": error_type, "check_error": check_error,
        }
        rows = failure_rows(conn, thread_id)
        if rows:
            frame["failure_rows"] = rows
        ds = engine.decide(CONSUMER_ID, list(LABELS), frame)
        if ds is None:
            _count("no_score")
            return
        state, key = "", ""
        try:
            from backend.agent.decision_engine import job_input
            from backend.agent.surface_shadow import input_key

            state = job_input(CONSUMER_ID, frame).text[:_STATE_CAP]
            key = input_key(CONSUMER_ID, state, None)
        except Exception:  # noqa: BLE001 - a replay key never blocks a row
            pass
        row: Dict[str, Any] = {
            "consumer_id": CONSUMER_ID,
            "engine": str(getattr(engine, "model_id", "") or ""),
            "job": "judge_repair", "criteria_version": VERSION,
            "chosen": ds.chosen,
            "confidence": round(float(ds.confidence), 4),
            "candidates": [{"name": c.name, "prob": round(float(c.prob), 4)}
                           for c in (ds.distribution or ())],
            "engine_latency_ms": ds.engine_latency_ms,
            "shadow": True, "state": state, "input_key": key,
            "attempt": int(attempt),
            # what the stated rule did here: a record, NOT a label (never scored against)
            "rule_choice": rule,
        }
        row.update(scope)
        with _LOCK:
            _HELD[consult_id] = row
            while len(_HELD) > _HELD_CAP:
                _HELD.popitem(last=False)
                _STATS["held_dropped"] += 1
    except Exception as e:  # noqa: BLE001 - a shadow never raises
        _count("errors")
        logger.warning("[repair_route] consult failed attempt=%s: %r", attempt, e)


def _label_job(consult_id: str, label: Optional[str], reason: str) -> None:
    """Lane job 2 (FIFO behind job 1): stamp the outcome and write the row."""
    try:
        with _LOCK:
            row = _HELD.pop(consult_id, None)
        if row is None:
            return  # no score (engine away) or dropped from the bounded hold
        if label is None:
            row["unlabelled"] = reason
            _count("unlabelled")
        else:
            row["outside_label"] = label
            row["label_source"] = "outcome"
            row["label_detail"] = reason
            _count("labelled")
        emit_row(row)
    except Exception as e:  # noqa: BLE001
        _count("errors")
        logger.warning("[repair_route] label failed consult=%s: %r", consult_id, e)


def _submit(name: str, fn: Callable, *args: Any) -> bool:
    try:
        from backend.utils.durability_queue import lane

        if lane("oracle_shadow").submit(name, fn, *args):
            return True
        _count("lane_dropped")
    except Exception as e:  # noqa: BLE001
        _count("errors")
        logger.warning("[repair_route] lane submit failed %s: %r", name, e)
    return False


class RepairTracker:
    """One node execution's open rows. Used from the node's own thread only; the
    scoring and the labelling run on the lane. Every method never raises."""

    def __init__(self, thread_id: str = "", conn: Any = None, can_escalate: bool = True):
        self._thread_id = str(thread_id or "")
        self._conn = conn
        self._can_escalate = bool(can_escalate)
        self._open: List[Dict[str, Any]] = []   # {"id": str, "briefed": bool}

    def failed(self, attempt: int, error_type: str, check_error: str) -> None:
        """A check failed: queue ONE consult and hold the row open for its label."""
        try:
            consult_id = uuid.uuid4().hex
            if _submit(CONSUMER_ID, _score_job, consult_id, int(attempt),
                       str(error_type or "CheckFailed")[:_ERROR_TYPE_CAP],
                       " ".join(str(check_error or "").split())[:_CHECK_ERROR_CAP],
                       self._conn, self._thread_id, _scope_now(),
                       rule_choice(int(attempt), self._can_escalate)):
                _count("queued")
                self._open.append({"id": consult_id, "briefed": False})
        except Exception as e:  # noqa: BLE001
            _count("errors")
            logger.warning("[repair_route] failed() raised: %r", e)

    def briefed(self) -> None:
        """The Brain's repair brief was injected for the next attempt."""
        for o in self._open:
            o["briefed"] = True

    def passed(self) -> None:
        """A check passed: every open row gets its label."""
        try:
            for o in self._open:
                label = ESCALATE if o["briefed"] else REPAIR
                _submit("repair_route_label", _label_job, o["id"], label,
                        "pass_after_brief" if o["briefed"] else "pass_without_brief")
        except Exception as e:  # noqa: BLE001
            _count("errors")
            logger.warning("[repair_route] passed() raised: %r", e)
        self._open = []

    def end(self) -> None:
        """The node ended: rows still open never saw a pass - written unlabelled."""
        try:
            for o in self._open:
                _submit("repair_route_label", _label_job, o["id"], None, "no_pass_after")
        except Exception as e:  # noqa: BLE001
            _count("errors")
            logger.warning("[repair_route] end() raised: %r", e)
        self._open = []


def stats() -> Dict[str, int]:
    """Counters (queued, drops, labelled, failures) for the log and tests."""
    with _LOCK:
        out = dict(_STATS)
        out["held"] = len(_HELD)
        return out


def reset() -> None:
    """Test seam."""
    with _LOCK:
        _HELD.clear()
        for k in _STATS:
            _STATS[k] = 0
