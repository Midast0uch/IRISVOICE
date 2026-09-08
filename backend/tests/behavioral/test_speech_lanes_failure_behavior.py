"""Behavioral: SpeechScheduler failure semantics (REQ-8, REQ-7 AC7.3) — BT-S6.

Drives FULL scheduler turns through the real worker with scripted play
functions (no TTS, no audio) and asserts emergent properties:

  * wedged node → failed, derived gates freed, turn continues (AC7.3)
  * failed node → marked failed, turn continues visibly without it (AC8.1)
  * REPLY/ALERT death → exactly one one-breath Critical notice per turn (AC8.2)
  * failed node retried exactly once, then dropped (AC8.3)
  * 3+ distinct dead nodes in one turn → turn drains, bounded work (edge)

Proving tests for tasks.md T8 (matrix rows AC7.3, AC8.1–AC8.3).
"""
from __future__ import annotations

import threading
import time

from backend.agent.speech_lanes import (
    ALERT_CRITICAL,
    FAILURE_NOTICE_KIND,
    NARRATION,
    REPLY,
    SpeechObservability,
    SpeechScheduler,
    UtteranceNode,
)


def _node(lane, turn_id="t1", session_id="s1", text="hi", deadline=None):
    node = UtteranceNode(
        id=f"utt_{lane}_{turn_id}_{text}_{time.time_ns()}",
        lane=lane,
        trigger={"source": "test", "label": lane, "rule_fired": "L1:test"},
        turn_id=turn_id,
        session_id=session_id,
        content={"kind": "text", "text": text},
    )
    if deadline is not None:
        node.deadline = deadline
    return node


def _wait_until(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def _make_sched(play, gate_calls=None):
    obs = SpeechObservability()
    sched = SpeechScheduler(
        play=play,
        observability=obs,
        auto_start=True,
        gate=(lambda a: gate_calls.append(a)) if gate_calls is not None else None,
    )
    return sched, obs


class TestNodeFailContinuesVisibly:
    def test_play_exception_fails_narration_and_turn_continues(self):
        """AC8.1: a dead narration node is marked failed; the turn plays on."""
        played = []
        lock = threading.Lock()

        def play(node):
            if node.content["text"] == "boom":
                raise RuntimeError("worker died mid-utterance")
            with lock:
                played.append(node.content["text"])

        sched, obs = _make_sched(play)
        try:
            bad = _node(NARRATION, turn_id="t1", text="boom")
            good = _node(NARRATION, turn_id="t1", text="after")
            sched.admit(bad)
            sched.admit(good)
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing())
            assert bad.state == "failed"
            assert good.state == "done"
            with lock:
                assert played == ["after"]
            # Failed once, retried once (AC8.3), then dropped — and the retry
            # is recorded, not silent.
            counts = obs.counters.snapshot()
            assert counts.get("node:failed", 0) >= 1
        finally:
            sched.stop()


class TestWatchdogFreesGates:
    def test_wedged_node_failed_gates_freed_worker_survives(self):
        """AC7.3: a node wedged past its deadline fails, gates free, next plays."""
        blocker = threading.Event()
        released = {"go": False}
        played = []
        lock = threading.Lock()
        gate_calls: list = []

        def play(node):
            # The wedge blocks until the test releases it; the retry (after
            # release) and the follower play straight through.
            if node.content["text"] == "wedge" and not released["go"]:
                blocker.wait(timeout=30.0)
            with lock:
                played.append(node.content["text"])

        sched, obs = _make_sched(play, gate_calls)
        try:
            wedge = _node(NARRATION, turn_id="t1", text="wedge")
            wedge.deadline = time.time() + 0.3
            follower = _node(NARRATION, turn_id="t1", text="follower")
            sched.admit(wedge)
            sched.admit(follower)
            # The wedge trips (deadline 0.3 s) while the play call is still
            # blocked: the failure counter persists even though the node is
            # immediately retried, and the gate frees although _play_fn
            # never returned.
            assert _wait_until(
                lambda: obs.counters.snapshot().get("node:failed", 0) >= 1,
                timeout=10.0,
            )
            assert False in gate_calls  # gate reopened on wedge-fail
            # Release the wedged call; the retry + follower must still play —
            # the worker was never pinned.
            released["go"] = True
            blocker.set()
            assert _wait_until(lambda: "follower" in played, timeout=10.0)
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing(), timeout=10.0)
            assert gate_calls[-1] is False
            counts = obs.counters.snapshot()
            assert counts.get("node:failed", 0) >= 1
        finally:
            released["go"] = True
            blocker.set()
            sched.stop()


