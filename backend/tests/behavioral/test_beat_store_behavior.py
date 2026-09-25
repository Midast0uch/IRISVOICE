"""Behavioral: beat store as the scheduler queue (REQ-10, T13) — BT-S7.

Drives the REAL SpeechScheduler worker (no TTS, no audio) and asserts the
one rhythm mechanism: pending narration coalesces, playing always finishes.

  * ADD/REPLACE/CANCEL atomicity + logged rejection (D10)
  * burst merge: rapid findings fold into ONE line (AC10.9)
  * pivot-grade findings bypass the merge, still serialize (AC10.9)
  * debounce expiry: stale pending starts a new line (AC10.9)
  * anti-repetition bounce exactly once, then speaks regardless (AC10.12)
  * wait entry / expectation-miss / silent exit (AC10.11)

Proving tests for tasks.md T13 (matrix rows AC10.3/AC10.4/AC10.9/AC10.10/AC10.11/AC10.12).
"""
from __future__ import annotations

import threading
import time

from backend.agent.speech_lanes import (
    BEAT_MERGE_DEBOUNCE_S,
    KIND_PLANNED,
    KIND_REACTIVE,
    NARRATION,
    SpeechObservability,
    SpeechScheduler,
    WAIT_ENTRY_TEXT,
    WAIT_MISS_TEXT,
)


def _wait_until(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def _make_sched(play=None, hold=None):
    played: list = []
    lock = threading.Lock()

    def _play(node):
        if hold is not None:
            hold.wait(timeout=30.0)
        from backend.agent.speech_lanes import _node_text

        with lock:
            played.append(_node_text(node))

    obs = SpeechObservability()
    sched = SpeechScheduler(
        play=play or _play, observability=obs, auto_start=True
    )
    return sched, obs, played, lock


class TestBeatAmendmentOps:
    def test_replace_pending_cancels_and_adds(self):
        hold = threading.Event()
        sched, obs, played, _ = _make_sched(hold=hold)
        try:
            first = sched.add_beat("Checking sources.", turn_id="t1", session_id="s1")
            assert sched.pending_count() == 1
            second = sched.replace_beat(
                first, "Comparing options.", turn_id="t1", session_id="s1"
            )
            assert second is not None and second != first
            hold.set()
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing())
            assert played == ["Comparing options."]  # stale never spoken
            assert obs.counters.get("beat:beat_revision") == 1
        finally:
            hold.set()
            sched.stop()

    def test_replace_settled_is_rejected_logged(self):
        sched, obs, played, _ = _make_sched()
        try:
            beat = sched.add_beat("First line.", turn_id="t1", session_id="s1")
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing())
            assert sched.replace_beat(
                beat, "New line.", turn_id="t1", session_id="s1"
            ) is None  # already spoken — never resurrected
            assert sched.replace_beat(
                "utt_missing", "New line.", turn_id="t1", session_id="s1"
            ) is None  # unknown beat
            assert obs.counters.get("beat:beat_replace_rejected") == 2
            assert played == ["First line."]
        finally:
            sched.stop()

    def test_cancel_pending_and_unknown(self):
        hold = threading.Event()
        sched, obs, played, _ = _make_sched(hold=hold)
        try:
            beat = sched.add_beat("Pending line.", turn_id="t1", session_id="s1")
            assert sched.cancel_beat(beat, turn_id="t1", session_id="s1") is True
            assert sched.cancel_beat("utt_missing", turn_id="t1", session_id="s1") is False
            hold.set()
            assert _wait_until(lambda: not sched.is_playing())
            assert played == []
        finally:
            hold.set()
            sched.stop()


