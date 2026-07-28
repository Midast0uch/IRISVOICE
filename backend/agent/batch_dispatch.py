"""Bounded Sub-Loop batching for the Caducean Phase Manager (Wave 4 / REQ-15).

Groups independent Sub-Loop children sharing a **join_point** (the parent step id)
into a single batched LLM call when their oscillator phase windows are within
``BATCH_WINDOW_RAD``.  The batch is capped at ``BATCH_MAX_CHILDREN`` children
and never held longer than ``BATCH_MAX_HOLD_S``.

Children arrive with ``is_subloop=True``, ``tool=None``, a per-child
``expected_output``, and id ``{parent}_s{i}`` — the id prefix IS the natural
join point (REQ-18 AC1).

Contract locks: never calls ``coupled_registry`` or ``iris_ffi``.
``abandon(join_point)`` is called on soft-cancel so we never batch across turns
(CT-8 / T4.2 CONTRACT).
"""
from __future__ import annotations

import logging
import math
import re as _re
import threading
import time as _perf_t
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.phase_manager import get_registry

logger = logging.getLogger(__name__)


# ── Tunables (env-overridable) ──────────────────────────────────────────────
def _env_float(name: str, default: float) -> float:
    try:
        _v = __import__("os").environ.get(name)
        return float(_v) if _v is not None else default
    except (TypeError, ValueError):
        return default


BATCH_WINDOW_RAD = _env_float("IRIS_BATCH_WINDOW_RAD", 0.35)
BATCH_MAX_HOLD_S = _env_float("IRIS_BATCH_MAX_HOLD_S", 0.25)
BATCH_MAX_CHILDREN = 3


@dataclass
class BatchGroup:
    """A group of Sub-Loop children pending batched dispatch.

    Children within a group share the same ``join_point``, are all
    ``independent``, and have oscillator phases within ``BATCH_WINDOW_RAD``.
    """

    join_point: str
    quota_id: str
    children: List[Any] = field(default_factory=list)
    opened_at: float = field(default_factory=_perf_t.time)
    batched_prompt: str = ""  # populated on flush


class SubLoopBatcher:
    """Holds Sub-Loop children until they can be dispatched as a batch or must
    time out and be released individually.

    Thread-safe (single ``threading.Lock``).
    """

    def __init__(self) -> None:
        self._groups: Dict[str, BatchGroup] = {}
        self._lock = threading.Lock()

    def offer(self, child: Any, quota_id: Optional[str] = None) -> Optional[BatchGroup]:
        """Offer a child for potential batching.

        **T6.8 gates (F10 / REQ-18):**
        1. Rejects children that are not ``independent`` (AC1) — they cannot be
           safely batched with siblings.
        2. Groups only when the quota's oscillator phase is within
           ``BATCH_WINDOW_RAD`` of the firing point (π) (AC2).
        3. ``BATCH_MAX_HOLD_S`` is enforced by ``flush_expired()`` (AC3).

        Returns:
            * ``BatchGroup`` — the group is ready to dispatch (enough children,
              window aligned, or max hold time reached).
            * ``None`` — the child was logged into a pending group or dispatched
              individually (non-Sub-Loop / not independent / phase outside window).
        """
        if not getattr(child, "is_subloop", False):
            return None  # not a Sub-Loop child → dispatch individually

        # T6.8 (AC1): reject non-independent children
        if not getattr(child, "independent", False):
            return None  # not safe to batch with siblings → dispatch individually

        _join = self._join_point(child)
        if _join is None:
            return None

        # T6.8 (AC2): check oscillator phase window — only group when the
        # quota's oscillator is within BATCH_WINDOW_RAD of the firing point (π).
        # If no oscillator is registered for this quota/call-class yet we cannot
        # evaluate the window, so we do NOT block batching on it (fail-open,
        # consistent with the gate's overall fail-open contract). Blocking on an
        # unknown phase would disable sub-loop batching entirely, since children
        # are offered before their request registers an oscillator.
        _qid = quota_id or getattr(child, "quota_id", "")
        if _qid:
            _osc_id = f"{_qid}:{getattr(child, 'call_class', 'SUBLOOP')}"
            _osc = get_registry().get(_osc_id)
            if _osc is not None:
                _phase = _osc.theta
                _dist_to_pi = abs(
                    ((_phase - math.pi + math.pi) % (2 * math.pi)) - math.pi
                )
                if _dist_to_pi > BATCH_WINDOW_RAD:
                    return None  # oscillator not near firing point → wait

        with self._lock:
            _group = self._groups.get(_join)
            if _group is None:
                _group = BatchGroup(join_point=_join, quota_id=_qid)
                self._groups[_join] = _group

            _group.children.append(child)

            # Full → immediate flush
            if len(_group.children) >= BATCH_MAX_CHILDREN:
                self._groups.pop(_join, None)
                self._compose_batch(_group)
                return _group

            return None  # awaiting more children

    def flush(self, join_point: str) -> Optional[BatchGroup]:
        """Force-flush a group (max hold or DER cycle end)."""
        with self._lock:
            _group = self._groups.pop(join_point, None)
        if _group is not None:
            self._compose_batch(_group)
        return _group

    def abandon(self, join_point: str) -> None:
        """Drop a group (soft-cancel / turn boundary)."""
        with self._lock:
            self._groups.pop(join_point, None)

    def flush_expired(self) -> List[BatchGroup]:
        """Flush all groups whose hold time has exceeded ``BATCH_MAX_HOLD_S``."""
        _now = _perf_t.time()
        _expired: List[BatchGroup] = []
        with self._lock:
            for _jp, _g in list(self._groups.items()):
                if _now - _g.opened_at >= BATCH_MAX_HOLD_S:
                    _expired.append(_g)
                    del self._groups[_jp]
        for _g in _expired:
            self._compose_batch(_g)
        return _expired

    # ── internals ──────────────────────────────────────────────────────────
    def _join_point(self, child: Any) -> Optional[str]:
        """Derive the join point from a Sub-Loop child's step id."""
        _sid = getattr(child, "step_id", "")
        if not _sid:
            _sid = str(getattr(child, "step_number", ""))
        # step_id format: ``{parent}_s{i}``
        if "_s" in _sid:
            return _sid.rsplit("_s", 1)[0]
        return _sid or None

    def _compose_batch(self, group: BatchGroup) -> None:
        """Build the batched prompt (T4.3 placeholder — fully populated in T4.3).

        Concatenates each child's description/expected_output into a single
        prompt structure so a single LLM call can answer all children at once.
        """
        _parts: List[str] = []
        for _i, _c in enumerate(group.children):
            _desc = getattr(_c, "description", "") or getattr(_c, "expected_output", "")
            _sid = getattr(_c, "step_id", f"sub_{_i}")
            _parts.append(f"<subloop id=\"{_sid}\">\n{_desc}\n</subloop>")
        group.batched_prompt = "\n".join(_parts)

    def parse_batched_response(
        self, group: BatchGroup, response: str
    ) -> Dict[str, str]:
        """Parse a batched LLM response into per-child results (T4.4).

        Primary: extract content from ``<subloop id=\"...\">...`` tags.
        Fallback: numbered extraction (``#1``, ``#2``, ...) ordered by child
        position, if tag-based parsing returns empty results.
        """
        _results: Dict[str, str] = {}
        for _c in group.children:
            _sid = getattr(_c, "step_id", "")
            if not _sid:
                continue
            _m = _re.search(
                rf"<subloop id=\"{_sid}\">(.*?)</subloop>",
                response,
                _re.DOTALL,
            )
            _results[_sid] = _m.group(1).strip() if _m else ""

        # Fallback: if all results are empty, try numbered extraction
        if not any(_results.values()):
            for _i, _c in enumerate(group.children):
                _sid = getattr(_c, "step_id", f"sub_{_i}")
                _m = _re.search(rf"#\s*{_i+1}\s*(.*?)(?=\n#\s*|\Z)", response, _re.DOTALL)
                _results[_sid] = _m.group(1).strip() if _m else response.strip()
        return _results

    def reset_for_testing(self) -> None:
        """Drop all pending groups (test isolation)."""
        with self._lock:
            self._groups.clear()


