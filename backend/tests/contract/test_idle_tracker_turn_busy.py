"""A user turn in flight is never "idle" (2026-10-01).

Measured: eval c01 reply 351 s vs the 145 s standard. The whisper warm-up
(fixed +90 s after boot) fired inside the turn; its HDD import of
faster_whisper -> transformers held the turn's first pytest for 220 s. The
IdleTracker was touched only when a message ARRIVED, so a turn that ran for
minutes without new input read as idle to every background worker.

Pinned:
  1. busy() holds idle_seconds() at 0 for the whole turn;
  2. every turn (voice, chat, developer orchestrator) runs inside busy() -
     the decorator on AgentKernel.process_text_message, the one shared entry;
  3. the whisper warm-up waits on the tracker, not on a fixed sleep alone.
"""
from __future__ import annotations

import ast
import time
from pathlib import Path

from backend.core.idle_tracker import IdleTracker

_BACKEND = Path(__file__).resolve().parents[2]


def test_busy_turn_is_never_idle():
    t = IdleTracker(idle_threshold_s=0.05)
    with t.busy():
        time.sleep(0.12)
        assert t.idle_seconds() == 0.0
        assert not t.is_idle()
    assert t.idle_seconds() < 0.05, "the idle clock restarts when the turn ends"
    time.sleep(0.07)
    assert t.is_idle()


def test_busy_releases_on_error():
    t = IdleTracker(idle_threshold_s=0.0)
    try:
        with t.busy():
            raise RuntimeError("turn failed")
    except RuntimeError:
        pass
    assert t.is_idle(), "a failed turn must not leave the tracker busy forever"


def test_every_turn_entry_is_busy():
    """Turns enter through voice, chat AND the developer orchestrator; the one
    place all three pass is AgentKernel.process_text_message."""
    from backend.agent.agent_kernel import AgentKernel
    from backend.core import idle_tracker

    seen = {}
    t = IdleTracker(idle_threshold_s=0.0)
    orig = idle_tracker._singleton
    idle_tracker._singleton = t
    try:
        k = AgentKernel.__new__(AgentKernel)

        class _Stop(Exception):
            pass

        def _stop():
            seen["idle"] = t.idle_seconds()
            seen["in_flight"] = t._in_flight
            raise _Stop

        k.clear_turn_trust_flag = _stop
        try:
            k.process_text_message("hi", session_id="s", conversation_id="c")
        except _Stop:
            pass
    finally:
        idle_tracker._singleton = orig
    assert seen.get("in_flight") == 1, "process_text_message ran outside busy()"
    assert t._in_flight == 0, "busy() must release when the turn raises"


def test_boot_prewarm_waits_for_idle():
    # RETARGETED 2026-10-05 (owner decision: Whisper is the fallback only and
    # gets no warm-up). The boot job that replaced it - the Parakeet file
    # pre-read - must keep the same rule: no disk work while a turn runs.
    src = (_BACKEND / "main.py").read_text(encoding="utf-8", errors="replace")
    assert "_delayed_whisper_warm_up" not in src
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_delayed_parakeet_prewarm"
    )
    body = ast.unparse(fn)
    assert "is_idle(" in body, "the warm-up must wait for no turn in flight"