class TestBurstMerge:
    def test_rapid_findings_fold_into_one_line(self):
        """AC10.9: burst findings author ONE merged line, never N utterances."""
        hold = threading.Event()
        sched, obs, played, _ = _make_sched(hold=hold)
        try:
            sched.admit_reactive("found papers", turn_id="t1", session_id="s1")
            sched.admit_reactive("three look relevant", turn_id="t1", session_id="s1")
            sched.admit_reactive("one has full text", turn_id="t1", session_id="s1")
            assert sched.pending_count() == 1
            hold.set()
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing())
            assert played == ["found papers; three look relevant; one has full text"]
            assert obs.counters.get("beat:beat_merged") == 2
        finally:
            hold.set()
            sched.stop()

    def test_pivot_bypasses_merge_but_serializes(self):
        """AC10.9: pivot-grade findings admit immediately — still behind
        anything already playing, never cutting it."""
        hold = threading.Event()
        sched, obs, played, _ = _make_sched(hold=hold)
        try:
            sched.admit_reactive("minor detail", turn_id="t1", session_id="s1")
            sched.admit_reactive(
                "THE ANSWER CHANGED", turn_id="t1", session_id="s1", pivot=True
            )
            assert sched.pending_count() == 2  # pivot is its own node
            hold.set()
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing())
            assert played == ["minor detail", "THE ANSWER CHANGED"]
        finally:
            hold.set()
            sched.stop()

    def test_stale_pending_starts_new_line(self):
        """Past the debounce window, a finding is a new line, not a merge."""
        from backend.agent.speech_lanes import (
            SpeechObservability,
            SpeechScheduler,
            _node_text,
        )

        hold = threading.Event()
        played: list = []
        lock = threading.Lock()

        def _play(node):
            if _node_text(node) == "block":
                hold.wait(timeout=30.0)
            with lock:
                played.append(_node_text(node))

        sched = SpeechScheduler(
            play=_play, observability=SpeechObservability(), auto_start=True
        )
        try:
            sched.add_beat("block", turn_id="t1", session_id="s1")
            assert _wait_until(lambda: sched.is_playing())
            sched.admit_reactive("early note", turn_id="t1", session_id="s1")
            time.sleep(BEAT_MERGE_DEBOUNCE_S + 0.4)
            sched.admit_reactive("later note", turn_id="t1", session_id="s1")
            assert sched.pending_count() == 2  # no merge across the window
            hold.set()
            assert _wait_until(lambda: sched.pending_count() == 0
                               and not sched.is_playing())
            assert played == ["block", "early note", "later note"]
        finally:
            hold.set()
            sched.stop()


class TestAntiRepetitionBounce:
    def test_repeat_opening_bounces_once_then_speaks(self):
        """AC10.12: one bounce signal per repeated opening, then the line
        speaks regardless — the turn is never blocked. (Merge may fold the
        queued lines; the bounce count is what is pinned.)"""
        sched, obs, played, lock = _make_sched()
        try:
            sched.add_beat(
                "Checking sources", turn_id="t1", session_id="s1",
                kind=KIND_REACTIVE,
            )
            assert _wait_until(lambda: played == ["Checking sources"])
            # Identical normalized openings ([checking, sources]).
            sched.admit_reactive("Checking sources!", turn_id="t1", session_id="s1")
            sched.admit_reactive("Checking sources?", turn_id="t1", session_id="s1")
            assert _wait_until(
                lambda: obs.counters.get("beat:beat_bounced") == 1, timeout=10.0
            )
            assert _wait_until(lambda: not sched.is_playing()
                               and sched.pending_count() == 0, timeout=10.0)
            with lock:
                spoken = " ".join(played)
            assert "Checking sources!" in spoken  # bounced, yet spoken
            assert "Checking sources?" in spoken
            assert obs.counters.get("beat:beat_bounced") == 1  # exactly once
        finally:
            sched.stop()