# ── Module-level dispatch helper (T4.5) ───────────────────────────────────
def dispatch_batch(
    group: BatchGroup,
    router: Any,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.5,
) -> Dict[str, str]:
    """Dispatch a ``BatchGroup`` as a single LLM call and return per-child
    results ``{step_id: result_text}``.

    Appends the batched prompt to *messages* as a user message, calls
    ``router.generate()``, and parses the response via
    ``SubLoopBatcher.parse_batched_response()``.

    The caller (DER loop) is responsible for queueing each child's result
    individually so the parent step consumes them normally.
    """
    _batcher = SubLoopBatcher()
    _batched_msg = messages + [
        {
            "role": "user",
            "content": (
                "Answer each of the following sub-queries in sequence. "
                "Use `<subloop id=\"...\">...</subloop>` tags around each answer.\n\n"
                f"{group.batched_prompt}"
            ),
        }
    ]
    _text, _think, _tools = router.generate(
        model, _batched_msg, [], max_tokens=max_tokens,
        temperature=temperature, chunk_callback=None, reasoning_callback=None,
    )
    return _batcher.parse_batched_response(group, _text)


# ── Singleton batcher ──────────────────────────────────────────────────────
_singleton: Optional[SubLoopBatcher] = None
_singleton_lock = threading.Lock()


def get_batcher() -> SubLoopBatcher:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = SubLoopBatcher()
        return _singleton


def reset_batcher_for_testing() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


def process_subloop_child(
    child: Any,
    router: Any,
    model: str,
    base_messages: List[Dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.5,
) -> Optional[Dict[str, str]]:
    """Route a Sub-Loop child through the batcher (T4.5 integration point).

    Called by the DER loop when it encounters a child with ``is_subloop=True``.

    Returns:
        * ``{step_id: result_text}`` — when a batch is ready to dispatch.
        * ``None`` — child was added to a pending batch (awaiting more children
          or timeout).

    The caller (DER loop) must:
    1. If ``None`` is returned, continue the step loop (child is pending).
    2. If results are returned, queue each child's result individually so the
       parent step consumes them normally.
    3. Call ``get_batcher().flush_expired()`` periodically (e.g., every phase
       iteration) to release timed-out groups.
    """
    _batcher = get_batcher()
    _group = _batcher.offer(child)
    if _group is None:
        return None  # child is in a pending batch
    # Batch is ready → dispatch
    return dispatch_batch(
        _group, router, model, base_messages, max_tokens, temperature,
    )
