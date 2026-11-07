"""Attach the STEP'S verified outcome to the tool_choice rows decided in it.

WHY THIS EXISTS (measured 2026-11-07, data/memory.db, active engine)
    The decided tool_choice row used ``outside_label = bool(called == chosen and
    ok)``. On a binding pick the model writes only the ARGUMENTS, so
    ``called == chosen`` is true by construction and the label reduces to ``ok``:
    "the call ran".  Measured on ``tc-decide-v4`` (698 distinct rows): 74 wrong
    and EVERY one carried ``outcome_label=failed``. There is no ``overridden``
    class, so the consumer was graded on whether the model's arguments worked,
    not on whether the Oracle's TOOL was the right next action. A read_file on a
    path the frame said existed but the model then mistyped is a wrong ARGUMENT,
    not a wrong tool choice. oof AUROC sat at 0.5849 under that label.

    The step's own ``verified_label`` (VERIFIED / UNVERIFIED / FAILED) is the
    outside reference REQ-7 already prefers. It answers the question the pick
    actually asks: did this choice serve a step that did its job?

THE LABEL (stated, not computed)
    VERIFIED   -> the step did its job. The pick served it: ``outside_label``
                  True.
    FAILED     -> the step did not do its job. ``outside_label`` False.
    UNVERIFIED -> the result did not demonstrate the expected output. The pick
                  is not proven right: ``outside_label`` False. This is the
                  review_verdict v10 precedent (2026-11-05): an unproven result
                  should not be waved through, and without this arm the cohort
                  is single-class (der_commits: 12,980 VERIFIED against 20
                  FAILED).

    A row whose step never settles is written with NO outside label. It is
    COUNTED as skipped by the report, never scored on the old call label - a
    blended cohort would look better than the label it claims to measure.

WHY DEFER (one row, one writer)
    The row is built at the CALL result (tool_decision.label_decided_row); the
    step settles later (_der_finalize_step). The single ledger writer copies the
    dict (``meta = dict(row)``), so a stamp applied after that write can never
    reach the ledger. Hold the row here and write it from ``stamp`` at settle.
    Same measured reason as backend.agent.review_outcome_label.

    This module allows SEVERAL rows per step (one per tool call). They are keyed
    by ``(turn_id, step_id)`` because ``step_id`` is the step's ordinal inside a
    turn ("s2"), not a globally unique id - the same defect review_outcome_label
    documents at 2047 rows over 55 ids.

WHY A FLAG, DEFAULT OFF (deletable wrapper)
    With IRIS_ORACLE_TOOL_CHOICE_OUTCOME unset, ``defer`` returns False and the
    call-age label is byte-identical to tc-decide-v5. The live gate is run with
    the flag on; the cohort carries a NEW criteria stamp (tc-decide-v6), so the
    old and new labels never blend.

DELETION CONTRACT (keep this true)
    - backend/agent/tool_choice_outcome_label.py   (this file, all logic)
    - backend/agent/tool_decision.py               (the defer call in
      _record_shadow_row and the outside_label removal in label_decided_row)
    - backend/agent/agent_kernel.py                (the stamp call at settle)
    - backend/tests/contract/test_tool_choice_outcome_label_contract.py
    Nothing else.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# Deletable wrapper switch (same convention as review_outcome_label).
ENV_FLAG = "IRIS_ORACLE_TOOL_CHOICE_OUTCOME"
CONSUMER = "tool_choice"

# The step settle values. Anything else leaves the row unlabelled: an unknown
# outcome must not invent a reference.
VERIFIED_LABELS = ("VERIFIED", "UNVERIFIED", "FAILED")

# How a settled step reads against "was this tool the right choice?".
TOOL_CHOICE_GROUND_TRUTH = {
    "VERIFIED": True,
    "UNVERIFIED": False,
    "FAILED": False,
}

# Bounded, drop-oldest, always COUNTED (repo standard: never lose a measurement
# silently). tool_choice has several rows per step, so the cap is in ROWS.
_MAX_PENDING_ROWS = 4096
_MAX_SETTLED = 512

_LOCK = threading.Lock()
_PENDING: "OrderedDict[Tuple[str, str], List[Dict[str, Any]]]" = OrderedDict()
_PENDING_ROWS = 0
# A step that settled before its row arrived. The row is normally built at the
# call result, which precedes settle, but a concurrent step can race; remember
# the label (bounded) so the row is still stamped instead of flushed on parity.
_SETTLED: "OrderedDict[Tuple[str, str], str]" = OrderedDict()

_DROPPED = 0
_SETTLED_AHEAD = 0
_FLUSHED = 0
_WRITE_FAILED = 0


def enabled() -> bool:
    """True when the owner turned the step-outcome label on. Read per call."""
    return os.environ.get(ENV_FLAG, "").strip() not in ("", "0", "false", "False")


def _key(step_id: Any, turn_id: Any) -> Optional[Tuple[str, str]]:
    sid = str(step_id or "").strip()
    if not sid:
        return None
    return (str(turn_id or "").strip(), sid)


def _apply(row: Dict[str, Any], label: Optional[str]) -> None:
    """Attach the settled outcome to one row. Unknown label = no label."""
    truth = TOOL_CHOICE_GROUND_TRUTH.get(str(label or "").upper())
    if truth is None:
        return
    row["label_source"] = "outcome"
    row["label_reference"] = "step_verified"
    row["step_outcome"] = str(label).upper()
    row["outside_label"] = bool(truth)


def _write(entry: Dict[str, Any], label: Optional[str]) -> None:
    global _WRITE_FAILED
    row = entry["row"]
    _apply(row, label)
    try:
        entry["write"](row)
    except Exception:  # noqa: BLE001 - a label never blocks a settle
        with _LOCK:
            _WRITE_FAILED += 1


def defer(row: Optional[Dict[str, Any]], write) -> bool:
    """HOLD a decided tool_choice row instead of writing it now.

    Returns True when the caller must NOT write (the row is held and ``stamp``
    writes it after the step settles). Returns False when the flag is off, the
    row is not a decided tool_choice row, it has no join key, or its outcome is
    one that must NOT be graded by the step (``finished`` / ``overridden``).
    Never raises.
    """
    if not enabled() or not isinstance(row, dict):
        return False
    global _SETTLED_AHEAD
    try:
        if row.get("consumer_id") != CONSUMER:
            return False
        # Only the rows produced by label_decided_row carry this marker. The
        # RespondDirect shadow rows (record_shadow_tool_choice) keep their
        # parity reference and are never held here.
        if row.get("label_source") != "outcome":
            return False
        # "finished" was never called (no evidence); "overridden" did not
        # stand (already a wrong pick, not a step-outcome question).
        if row.get("outcome_label") not in ("ok", "failed"):
            return False
        key = _key(row.get("step_id"), row.get("turn_id"))
        if key is None:
            return False
        entry = {"row": row, "write": write}
        with _LOCK:
            label = _SETTLED.pop(key, None)
            if label is not None:
                _SETTLED_AHEAD += 1
                flush_now = True
            else:
                flush_now = False
                _PENDING.setdefault(key, []).append(entry)
                _bump_pending_locked(1)
        if flush_now:
            _write(entry, label)
        return True
    except Exception:  # noqa: BLE001 - deferral never blocks a call
        return False


def _bump_pending_locked(delta: int) -> None:
    global _PENDING_ROWS, _DROPPED
    _PENDING_ROWS += delta
    while _PENDING_ROWS > _MAX_PENDING_ROWS and _PENDING:
        _, dropped = _PENDING.popitem(last=False)
        _PENDING_ROWS -= len(dropped)
        _DROPPED += len(dropped)


def stamp(step_id: Optional[str], turn_id: Optional[str],
          verified_label: Optional[str]) -> int:
    """Attach the settled outcome to every held row of this step and WRITE them.

    Returns the number of rows emitted. A step whose label the table cannot read
    emits its rows with no outside label (counted, never scored). Idempotent per
    step: a second settle finds nothing held. Never raises.
    """
    if not enabled():
        return 0
    try:
        key = _key(step_id, turn_id)
        if key is None:
            return 0
        label = str(verified_label or "").upper()
        if label not in VERIFIED_LABELS:
            label = ""
        with _LOCK:
            entries = _PENDING.pop(key, None)
            if entries is None:
                # Keep the outcome for a row still in flight (bounded).
                _SETTLED[key] = label
                while len(_SETTLED) > _MAX_SETTLED:
                    _SETTLED.popitem(last=False)
                return 0
            global _PENDING_ROWS
            _PENDING_ROWS -= len(entries)
        for entry in entries:
            _write(entry, label or None)
        return len(entries)
    except Exception:  # noqa: BLE001 - a label never blocks a settle
        return 0


def sweep() -> int:
    """Write every still-held row with NO outside label (its step never settled).

    Counted separately so a row loss is visible. Never raises.
    """
    global _PENDING_ROWS, _FLUSHED
    try:
        with _LOCK:
            pending = list(_PENDING.items())
            _PENDING.clear()
            _PENDING_ROWS = 0
        n = 0
        for _key_, entries in pending:
            for entry in entries:
                _write(entry, None)
                n += 1
        with _LOCK:
            _FLUSHED += n
        return n
    except Exception:  # noqa: BLE001
        return 0


def reset() -> None:
    """Clear all held state (tests and a clean shutdown)."""
    global _PENDING_ROWS, _DROPPED, _SETTLED_AHEAD, _FLUSHED, _WRITE_FAILED
    with _LOCK:
        _PENDING.clear()
        _SETTLED.clear()
        _PENDING_ROWS = 0
        _DROPPED = 0
        _SETTLED_AHEAD = 0
        _FLUSHED = 0
        _WRITE_FAILED = 0


def stats() -> Dict[str, int]:
    """Counters for the report/log. Never raises."""
    with _LOCK:
        return {
            "pending_rows": _PENDING_ROWS,
            "pending_steps": len(_PENDING),
            "dropped_overflow": _DROPPED,
            "recovered_after_settle": _SETTLED_AHEAD,
            "flushed_parity": _FLUSHED,
            "write_failed": _WRITE_FAILED,
        }
