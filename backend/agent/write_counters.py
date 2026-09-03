"""Named counters for swallowed write-path failures.

specs/der-ground-truth/ REQ-13 (silent-failure policy), used first by REQ-5/T1.

WHY THIS EXISTS
---------------
A census of ``backend/agent/`` + ``backend/memory/`` found **441 of 778 exception
handlers (57%) swallow at ``logger.debug`` or silently via ``pass``/``continue``**.
Each one is individually defensible — observability must never break the thing it
observes — but collectively they make the system unobservable, because **a write
that fails silently is indistinguishable from a write that was never attempted**.
Both leave an empty table and a clean log. That ambiguity is exactly what let five
memory substrates sit empty and unnoticed (pin_ef766b9223ed).

This module resolves the ambiguity without giving up the never-raise guarantee:
the handler still swallows, but it leaves a number behind.

DESIGN CONSTRAINTS
------------------
* **Cannot fail.** Incrementing is a dict update under a lock — no I/O, no
  serialization, no network. REQ-13's edge case ("a counter itself fails to
  increment") is answered structurally: there is nothing here to fail.
* **Never raises.** ``bump`` swallows even its own errors. A counter that could
  break a caller would be worse than the silence it replaces.
* **Bounded.** Distinct names are capped so a caller that accidentally bumps a
  per-item name (a URL, a step id) cannot grow this unboundedly.
* **No heavy imports.** ``threading`` only, so any module can import it without
  dragging in a dependency chain (AGENTS.md quality check: heavy imports lazy).

WHAT IT IS NOT
--------------
Not telemetry, not a metrics backend, not persisted. It is an in-process tally
that ``scripts/validate_store_invariants.py`` (REQ-6) reads to answer one
question: *did a write path fail quietly during this run?*
"""
from __future__ import annotations

import threading
from typing import Dict

__all__ = ["bump", "get", "snapshot", "reset", "total", "MAX_DISTINCT_NAMES"]

# A name is a STABLE call-site label ("edge_scoring.skipped_no_region"), never a
# per-item value. The cap is a backstop against that mistake, not a budget.
MAX_DISTINCT_NAMES = 512

_LOCK = threading.Lock()
_COUNTS: Dict[str, int] = {}
_OVERFLOW = "_counter_names_overflow"


def bump(name: str, n: int = 1) -> None:
    """Increment *name* by *n*. Never raises, never blocks meaningfully.

    Call this from an ``except`` block that swallows a WRITE, and from the
    guard that SKIPS one — a skip and a failure are different causes and
    deserve different names.
    """
    try:
        if not name:
            return
        with _LOCK:
            if name not in _COUNTS and len(_COUNTS) >= MAX_DISTINCT_NAMES:
                # Refuse the new name rather than growing without bound, and
                # record that a refusal happened so the cap is never silent —
                # a silent cap reads as full coverage when it is not.
                _COUNTS[_OVERFLOW] = _COUNTS.get(_OVERFLOW, 0) + 1
                return
            _COUNTS[name] = _COUNTS.get(name, 0) + int(n)
    except Exception:  # pragma: no cover - a counter must never break a caller
        pass


def get(name: str) -> int:
    """Current value of *name* (0 when never bumped)."""
    with _LOCK:
        return _COUNTS.get(name, 0)


def snapshot() -> Dict[str, int]:
    """Copy of every counter. Safe to read while other threads bump."""
    with _LOCK:
        return dict(_COUNTS)


def total() -> int:
    """Sum across every counter — the headline 'did anything fail quietly' number."""
    with _LOCK:
        return sum(_COUNTS.values())


def reset() -> None:
    """Clear all counters. For tests and for per-run reporting boundaries."""
    with _LOCK:
        _COUNTS.clear()
