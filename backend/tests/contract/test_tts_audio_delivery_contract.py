"""TTS audio delivery contract — the slow-chunk defect, pinned.

Live 2026-09-24: once streaming had started, the voice consumer waited only
0.5 s for the next audio chunk. The worst single synthesis measured that session
took 13.81 s (214560 samples = 8.9 s of audio), so the wait threw queue.Empty
MID-REPLY and the turn's
speech was skipped ("TTS audio queue timed out after 0.5s"). The user saw the
answer and heard nothing, and the producer's full-queue latch then silenced the
rest of the turn ("consumer gone after 5.1s").

These tests drive the REAL `IRISGateway._tts_wait_for_chunk` (object.__new__: no
audio stack; a producer thread is used as the clock) and pin the behaviours the
live trace demands:

  * a chunk that arrives LATE is still returned — never dropped for lateness
  * barge-in still returns promptly, inside the poll slice, not the budget
  * a genuinely dead producer is still reported as a timeout
  * the end-of-stream sentinel is a chunk, never confused with the timeout
"""
import queue
import threading
import time

from backend.iris_gateway import (
    _TTS_CHUNK_BUDGET_S,
    _TTS_CHUNK_POLL_S,
    _TTS_END_STREAM,
    IRISGateway,
)

MEASURED_WORST_CHUNK_S = 13.81  # live 2026-09-24: 214560 samples = 8.9 s audio


def _gateway():
    return object.__new__(IRISGateway)  # no __init__: pure delivery-logic test


def _late_producer(q, delay_s, item):
    def _run():
        time.sleep(delay_s)
        q.put(item)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def test_a_slow_chunk_is_returned_not_dropped():
    """The defect: a second of silence is normal under load, not the end."""
    q = queue.Queue()
    _late_producer(q, 1.0, b"chunk")
    chunk, timed_out, barge_in = _gateway()._tts_wait_for_chunk(
        q, budget_s=_TTS_CHUNK_BUDGET_S
    )
    assert chunk == b"chunk", "a chunk 1.0 s late must still be played"
    assert timed_out is False and barge_in is False


def test_budget_covers_the_measured_worst_chunk():
    """The budget must exceed the slowest chunk measured live, with headroom."""
    assert _TTS_CHUNK_BUDGET_S > MEASURED_WORST_CHUNK_S
    assert 0.0 < _TTS_CHUNK_POLL_S < 1.0, "the poll slice keeps barge-in fast"


def test_barge_in_returns_inside_the_poll_slice():
    """A 180 s first-chunk budget must not delay the user's own interrupt."""
    q = queue.Queue()  # empty for good: the producer is still synthesizing
    flag = {"hit": False}
    threading.Timer(0.4, lambda: flag.__setitem__("hit", True)).start()
    started = time.monotonic()
    chunk, timed_out, barge_in = _gateway()._tts_wait_for_chunk(
        q, budget_s=180.0, interrupted_fn=lambda: flag["hit"]
    )
    elapsed = time.monotonic() - started
    assert chunk is None and barge_in is True and timed_out is False
    assert elapsed < 2.0, f"barge-in took {elapsed:.2f}s — must stay sub-second"


def test_dead_producer_still_reports_a_timeout():
    """Completeness budget, not a hang: a silent producer still ends the wait."""
    chunk, timed_out, barge_in = _gateway()._tts_wait_for_chunk(
        queue.Queue(), budget_s=0.5
    )
    assert chunk is None and timed_out is True and barge_in is False


def test_end_of_stream_is_a_chunk_not_a_timeout():
    q = queue.Queue()
    q.put(_TTS_END_STREAM)
    chunk, timed_out, barge_in = _gateway()._tts_wait_for_chunk(q, budget_s=1.0)
    assert chunk is _TTS_END_STREAM
    assert timed_out is False and barge_in is False
