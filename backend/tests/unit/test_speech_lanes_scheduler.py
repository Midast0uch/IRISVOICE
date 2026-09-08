"""Unit: SpeechScheduler — serialize/preempt/subsume/turn-boundary (REQ-2, REQ-4, REQ-5).

Pins the lane scheduler's admission rules with a fake play function (no TTS,
no audio). Covers: lane-priority serialization + FIFO (AC2.2), subsumption of
pending narration on reply (AC4.2), critical preemption (AC4.3), barge-in
kill-and-fresh (AC4.1), turn-boundary narration death + reply survival
(AC5.1/AC5.2), and derived is_playing gate (AC7.2).
"""
from __future__ import annotations

import threading
import time

import pytest

from backend.agent.speech_lanes import (
    ALERT_AWAITING,
    ALERT_CRITICAL,
    NARRATION,
    REPLY,
    SpeechScheduler,
    UtteranceNode,
)


def _node(lane, turn_id="t1", session_id="s1", text="hi"):
    return UtteranceNode(
        id=f"utt_{lane}_{turn_id}_{time.time_ns()}",
        lane=lane,
        trigger={"source": "test", "label": lane, "rule_fired": "L1:test"},
        turn_id=turn_id,
        session_id=session_id,
        content={"kind": "text", "text": text},
    )


class _Recorder:
    """Collects played node ids in order; blocks on a gate when told."""

    def __init__(self):
        self.played = []
        self.lock = threading.Lock()
        self._gate = None

    def play(self, node):
        with self.lock:
            self.played.append(node.id)
        if self._gate is not None:
            self._gate.wait(timeout=2.0)

    def set_gate(self, evt):
        self._gate = evt


