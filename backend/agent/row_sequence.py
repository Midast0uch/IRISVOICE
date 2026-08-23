"""Backend-owned monotonic ordering key for task-card rows.

specs/der-ground-truth/ REQ-17 (T28/T29). The ONE authority for render order.

THE PROBLEM THIS REPLACES
-------------------------
Four numbering authorities disagreed, and none of them owned render order:

* the planner LLM self-reported ``step_number`` in its plan JSON
  (``agent_kernel._parse_plan``), with a positional fallback ``len(steps)+1`` --
  an untrusted source for anything, let alone ordering;
* grafts took ``len(completed_items)``, which can COLLIDE with a
  planner-assigned number (measured: T27 found exactly this collision in the
  captured graft trace, rows ``r1`` and ``r1_s1`` both on key 1);
* progressive phase nodes carried NO key at all, so every one of them sorted
  to the end of the card forever, whenever it actually happened;
* the frontend then derived position three separate ways.

T27 measured the result: **18 emitter-contract violations across all three
captured traces**, every ``task:start`` row unkeyed, in crawl and non-crawl
tasks alike.

THE RULE
--------
``seq`` is allocated **per row identity, memoized** -- not per emit.

That distinction is the whole design. Allocation order is emit order, so a row
created between planner steps 2 and 3 sorts between them (REQ-17 AC4:
chronological interleaving). But because it is memoized by row id, re-emitting a
row -- which ``task:start`` does on every revision, graft, and split, and which
a revisited crawl phase does too -- returns the SAME key. A revision therefore
cannot renumber rows that already exist, and a card's order is stable for its
whole life.

``step_number`` is deliberately left alone. The planner's numbering is a
meaningful DISPLAY concern ("step 2 of the plan") and REQ-17 AC5 keeps it, it
simply stops being the render-order authority.

CONSTRAINTS
-----------
* Bounded in both dimensions -- conversations tracked and rows per conversation
  -- so a long-lived process cannot grow this without limit.
* Never raises. An allocator that could break an emit would be worse than the
  disorder it fixes; on any internal failure it degrades to a monotonic value
  that is still unique, just not memoized.
* ``threading`` only. No heavy imports (AGENTS.md quality check).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Dict, Optional

__all__ = ["seq_for", "peek", "reset_conversation", "reset_all",
           "MAX_CONVERSATIONS", "MAX_ROWS_PER_CONVERSATION"]

# A conversation is a card's lifetime; a few hundred rows is already a very long
# run. These are backstops against unbounded growth, not budgets.
MAX_CONVERSATIONS = 64
MAX_ROWS_PER_CONVERSATION = 2048

_LOCK = threading.Lock()
# conversation_id -> {row_id: seq}; OrderedDict so the oldest conversation is
# the one evicted when the cap is reached.
_ROWS: "OrderedDict[str, Dict[str, int]]" = OrderedDict()
_NEXT: Dict[str, int] = {}
# Degraded-path counter: allocations that could not be memoized (cap reached).
# Surfaced through write_counters so a silent cap is impossible.
_DEGRADED = "row_sequence.unmemoized_allocation"


def _bump_degraded() -> None:
    try:
        from backend.agent import write_counters as _wc
        _wc.bump(_DEGRADED)
    except Exception:
        pass


def seq_for(conversation_id: Optional[str], row_id: Optional[str]) -> int:
    """Return the stable ordering key for ``row_id`` within ``conversation_id``.

    First call for a row allocates the next value; every later call for the SAME
    row returns what was allocated. Distinct rows never share a key (REQ-17 AC3).

    Returns 0 when the inputs are unusable -- callers treat 0 as "no key" and the
    emitter contract (rule E1) will flag it, which is the intended behaviour:
    a missing key must be visible, never silently invented.
    """
    try:
        if not conversation_id or not row_id:
            return 0
        cid = str(conversation_id)
        rid = str(row_id)
        with _LOCK:
            rows = _ROWS.get(cid)
            if rows is None:
                if len(_ROWS) >= MAX_CONVERSATIONS:
                    old, _ = _ROWS.popitem(last=False)
                    _NEXT.pop(old, None)
                rows = {}
                _ROWS[cid] = rows
                _NEXT[cid] = 0
            else:
                _ROWS.move_to_end(cid)

            existing = rows.get(rid)
            if existing is not None:
                return existing

            nxt = _NEXT.get(cid, 0) + 1
            _NEXT[cid] = nxt
            if len(rows) < MAX_ROWS_PER_CONVERSATION:
                rows[rid] = nxt
            else:
                # Past the cap we still hand back a UNIQUE, monotonic value --
                # ordering survives; only stability across re-emits is lost.
                # Counted, never silent.
                _bump_degraded()
            return nxt
    except Exception:  # pragma: no cover - must never break an emit
        _bump_degraded()
        return 0


def peek(conversation_id: Optional[str], row_id: Optional[str]) -> int:
    """Key already allocated to ``row_id``, or 0. Allocates nothing."""
    try:
        if not conversation_id or not row_id:
            return 0
        with _LOCK:
            return _ROWS.get(str(conversation_id), {}).get(str(row_id), 0)
    except Exception:
        return 0


def reset_conversation(conversation_id: Optional[str]) -> None:
    """Forget one conversation's rows (new card / cleared thread)."""
    try:
        if not conversation_id:
            return
        with _LOCK:
            _ROWS.pop(str(conversation_id), None)
            _NEXT.pop(str(conversation_id), None)
    except Exception:
        pass


def reset_all() -> None:
    """Clear every conversation. For tests."""
    with _LOCK:
        _ROWS.clear()
        _NEXT.clear()
