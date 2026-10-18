"""Attach the STEP'S REAL OUTCOME to a pending review_verdict shadow row.

WHY (measured live 2026-10-09, data/memory.db)
    `review_verdict` was scored against PARITY only: the row records what d1
    said next to what the Brain's reviewer said, and `decision_label` marks the
    row correct when the two agree. That reference is not ground truth. The
    Brain's reviewer passes ~96% of steps, so a d1 row that correctly catches a
    bad step is scored WRONG for disagreeing. Measured: 42/143 correct (29%),
    AUROC 0.375 - i.e. WORSE THAN RANDOM, which is what a good catch looks like
    when you grade it against a colleague who rubber-stamps.

    The loop ALREADY knows the truth: `_der_finalize_step` computes a
    `verified_label` of VERIFIED / UNVERIFIED / FAILED for the same step. That
    is the outside label REQ-7 already prefers. This module carries it across.

THE TIMING PROBLEM THIS SOLVES
    The review row is written at REVIEW time (der_loop._shadow_review_verdict ->
    kernel._forward_consumer_rows -> the single ledger writer). The step settles
    LATER, in `_der_finalize_step`. So the outcome does not exist when the row
    is written, and the row cannot simply be re-written: the one-writer rule
    forbids a second writer, and the ledger row is already committed.

    Hence DEFER: hold the row in a small bounded in-memory map keyed by
    step_id, and stamp it at settle time. The label is attached to the SAME row
    object before the kernel's single writer emits it, so no second writer is
    opened and no row is rewritten in the ledger.

WHY A FLAG, DEFAULT OFF
    This touches the step-settle path. A bug there corrupts STEP OUTCOMES for
    the whole agent, not just the reviewer. The owner asked for a deletable
    wrapper: with the flag off, `stamp_review_outcome` is a no-op and the
    agent behaves exactly as at commit 0bdd1ad1. Deleting this module, the two
    try/except hooks in agent_kernel, and nothing else, returns the tree to
    that behaviour.

DELETION CONTRACT (keep this true)
    - backend/agent/review_outcome_label.py   (this file, all logic)
    - backend/agent/agent_kernel.py           (two try/except calls)
    - backend/tests/contract/test_review_outcome_label_contract.py
    Nothing else. No row-format change: `outside_label` is ALREADY on
    tool_bridge._DECISION_META_KEYS (REQ-7), so it survives to the ledger.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

# The flag. Default OFF == byte-identical behaviour to commit 0bdd1ad1.
ENV_FLAG = "IRIS_ORACLE_REVIEW_OUTCOME"
CONSUMER = "review_verdict"

# The loop's three settled outcomes. `verified_label` is one of exactly these
# (agent_kernel._der_score_step_outcome returns early on anything else), so
# anything outside the set is NOT stamped - an unrecognised value must leave
# the row on its parity reference rather than invent a label.
VERIFIED_LABELS = ("VERIFIED", "UNVERIFIED", "FAILED")

# How a settled outcome reads against the three verdict NAMES. This is the
# whole point of the module, so it is stated rather than computed:
#
#   VERIFIED   -> the step did its job. `pass` was RIGHT; `refine` (needs
#                 another pass) and `veto` (refuse to run) were both WRONG -
#                 too harsh against a step that settled fine.
#   FAILED     -> the step did not do its job. `pass` and `refine` were WRONG
#                 (refine lets a bad step continue); `veto` was RIGHT.
#   UNVERIFIED -> neither confirmed nor refuted. There is NO ground truth here,
#                 so no label is emitted and the row stays on parity. Stamping
#                 a guess would be the exact phantom-agreement failure the
#                 review row already guards against for parse failures.
#
# MEASURED CONSEQUENCE of an earlier incomplete map (VERIFIED carried only
# `pass`): `refine` is the MOST COMMON verdict (2204 of 2881 live rows), so
# nearly every stamped row fell through unstamped and the label never landed.
GROUND_TRUTH = {
    "VERIFIED": {"pass": True, "refine": False, "veto": False},
    "FAILED": {"pass": False, "refine": False, "veto": True},
}

_LOCK = threading.Lock()
# Bounded: a step that never settles must not leak. Drop-oldest, and the drop
# is COUNTED (repo standard: never silently lose a measurement).
_PENDING: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_CAP = 256
_DROPPED = 0
_WRITING = False

# Outcomes whose STEP ALREADY SETTLED before this module was handed the row.
#
# WHY THIS EXISTS (measured live 2026-10-16: "flushed unsettled review rows = 5"
# in one coding run). The review row is not built here on the turn thread: it is
# built on the `oracle_shadow` lane (der_loop._shadow_review_verdict submits
# `_job`, and `_job` calls this module's sink from a worker thread), while
# `stamp` runs on the turn thread when the step settles. The two RACE, and the
# settle can win. When it did, `defer` held a row whose step could never settle
# again: it sat in `_PENDING`, `sweep` flushed it at turn grade on PARITY, and
# the outcome label was lost with no marker on the row. This map lets that late
# row be stamped ON ARRIVAL instead.
#
# Bounded twice over: drop-oldest at `_SETTLED_CAP`, and an entry is CONSUMED by
# `defer` (a pop), so an ordinary row leaves nothing behind. A leftover entry is
# reachable only by a later row carrying the SAME step_id, and `stamp` records
# the FIRST settle for an id, never a later one - and a step_id is unique per
# step in the loop.
_SETTLED: "OrderedDict[str, str]" = OrderedDict()
_SETTLED_CAP = 256
_SETTLED_AHEAD = 0   # rows recovered by the reverse path (counted, not silent)
_SWEPT = 0           # rows flushed on parity because their step never settled


def enabled() -> bool:
    """True when the owner turned the outcome label on. Reads the env every
    call so the flag can be flipped without a restart."""
    return os.environ.get(ENV_FLAG, "").strip() not in ("", "0", "false", "False")


def stats() -> Dict[str, int]:
    """Counters for the report/log. Never raises.

    `recovered_after_settle` and `flushed_parity` are the two halves of the
    ROW-LOSS question: how many rows the reverse path saved, and how many were
    still flushed on parity because their step never settled. Both are visible
    so a loss is measured rather than silent.
    """
    with _LOCK:
        return {
            "pending": len(_PENDING),
            "dropped_overflow": _DROPPED,
            "recovered_after_settle": _SETTLED_AHEAD,
            "flushed_parity": _SWEPT,
        }


def _verdict_name(row: Dict[str, Any]) -> Optional[str]:
    """The verdict NAME this row is about, from either reference key.

    `brain_choice` is what the ledger passes through and the report reads;
    `brain_verdict` is kept for the caller's log and is not whitelisted.
    """
    for key in ("chosen", "brain_choice", "brain_verdict"):
        v = row.get(key)
        if v is not None:
            return str(v)
    return None


def _apply_outcome(row: Dict[str, Any], label: str) -> None:
    """Attach the settled outcome to the row, when the map has an answer.

    The ONE place the label lands, shared by the normal path (`stamp`) and the
    late path (`defer` winning the race). UNVERIFIED - or a verdict name we
    cannot read - leaves the row UNSTAMPED: no ground truth exists, so it keeps
    its parity reference. Dropping it would lose evidence; guessing would be the
    phantom agreement the review row already guards against for parse failures.
    """
    truth = GROUND_TRUTH.get(label) or {}
    verdict = _verdict_name(row)
    correct = truth.get(verdict) if verdict is not None else None
    if correct is None:
        return
    # REQ-7: an outside label takes precedence over the incumbent reference.
    # `label_source` says which curve the row is built on, so the report keeps
    # parity and outcome SEPARATE instead of blending.
    row["outside_label"] = bool(correct)
    row["label_source"] = "outcome"


def _noop_write(_row) -> None:
    """Sink for `register()` (in-memory only). The row is already in the ledger
    by the time `register` is used; `defer` is the path that also WRITES."""


class _Emitting:
    """Re-entrancy guard: while a held row is being handed back to the writer,
    `defer` must not hold it again."""

    def __enter__(self):
        global _WRITING
        _WRITING = True
        return self

    def __exit__(self, *exc):
        global _WRITING
        _WRITING = False
        return False


def defer(row: Optional[Dict[str, Any]], write) -> bool:
    """HOLD a review row instead of writing it now. Returns True when the caller
    must NOT write (the row is held and ``stamp`` writes it after the step
    settles).

    Why deferral rather than register-then-write: the single ledger writer does
    ``meta = dict(row)`` - a COPY - so a stamp applied after that write can never
    reach the ledger. Measured live with the write left in place: 0 rows carried
    an outcome label regardless of what the stamp did.

    Returns False (caller writes exactly as before) when the flag is off, the row
    is not a review row, or it has no join key - and, critically, when this is
    the RE-ENTRANT call from ``stamp``/``sweep`` handing the row back to the
    same writer. Without that guard the flush re-defers the row instead of
    writing it, so the measurement is silently held forever (measured live:
    263 review_verdict decisions in the last 2000 rows and the stored total
    never moved).

    Never raises.
    """
    if _WRITING:
        return False  # re-entrant flush from stamp/sweep: write it for real
    if not enabled() or not row or not isinstance(row, dict):
        return False
    if str(row.get("consumer_id") or "") != CONSUMER:
        return False
    sid = str(row.get("step_id") or "").strip()
    if not sid:
        return False  # no join key -> write it now on parity, as before
    global _SETTLED_AHEAD
    with _LOCK:
        settled = _SETTLED.pop(sid, None)
        if settled is None:
            _PENDING[sid] = {"row": row, "write": write}
            _PENDING.move_to_end(sid)
            while len(_PENDING) > _CAP:
                _PENDING.popitem(last=False)
                globals()["_DROPPED"] += 1
            return True
        _SETTLED_AHEAD += 1
    # THE RACE, LOST: the step settled BEFORE this row was built. The review row
    # is built on lane("oracle_shadow") (see _shadow_review_verdict), but
    # `stamp` runs on the turn thread at settle, so the settle can arrive first.
    # Holding the row now would strand it - its step can never settle again -
    # and `sweep` would flush it on PARITY, losing the label with no marker.
    # Stamp it here and write it now.
    _apply_outcome(row, settled)
    try:
        with _Emitting():
            write(row)
    except Exception:  # noqa: BLE001 — a label never blocks a settle
        pass
    return True  # already written: the caller must NOT write again


def register(row: Optional[Dict[str, Any]], step_id: Optional[str] = None) -> Optional[str]:
    """Hold a review row until its step settles, WITHOUT a writer.

    Kept for the in-memory case only (no ledger write). `defer` is the real
    entry point when the caller has a writer. Returns the step_id held, or None
    when the flag is off, the row is not a review row, or it carries no step
    scope. Never raises.

    ``step_id`` is passed explicitly because the review site's scope contextvar
    binds only turn_id (measured live: 2877 of 2877 review_verdict rows carried
    an EMPTY step_id, so nothing could ever join).
    """
    if not enabled() or not row or not isinstance(row, dict):
        return None
    if str(row.get("consumer_id") or "") != CONSUMER:
        return None
    sid = str(row.get("step_id") or step_id or "").strip()
    if not sid:
        return None  # no join key -> parity is the only reference we can offer
    # The row may carry an EMPTY step_id (the review site's scope binds
    # turn_id only), so this must overwrite a blank, not just fill a missing
    # key - `setdefault` would leave "" in place and the ledger row would
    # still have no join key.
    row["step_id"] = sid
    with _LOCK:
        _PENDING[sid] = {"row": row, "write": _noop_write}
        _PENDING.move_to_end(sid)
        while len(_PENDING) > _CAP:
            _PENDING.popitem(last=False)
            globals()["_DROPPED"] += 1
    return sid


def stamp(step_id: Optional[str], verified_label: Optional[str]) -> int:
    """Attach the outcome to the held row and WRITE it. Returns 1 when a row was
    emitted.

    Idempotent per step: a step that settles twice does not double-write, and an
    UNVERIFIED step emits the row UNSTAMPED (parity reference preserved) rather
    than dropping a real measurement.

    When NO row is held yet the outcome is not discarded: the row is built on the
    shadow lane and may still be in flight, so the outcome is remembered for
    `defer` (see `_SETTLED`). Never raises."""
    if not enabled() or not step_id:
        return 0
    label = str(verified_label or "").strip().upper()
    if label not in VERIFIED_LABELS:
        return 0
    sid = str(step_id)
    with _LOCK:
        entry = _PENDING.pop(sid, None)
        if entry is None:
            # The row has not been held yet (the oracle_shadow lane has not
            # finished building it). Remember the outcome so `defer` stamps it on
            # arrival, instead of `sweep` flushing it on parity. FIRST settle wins
            # for an id, so a repeat settle cannot overwrite the real one.
            if sid not in _SETTLED:
                _SETTLED[sid] = label
                _SETTLED.move_to_end(sid)
                while len(_SETTLED) > _SETTLED_CAP:
                    _SETTLED.popitem(last=False)
            return 0
    row = entry["row"]
    _apply_outcome(row, label)
    # UNVERIFIED (or an unknown verdict) emits the row UNSTAMPED: it is still a
    # real measurement on its parity reference. Dropping it would lose evidence.
    try:
        with _Emitting():
            entry["write"](row)
    except Exception:  # noqa: BLE001 — a label never blocks a settle
        pass
    return 1


def sweep() -> int:
    """Flush rows whose step will never settle (turn ended early, exception).
    Returns the count emitted; those rows keep their parity reference. Never
    raises.

    This is the loss path: after the reverse path in `defer`, every row counted
    here is one whose outcome label did NOT land. The count is kept in `stats()`
    so the loss rate is measurable, not inferred."""
    global _SWEPT
    if not enabled():
        return 0
    with _LOCK:
        entries = list(_PENDING.values())
        _PENDING.clear()
        _SWEPT += len(entries)
    for ent in entries:
        try:
            with _Emitting():
                ent["write"](ent["row"])
        except Exception:  # noqa: BLE001
            pass
    return len(entries)


def reset() -> None:
    """Test seam."""
    global _DROPPED, _SETTLED_AHEAD, _SWEPT
    with _LOCK:
        _PENDING.clear()
        _SETTLED.clear()
        _DROPPED = 0
        _SETTLED_AHEAD = 0
        _SWEPT = 0
