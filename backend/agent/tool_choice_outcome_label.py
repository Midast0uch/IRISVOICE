"""Attach the STEP'S completion to the tool_choice rows decided in it.

WHY THIS EXISTS (measured 2026-11-07, data/memory.db, active engine)
    Two labels failed before this one, and those failures are the reason for the
    rule below:

    * tc-decide-v4 used ``outside_label = bool(called == chosen and ok)``. On a
      binding pick the model writes only the ARGUMENTS, so ``called == chosen``
      is true by construction and the label reduces to ``ok``: "the call ran".
      698 distinct rows: 624 ok / 74 failed, oof AUROC 0.5849. A read_file on a
      path the frame named but the model then mistyped is a wrong ARGUMENT, not
      a wrong tool choice.

    * tc-decide-v6 used the step's ``verified_label`` (VERIFIED -> True,
      UNVERIFIED/FAILED -> False). Live gate, 100% sampling, force floor 0:
      19 settled rows, ALL UNVERIFIED, zero VERIFIED. The DER verifier grades
      the step OUTPUT against the step's expected text; a successful read that
      returns the file does not match an expected sentence, so it is UNVERIFIED.
      The label was single-class (all False) and could not rank anything.

THE LABEL (tc-decide-v7, stated, not computed)
    ``outside_label`` = the CALL succeeded AND the step was NOT retried.
      - the call succeeded: the row's own ``outcome_label == "ok"`` (the
        call-level outcome, the v4 precedent);
      - the step was not retried: the step reached finalize without taking the
        failure path and without a post-finalize artifact graft.
    A failed step is exactly the step the DER recovery path retries, grafts or
    splits, so "retried" is a structural signal, not a text match.
    ``label_reference`` = "step_completed"; ``step_outcome`` = COMPLETED/FAILED.

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
    the flag on; the cohort carries a NEW criteria stamp (tc-decide-v7), so the
    old and new labels never blend.

DELETION CONTRACT (keep this true)
    - backend/agent/tool_choice_outcome_label.py   (this file, all logic)
    - backend/agent/tool_decision.py               (the defer call in
      _record_shadow_row and the outside_label removal in label_decided_row)
    - backend/agent/agent_kernel.py                (the stamp at the failure
      branch and after the post-finalize artifact graft)
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

# Bounded, drop-oldest, always COUNTED (repo standard: never lose a measurement
# silently). tool_choice has several rows per step, so the cap is in ROWS.
_MAX_PENDING_ROWS = 4096
_MAX_SETTLED = 512

_LOCK = threading.Lock()
_PENDING: "OrderedDict[Tuple[str, str], List[Dict[str, Any]]]" = OrderedDict()
_PENDING_ROWS = 0
# A step that settled before its row arrived. The row is normally built at the
# call result, which precedes settle, but a concurrent step can race; remember
# the label (bounded) so the row is still stamped instead of flushed unlabelled.
_SETTLED: "OrderedDict[Tuple[str, str], bool]" = OrderedDict()

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


def _apply(row: Dict[str, Any], step_ok: bool) -> None:
    """Attach the step's completion to one row.

    The pick is right only when BOTH hold: the call it made worked, and the
    step it served was not retried. A call that failed is a wrong pick even in
    a completed step; a step that failed is a wrong pick even when its call ran.
    """
    row["label_source"] = "outcome"
    row["label_reference"] = "step_completed"
    row["step_outcome"] = "COMPLETED" if step_ok else "FAILED"
    row["outside_label"] = bool(step_ok and row.get("outcome_label") == "ok")


def _write(entry: Dict[str, Any], step_ok: Optional[bool]) -> None:
    global _WRITE_FAILED
    row = entry["row"]
    if step_ok is not None:
        _apply(row, bool(step_ok))
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
            flush_now = key in _SETTLED
            if flush_now:
                step_ok = _SETTLED.pop(key)
                _SETTLED_AHEAD += 1
            else:
                _PENDING.setdefault(key, []).append(entry)
                _bump_pending_locked(1)
        if flush_now:
            _write(entry, step_ok)
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
          step_ok: bool) -> int:
    """Attach the step's completion to every held row and WRITE them.

    ``step_ok`` is True only for a step that reached finalize without a retry.
    Returns the number of rows emitted. A step that never held a row keeps the
    value for a row still in flight (bounded). Idempotent per step: a second
    settle finds nothing held. Never raises.
    """
    if not enabled():
        return 0
    try:
        key = _key(step_id, turn_id)
        if key is None:
            return 0
        ok = bool(step_ok)
        with _LOCK:
            entries = _PENDING.pop(key, None)
            if entries is None:
                # Keep the outcome for a row still in flight (bounded).
                _SETTLED[key] = ok
                while len(_SETTLED) > _MAX_SETTLED:
                    _SETTLED.popitem(last=False)
                return 0
            global _PENDING_ROWS
            _PENDING_ROWS -= len(entries)
        for entry in entries:
            _write(entry, ok)
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
            "flushed_unsettled": _FLUSHED,
            "write_failed": _WRITE_FAILED,
        }
