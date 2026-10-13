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
  4. transport frames (pong, ping, heartbeat, frame acks) never reset the
     idle clock, but a user message does (2026-10-13);
  5. the distillation maintenance guard reads the same clock as should_run.
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


def test_keepalives_do_not_reset_the_idle_clock(monkeypatch):
    """Transport frames are not the user (measured 2026-10-13).

    With the app open and unused, a "pong" every 30 s (720 overnight) reset
    the idle clock, so the 10-min gate never opened and distillation never
    ran. The gateway handler runs for real; only the tracker is a recorder
    and the handler's own collaborators are stubs.
    """
    import asyncio
    import logging
    from unittest.mock import AsyncMock, MagicMock

    import backend.core.idle_tracker as idle_mod
    from backend.iris_gateway import IRISGateway

    class _Recorder:
        touches = 0

        def touch(self):
            self.touches += 1

    rec = _Recorder()
    monkeypatch.setattr(idle_mod, "get_idle_tracker", lambda: rec)

    class _Gateway:
        _main_loop = None
        _logger = logging.getLogger("test_idle_tracker_turn_busy")

        def __init__(self):
            self._send_error = AsyncMock()
            self._handle_chat = AsyncMock()
            self._touch_session = MagicMock()
            self._ws_manager = MagicMock(
                send_to_client=AsyncMock(), handle_pong=AsyncMock()
            )

    gw = _Gateway()

    def _touches_for(message):
        before = rec.touches
        asyncio.run(IRISGateway.handle_message(gw, "client-1", message, session_id="s-1"))
        return rec.touches - before

    for kind in ("pong", "ping", "heartbeat", "chat_heartbeat", "takeover_frame_ack"):
        assert _touches_for({"type": kind}) == 0, f"{kind} reset the idle clock"
    assert _touches_for({"type": "text_message", "payload": {"text": "hi"}}) == 1, (
        "a user message must reset the idle clock"
    )


def test_maintenance_guard_reads_the_shared_idle_clock():
    """The mycelium-maintenance guard must read the clock should_run reads
    (idle_minutes -> IdleTracker). The old guard read self._last_activity,
    which only start() and record_activity() set, and nothing calls
    record_activity - so it measured uptime, not idleness."""
    src = (_BACKEND / "memory" / "distillation.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_distillation"
    )
    body = ast.unparse(fn)
    assert "self.idle_minutes >= self.config.idle_threshold_minutes" in body
    assert "time.time() - self._last_activity" not in body