def _wait_until(pred, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


# ── REQ-2 AC2.2: priority serialize + FIFO ────────────────────────────────
class TestSerialization:
    def test_priority_order_then_fifo(self):
        rec = _Recorder()
        sched = SpeechScheduler(play=rec.play, auto_start=True)
        # Use non-subsuming lanes (reply + awaiting) so priority ordering is
        # isolated from subsumption. Awaiting (prio 1) beats reply (prio 2);
        # equal-priority replies are FIFO.
        a1 = _node(ALERT_AWAITING, text="a1")
        r1 = _node(REPLY, text="r1")
        r2 = _node(REPLY, text="r2")
        sched.admit(r1)
        sched.admit(a1)
        sched.admit(r2)
        assert _wait_until(lambda: len(rec.played) >= 3)
        # Awaiting (priority 1) plays before both replies (priority 2); the
        # two replies are FIFO.
        assert rec.played[0] == a1.id
        assert rec.played[1] == r1.id
        assert rec.played[2] == r2.id
        sched.stop()

    def test_is_playing_derived_gate(self):
        rec = _Recorder()
        gate = threading.Event()
        rec.set_gate(gate)
        sched = SpeechScheduler(play=rec.play, auto_start=True)
        sched.admit(_node(NARRATION))
        assert _wait_until(lambda: sched.is_playing())
        gate.set()  # release
        assert _wait_until(lambda: not sched.is_playing())
        sched.stop()


# ── REQ-7 AC7.2: derived half-duplex mic gate ───────────────────────────────
class TestDerivedGate:
    def test_gate_follows_running_state(self):
        """The half-duplex mic gate derives from scheduler state (REQ-7 AC7.2):
        closed (True) while a play-node runs, reopened (False) when idle."""
        rec = _Recorder()
        gate = threading.Event()
        rec.set_gate(gate)
        calls: list = []
        sched = SpeechScheduler(
            play=rec.play, auto_start=True, gate=lambda a: calls.append(a)
        )
        sched.admit(_node(NARRATION))
        assert _wait_until(lambda: sched.is_playing())
        assert calls and calls[-1] is True  # gate closed while playing
        gate.set()  # release
        assert _wait_until(lambda: not sched.is_playing())
        assert calls[-1] is False  # gate reopened when idle
        sched.stop()

    def test_barge_in_reopens_gate_immediately(self):
        """Barge-in reopens the mic gate synchronously (REQ-7 AC7.2) so the new
        turn's recording starts capturing without waiting for the worker."""
        rec = _Recorder()
        gate = threading.Event()
        rec.set_gate(gate)
        calls: list = []
        sched = SpeechScheduler(
            play=rec.play, auto_start=True, gate=lambda a: calls.append(a)
        )
        sched.admit(_node(NARRATION))
        assert _wait_until(lambda: sched.is_playing())
        sched.barge_in(turn_id="t2", session_id="s1")
        assert calls[-1] is False  # gate reopened immediately on barge-in
        gate.set()
        sched.stop()

    def test_gate_failure_never_wedges_scheduler(self):
        """A gate callback that raises must not block the scheduler worker."""
        rec = _Recorder()
        sched = SpeechScheduler(
            play=rec.play,
            auto_start=True,
            gate=lambda a: (_ for _ in ()).throw(RuntimeError("gate boom")),
        )
        sched.admit(_node(NARRATION))
        assert _wait_until(lambda: len(rec.played) >= 1)
        assert _wait_until(lambda: not sched.is_playing())
        sched.stop()


# ── REQ-4 AC4.2: subsumption ──────────────────────────────────────────────
class TestSubsumption:
    def test_reply_cancels_pending_narration(self):
        rec = _Recorder()
        gate = threading.Event()
        rec.set_gate(gate)  # hold the first (running) narration
        sched = SpeechScheduler(play=rec.play, auto_start=True)
        n1 = _node(NARRATION, text="running-narration")
        sched.admit(n1)
        assert _wait_until(lambda: sched.is_playing())
        n2 = _node(NARRATION, text="queued-narration")
        sched.admit(n2)
        r = _node(REPLY, text="reply")
        sched.admit(r)
        gate.set()  # release the running narration
        assert _wait_until(lambda: len(rec.played) >= 2)
        # The queued narration n2 was subsumed (cancelled, never played);
        # only n1 (already playing) and the reply played.
        assert n2.id not in rec.played
        assert r.id in rec.played
        sched.stop()


# ── REQ-4 AC4.3: critical preemption ──────────────────────────────────────
class TestPreemption:
    def test_critical_preempts_running(self):
        rec = _Recorder()
        gate = threading.Event()
        rec.set_gate(gate)
        sched = SpeechScheduler(play=rec.play, auto_start=True)
        n1 = _node(NARRATION, text="running")
        sched.admit(n1)
        assert _wait_until(lambda: sched.is_playing())
        crit = _node(ALERT_CRITICAL, text="critical")
        sched.admit(crit)
        # Critical preempts: running narration cancelled, critical plays.
        assert _wait_until(lambda: len(rec.played) >= 1)
        gate.set()
        assert _wait_until(lambda: crit.id in rec.played)
        sched.stop()


# ── REQ-4 AC4.1: barge-in ─────────────────────────────────────────────────
class TestBargeIn:
    def test_barge_in_kills_running_and_pending(self):
        rec = _Recorder()
        gate = threading.Event()
        rec.set_gate(gate)
        sched = SpeechScheduler(play=rec.play, auto_start=True)
        sched.admit(_node(NARRATION, text="running"))
        assert _wait_until(lambda: sched.is_playing())
        sched.admit(_node(NARRATION, text="pending1"))
        sched.admit(_node(NARRATION, text="pending2"))
        sched.barge_in(turn_id="t2", session_id="s1")
        gate.set()
        # Only the running node played; pending were killed.
        assert _wait_until(lambda: not sched.is_playing())
        assert len(rec.played) == 1
        assert sched.pending_count() == 0
        sched.stop()


# ── REQ-5 AC5.1/AC5.2: turn boundary ──────────────────────────────────────
class TestTurnBoundary:
    def test_narration_dies_reply_survives(self):
        rec = _Recorder()
        sched = SpeechScheduler(play=rec.play, auto_start=True)
        # Queue a narration and a reply for turn t1.
        sched.admit(_node(NARRATION, turn_id="t1", text="narration"))
        sched.admit(_node(REPLY, turn_id="t1", text="reply"))
        # Turn t1 ends: narration cancelled, reply survives.
        sched.cancel_turn("t1")
        assert _wait_until(lambda: len(rec.played) >= 1)
        # Only the reply played; the narration was cancelled at turn end.
        assert len(rec.played) == 1
        sched.stop()

    def test_awaiting_survives_turn_boundary(self):
        rec = _Recorder()
        sched = SpeechScheduler(play=rec.play, auto_start=True)
        sched.admit(_node(ALERT_AWAITING, turn_id="t1", text="awaiting"))
        sched.cancel_turn("t1")
        assert _wait_until(lambda: len(rec.played) >= 1)
        assert len(rec.played) == 1  # awaiting survived
        sched.stop()