class TestWaitStateTriggers:
    def test_long_wait_entry_miss_exit(self):
        """AC10.11: known-long wait speaks at entry; crossing the budget
        speaks once; exit is silent with results voicing via reply."""
        sched, obs, played, lock = _make_sched()
        try:
            sched.note_wait(
                "w1", turn_id="t1", session_id="s1",
                budget_s=0.4, long_wait=True,
            )
            assert _wait_until(lambda: WAIT_ENTRY_TEXT in played)
            assert obs.counters.get("beat:wait_entry") == 1
            assert _wait_until(lambda: WAIT_MISS_TEXT in played, timeout=10.0)
            assert obs.counters.get("beat:wait_miss") == 1
            sched.end_wait("w1")
            assert obs.counters.get("beat:wait_exit") == 1
            time.sleep(1.2)  # miss must never fire twice
            assert obs.counters.get("beat:wait_miss") == 1
        finally:
            sched.stop()

    def test_short_wait_no_entry_line_but_miss_fires(self):
        """Entry lines are for known-long waits only; the miss budget
        applies to every wait."""
        sched, obs, played, lock = _make_sched()
        try:
            sched.note_wait(
                "w2", turn_id="t1", session_id="s1",
                budget_s=0.3, long_wait=False,
            )
            time.sleep(1.0)
            with lock:
                assert WAIT_ENTRY_TEXT not in played
            assert _wait_until(lambda: WAIT_MISS_TEXT in played, timeout=10.0)
            sched.end_wait("w2")
        finally:
            sched.stop()

    def test_many_waits_in_one_turn_speak_one_miss_line(self):
        """Live 2026-09-24: a grafted task opened four waits inside ONE turn
        (one per sub-step) and each crossed its own budget, so the user heard
        the SAME reassurance four times in six seconds. The line reassures; it
        does not notify per wait. ONE line per turn — while every crossing is
        still recorded as its own wait_miss beat event.
        """
        sched, obs, played, lock = _make_sched()
        try:
            for n in range(4):
                sched.note_wait(
                    f"w{n}", turn_id="t1", session_id="s1",
                    budget_s=0.3, long_wait=False,
                )
            assert _wait_until(lambda: WAIT_MISS_TEXT in played, timeout=10.0)
            time.sleep(1.2)  # room for a second line to slip through
            with lock:
                spoken = " ".join(played)
            assert spoken.count(WAIT_MISS_TEXT) == 1, (
                f"four waits in one turn must speak ONE reassurance, got {spoken!r}"
            )
            assert obs.counters.get("beat:wait_miss") == 4, (
                "every crossing must still be recorded as its own beat event"
            )
        finally:
            sched.stop()

    def test_a_later_turn_speaks_its_own_miss_line(self):
        """The latch is per turn, never global: a later turn's wait must reach
        the user even seconds after the previous turn's line."""
        sched, obs, played, lock = _make_sched()
        try:
            sched.note_wait(
                "a1", turn_id="t1", session_id="s1",
                budget_s=0.3, long_wait=False,
            )
            assert _wait_until(lambda: WAIT_MISS_TEXT in played, timeout=10.0)
            sched.end_wait("a1")
            sched.note_wait(
                "b1", turn_id="t2", session_id="s1",
                budget_s=0.3, long_wait=False,
            )
            assert _wait_until(
                lambda: " ".join(played).count(WAIT_MISS_TEXT) == 2, timeout=10.0
            )
            with lock:
                spoken = " ".join(played)
            assert spoken.count(WAIT_MISS_TEXT) == 2
            assert obs.counters.get("beat:wait_miss") == 2
        finally:
            sched.stop()


class TestBeatKinds:
    def test_planned_and_reactive_kinds_preserved(self):
        sched, obs, played, _ = _make_sched()
        try:
            seen: list = []
            orig_admit = sched.admit

            def _spy(node):
                seen.append((node.kind, node.lane))
                return orig_admit(node)

            sched.admit = _spy
            sched.add_beat("Planned.", turn_id="t1", session_id="s1",
                           kind=KIND_PLANNED)
            sched.admit_reactive("Reactive.", turn_id="t1", session_id="s1",
                                 pivot=True)
            assert _wait_until(lambda: len(played) == 2)
            assert (KIND_PLANNED, "narration") in seen
            assert (KIND_REACTIVE, "narration") in seen
        finally:
            sched.stop()
