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
#   VERIFIED   -> the step did its job -> `pass` was RIGHT.
#   FAILED     -> the step did not    -> `pass` was WRONG, and so was `refine`
#                 for anything that let it through; `veto` would have been
#                 RIGHT (it refuses to run).
#   UNVERIFIED -> neither confirmed nor refuted. There is NO ground truth here,
#                 so no label is emitted and the row stays on parity. Stamping
#                 a guess would be the exact phantom-agreement failure the
#                 review row already guards against for parse failures.
GROUND_TRUTH = {
    "VERIFIED": {"pass": True},
    "FAILED": {"pass": False, "refine": False, "veto": True},
}

_LOCK = threading.Lock()
# Bounded: a step that never settles must not leak. Drop-oldest, and the drop
# is COUNTED (repo standard: never silently lose a measurement).
_PENDING: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_CAP = 256
_DROPPED = 0


def enabled() -> bool:
    """True when the owner turned the outcome label on. Reads the env every
    call so the flag can be flipped without a restart."""
    return os.environ.get(ENV_FLAG, "").strip() not in ("", "0", "false", "False")


def stats() -> Dict[str, int]:
    """Counters for the report/log. Never raises."""
    with _LOCK:
        return {
            "pending": len(_PENDING),
            "dropped_overflow": _DROPPED,
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


def register(
    row: Optional[Dict[str, Any]],
    step_id: Optional[str] = None,
) -> Optional[str]:
    """Hold a review row until its step settles. Returns the step_id held, or
    None when the flag is off, the row is not a review row, or it carries no
    step scope. Never raises - a missing label must not break a review.

    ``step_id`` is passed explicitly because the review site's scope contextvar
    binds only turn_id (measured live: 2877 of 2877 review_verdict rows carried
    an EMPTY step_id, so nothing could ever join). The caller knows the item;
    the contextvar does not.
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
        _PENDING[sid] = row
        _PENDING.move_to_end(sid)
        while len(_PENDING) > _CAP:
            _PENDING.popitem(last=False)
            globals()["_DROPPED"] += 1
    return sid


def stamp(step_id: Optional[str], verified_label: Optional[str]) -> int:
    """Attach the outcome to the held row. Returns 1 when a row was stamped.

    Idempotent per step: a step that settles twice does not double-stamp, and a
    UNVERIFIED step stamps nothing so the row keeps its parity reference.
    Never raises."""
    if not enabled() or not step_id:
        return 0
    label = str(verified_label or "").strip().upper()
    if label not in VERIFIED_LABELS:
        return 0
    with _LOCK:
        row = _PENDING.pop(str(step_id), None)
    if not row:
        return 0
    verdict = _verdict_name(row)
    if verdict is None:
        return 0
    truth = GROUND_TRUTH.get(label)
    if label == "UNVERIFIED" or not truth:
        return 0
    correct = truth.get(verdict)
    if correct is None:
        return 0
    # REQ-7: an outside label takes precedence over the incumbent reference.
    # `label_source` says which curve the row is built on, so the report can
    # keep parity and outcome measurable SEPARATELY instead of blending them.
    row["outside_label"] = bool(correct)
    row["label_source"] = "outcome"
    return 1


def sweep(session_scoped_step_ids=None) -> int:
    """Drop rows whose step will never settle (a turn ended early). Returns the
    count dropped. Those rows were already written with parity, so nothing is
    lost - they simply never gain an outcome. Never raises."""
    if not enabled() or not session_scoped_step_ids:
        return 0
    gone = 0
    with _LOCK:
        for sid in list(_PENDING):
            if sid in session_scoped_step_ids:
                continue
            _PENDING.pop(sid, None)
            gone += 1
    return gone


def reset() -> None:
    """Test seam."""
    global _DROPPED
    with _LOCK:
        _PENDING.clear()
        _DROPPED = 0