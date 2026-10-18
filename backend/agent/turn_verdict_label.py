"""Hold shadow rows that await a turn verdict from OUTSIDE the process.

WHY (oracle.md 7.5, depth_met, 2026-10-17, owner: "work on depth_met"):
depth_met's incumbent reference is the loop grade - a deterministic rule over
inputs the model never sees, so the Oracle cannot beat it (measured oof AUROC
0.40: its confidence ranks errors BACKWARDS). The honest label is whether the
TURN was actually right: the eval verdict (hidden tests) for eval turns, a
user correction or a re-ask for live turns. That verdict exists only OUTSIDE
the process, AFTER the turn ends - so the row must be HELD from its consult
until the verdict is reported.

THE JOIN: rows are held keyed by ``turn_id``; ``report_verdict(turn_id,
passed)`` stamps them - ``outside_label`` = the verdict, ``label_source`` =
"outcome" - and writes them through the SAME writer that would have written
them immediately. The noul consumers here carry ``chosen`` as a BOOL, so the
report's ``decision_label`` scores ``bool(chosen) == bool(verdict)``: "the
engine said met and the turn was right" / "the engine said met and the turn
was wrong". Rows whose verdict never arrives (a live turn, a crashed harness)
are never lost: the map is bounded drop-oldest and the drop is COUNTED, and
``sweep()`` flushes everything unlabelled on their parity reference.

SAFETY: nothing here can block a consult or a turn - every entry point is
try/except-clean and the hold lives off the answer path (the shadow lane).
A verdict for an unknown turn is a no-op (counted by stats, never an error).

DELETION CONTRACT (keep this true): this module, the depth_met interception
in surface_shadow._submit_shadow, the router in backend/api/eval_verdict.py,
its include_router line in backend/main.py, the verdict POST in
evals/run_evals.py, and the contract test file. Nothing else.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

_PENDING: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
_CAP = 256          # turns; drop-oldest, counted
_DROPPED = 0
_LOCK = threading.Lock()


def defer(row: Optional[Dict[str, Any]], write: Callable[[dict], None]) -> bool:
    """HOLD one shadow row until its turn's verdict is reported. Returns True
    when the caller must NOT write it (the verdict path writes it later).

    Returns False (caller writes exactly as before) when the row carries no
    turn_id - no join key means parity is the only reference available, and
    holding it would strand it. Never raises.
    """
    global _DROPPED
    try:
        if not row or not isinstance(row, dict):
            return False
        tid = str(row.get("turn_id") or "")
        if not tid:
            return False
        with _LOCK:
            _PENDING.setdefault(tid, []).append({"row": row, "write": write})
            _PENDING.move_to_end(tid)
            while len(_PENDING) > _CAP:
                _, dropped = _PENDING.popitem(last=False)
                _DROPPED += len(dropped)
        return True
    except Exception:  # noqa: BLE001 — a label never blocks a consult
        return False


def report_verdict(turn_id: str, passed: bool) -> int:
    """Stamp this turn's held rows with the verdict and write them. Returns
    the count labelled. A verdict for an unknown turn is a no-op. Never
    raises."""
    tid = str(turn_id or "")
    if not tid:
        return 0
    try:
        with _LOCK:
            entries = _PENDING.pop(tid, None) or []
    except Exception:  # noqa: BLE001
        entries = []
    labelled = 0
    for ent in entries:
        row = ent.get("row") or {}
        try:
            row["outside_label"] = bool(passed)
            row["label_source"] = "outcome"
            labelled += 1
        except Exception:  # noqa: BLE001 — a bad row never blocks the rest
            continue
        try:
            ent["write"](row)
        except Exception:  # noqa: BLE001 — a writer failure never propagates
            pass
    return labelled


def sweep() -> int:
    """Flush every held row UNLABELLED (parity reference preserved). For
    shutdown and tests; the bound handles the leaks. Never raises."""
    try:
        with _LOCK:
            entries = [e for lst in _PENDING.values() for e in lst]
            _PENDING.clear()
    except Exception:  # noqa: BLE001
        return 0
    for ent in entries:
        try:
            ent["write"](ent["row"])
        except Exception:  # noqa: BLE001
            pass
    return len(entries)


def stats() -> Dict[str, int]:
    """Counters for the report/log. Never raises."""
    try:
        with _LOCK:
            return {
                "turns_pending": len(_PENDING),
                "rows_pending": sum(len(v) for v in _PENDING.values()),
                "dropped_overflow": _DROPPED,
            }
    except Exception:  # noqa: BLE001
        return {"turns_pending": 0, "rows_pending": 0, "dropped_overflow": 0}


def reset() -> None:
    """Test seam."""
    global _DROPPED
    with _LOCK:
        _PENDING.clear()
        _DROPPED = 0
