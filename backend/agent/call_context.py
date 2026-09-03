"""Call-class context for the Caducean Phase Manager (REQ-14).

Provides a ``ContextVar``-scoped call classification so the phase gate can
distinguish high-priority user-facing calls (SPEAK / USER_TURN) from background
processing (REASON / TOOL / GRAFT / REVIEW). The ``BACKGROUND`` default is load-
bearing: an unclassified call is **gated**, never accidentally privileged
(REQ-14 AC3).

Mirrors the ``ContextVar`` precedent at
``backend/monitoring/session_correlation.py:18-21``.
"""

from __future__ import annotations

import enum
import functools
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Tuple


class CallClass(enum.Enum):
    """Priority classification for an LLM call.

    Higher-priority classes appear earlier in ``PRIORITY_CLASSES`` and skip the
    phase gate wait (REQ-13 AC2 / REQ-14 AC2).

    * ``SPEAK`` — user-facing TTS output (critical: user hears silence while waiting).
    * ``USER_TURN`` — live user interaction (turn-start inference).
    * ``TOOL`` — tool result processing (derived from a live turn).
    * ``GRAFT`` — recovery-plan generation (critical but not user-facing).
    * ``REVIEW`` — reviewer / verifier call (instrumental to loop correctness).
    * ``REASON`` — default for non-tool LLM inference (gated).
    * ``SUBLOOP`` — bounded Sub-Loop child (distinct from top-level loop).
    * ``BACKGROUND`` — default for any call not explicitly classified (gated).
    """

    SPEAK = "speak"
    USER_TURN = "user_turn"
    TOOL = "tool"
    GRAFT = "graft"
    REVIEW = "review"
    REASON = "reason"
    SUBLOOP = "subloop"
    BACKGROUND = "background"


# Priority-class set (T6.4): ONLY USER_TURN and SPEAK are high-priority.
# GRAFT is recovery-plan generation fired after a step failure (including 429),
# so exempting it would create a 429->graft->429 amplification loop (F6).
# TOOL, REVIEW, REASON, SUBLOOP, BACKGROUND are gated.
PRIORITY_CLASSES: frozenset = frozenset(
    {CallClass.USER_TURN, CallClass.SPEAK}
)

# Full ranking (for ordered admission of non-priority calls).
_PRIORITY_RANKING: Tuple[CallClass, ...] = (
    CallClass.SPEAK,
    CallClass.USER_TURN,
    CallClass.GRAFT,
    CallClass.TOOL,
    CallClass.REVIEW,
    CallClass.REASON,
    CallClass.SUBLOOP,
    CallClass.BACKGROUND,
)


def priority_index(cls: CallClass) -> int:
    """Return the priority rank (0=highest) for *cls*."""
    try:
        return _PRIORITY_RANKING.index(cls)
    except ValueError:
        return len(_PRIORITY_RANKING)


def is_high_priority(cls: CallClass) -> bool:
    """True if *cls* is high-priority (USER_TURN or SPEAK).

    GRAFT is NOT high-priority (F6) — recovery-plan generation after a step
    failure must be gated like any other non-user call.
    """
    return cls in PRIORITY_CLASSES


# Thread-local / ContextVar-scoped call classification.
# Defaults to BACKGROUND so any call without an explicit class is gated.
_call_class_ctx: ContextVar[CallClass] = ContextVar(
    "phase_call_class", default=CallClass.BACKGROUND
)


def set_call_class(cls: CallClass):
    """Set the current context's call class. Returns a restore token.

    Must be called at the top of ``_execute_plan_der`` (T3.7) and around
    ``speak_tool`` output paths. The equivalent of
    ``session_correlation.py:set_session_id``.

    **Always prefer** :func:`call_class_scope` over a bare call. The returned
    token may be passed to :func:`reset_call_class` if you need manual control.

    Why restoring matters (REQ-22 AC8 / review finding N4): the DER loop runs in
    a **reused** thread-pool thread (``api/chat.py:199`` dispatches through
    ``run_in_executor``). A ``ContextVar`` set in a bare worker thread mutates
    that thread's top-level context and **survives the request**, so a turn that
    ends on ``USER_TURN`` would leave the next unit of work scheduled on that
    thread in the never-gated priority lane — defeating REQ-14 AC3's rule that an
    unclassified call is gated, never accidentally privileged.
    """
    return _call_class_ctx.set(cls)


def reset_call_class(token) -> None:
    """Restore the call class to what it was before ``set_call_class``.

    Never raises — a token from a different context is ignored, because failing
    to restore must not break a request.
    """
    try:
        _call_class_ctx.reset(token)
    except (ValueError, RuntimeError):  # token from another context
        pass


def restores_call_class(fn):
    """Decorator: restore the caller's call class when ``fn`` returns or raises.

    Use on turn entry points that call :func:`set_call_class` internally and have
    many return paths (e.g. ``AgentKernel.process_text_message``), where wrapping
    the body in ``try/finally`` would mean restructuring a large method.

    Solves REQ-22 AC8 / review finding N4 for every exit path at once: the worker
    thread's context is handed back exactly as it was found, so a completed turn
    cannot leave the next unit of work on that thread in the priority lane.
    """
    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        _token = _call_class_ctx.set(_call_class_ctx.get())
        try:
            return fn(*args, **kwargs)
        finally:
            reset_call_class(_token)

    return _wrapper


@contextmanager
def call_class_scope(cls: CallClass):
    """Set the call class for the duration of a block, then restore it.

    The preferred entry point — makes the REQ-22 AC8 restore automatic::

        with call_class_scope(CallClass.USER_TURN):
            ...                       # gate admits immediately
        # previous class restored, even if the block raised
    """
    _token = _call_class_ctx.set(cls)
    try:
        yield
    finally:
        reset_call_class(_token)


def call_class() -> CallClass:
    """Get the current context's call class (default ``BACKGROUND``).

    Returns ``BACKGROUND`` if the caller's context has not called
    ``set_call_class`` (REQ-14 AC3 — unclassified calls are gated).
    """
    return _call_class_ctx.get()