class TestOneBreathCriticalCap:
    def test_two_dead_replies_yield_exactly_one_notice(self):
        """AC8.2: REPLY deaths speak one Critical notice per turn, never a loop."""
        played = []
        lock = threading.Lock()

        def play(node):
            if node.content.get("kind") == FAILURE_NOTICE_KIND:
                with lock:
                    played.append(("notice", node.content["text"]))
                return
            if node.lane == REPLY:
                raise RuntimeError("reply synthesis died")
            with lock:
                played.append(("other", node.content["text"]))

        sched, _ = _make_sched(play)
        try:
            r1 = _node(REPLY, turn_id="t1", text="reply-one")
            r2 = _node(REPLY, turn_id="t1", text="reply-two")
            sched.admit(r1)
            sched.admit(r2)
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing(), timeout=10.0)
            notices = [p for p in played if p[0] == "notice"]
            assert len(notices) == 1  # one breath, not one per death
            assert r1.state == "failed"
            assert r2.state == "failed"
        finally:
            sched.stop()


class TestRetryOnceThenDrop:
    def test_failing_node_tried_exactly_twice(self):
        """AC8.3: at most one retry on the next pass, then the node drops."""
        attempts: dict = {}
        lock = threading.Lock()

        def play(node):
            with lock:
                attempts[node.id] = attempts.get(node.id, 0) + 1
            raise RuntimeError("persistent worker death")

        sched, _ = _make_sched(play)
        try:
            bad = _node(NARRATION, turn_id="t1", text="flaky")
            sched.admit(bad)
            assert _wait_until(lambda: bad.state == "failed"
                               and sched.pending_count() == 0
                               and not sched.is_playing(), timeout=10.0)
            with lock:
                assert attempts.get(bad.id, 0) == 2  # first try + exactly one retry
        finally:
            sched.stop()


class TestCascadingDrain:
    def test_three_distinct_deaths_drain_the_turn(self):
        """REQ-8 edge: 3+ distinct dead nodes in one turn → bounded drain."""
        calls: dict = {}
        lock = threading.Lock()

        def play(node):
            with lock:
                calls[node.id] = calls.get(node.id, 0) + 1
            raise RuntimeError("lane is broken")

        sched, _ = _make_sched(play)
        try:
            nodes = [_node(NARRATION, turn_id="t1", text=f"n{i}") for i in range(3)]
            for n in nodes:
                sched.admit(n)
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing(), timeout=10.0)
            with lock:
                total = sum(calls.values())
            # Bounded: first tries + at most one retry each before the trip
            # drains the turn — never an infinite respawn.
            assert total <= 6
            assert all(n.state in ("failed", "cancelled") for n in nodes)
        finally:
            sched.stop()

    def test_other_turn_unaffected_by_drain(self):
        """The drain is turn-scoped: a healthy turn still plays."""
        played = []
        lock = threading.Lock()

        def play(node):
            if node.turn_id == "bad-turn":
                raise RuntimeError("lane is broken")
            with lock:
                played.append(node.content["text"])

        sched, _ = _make_sched(play)
        try:
            for i in range(3):
                sched.admit(_node(NARRATION, turn_id="bad-turn", text=f"bad{i}"))
            good = _node(NARRATION, turn_id="good-turn", text="good")
            sched.admit(good)
            assert _wait_until(lambda: good.state == "done", timeout=10.0)
            with lock:
                assert "good" in played
        finally:
            sched.stop()


class TestFailureNoticeShape:
    def test_notice_is_critical_one_breath(self):
        """The AC8.2 notice rides the Critical lane and stays short."""
        seen = []
        lock = threading.Lock()

        def play(node):
            if node.content.get("kind") == FAILURE_NOTICE_KIND:
                with lock:
                    seen.append(node)
                return
            raise RuntimeError("reply died")

        sched, _ = _make_sched(play)
        try:
            sched.admit(_node(REPLY, turn_id="t1", text="reply"))
            assert _wait_until(lambda: len(seen) >= 1, timeout=10.0)
            notice = seen[0]
            assert notice.lane == ALERT_CRITICAL
            assert len(notice.content["text"].split()) <= 20
        finally:
            sched.stop()
