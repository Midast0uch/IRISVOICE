"""T5 (chat-communication-lanes REQ-4, session-342 P6): TTS no-consumer guard.

Drives the REAL latch helpers on IRISGateway (`object.__new__` — no audio
stack, no threads) exactly as `_put_chunk` drives them live:

  - consumer gone once in a turn  -> ONE WARN, then silent fail-fast
  - later calls in the SAME turn  -> no second log (the flood, killed)
  - a DIFFERENT turn id           -> latch cleared (consumer may be back)
  - a stale latch (>60 s)         -> one honest retry, never a wedged turn

The guard lives in `IRISGateway._speak_response`'s `_put_chunk`; these tests
pin the decision logic the closure delegates to.
"""
import logging
import time

from backend.iris_gateway import IRISGateway


def _gateway():
    gw = object.__new__(IRISGateway)  # no __init__: pure decision-logic test
    gw._logger = logging.getLogger("test.tts-no-consumer")
    return gw


def _warn_count(gw, monkeypatch):
    calls = []
    monkeypatch.setattr(gw._logger, "warning", lambda *a, **k: calls.append(a))
    return calls


def test_consumer_gone_turn_logs_once_and_silences_the_rest(monkeypatch):
    """REQ-4 AC1: the ~25 s flood of repeated 'consumer gone' errors becomes
    exactly ONE WARN per turn."""
    gw = _gateway()
    calls = _warn_count(gw, monkeypatch)

    gw._tts_no_consumer_latch_set("turn-A", stalled_s=5.2)
    assert len(calls) == 1, "first consumer-gone event must log once"

    # The same turn, asked again and again (the flood shape): all silent.
    for _ in range(50):
        assert gw._tts_no_consumer_skip("turn-A") is True
    assert len(calls) == 1, "the flood: 50 repeats must not log again"

    # Only THEN does a new turn id clear the latch (consumer may be back).
    assert not gw._tts_no_consumer_skip("turn-B")


def test_new_turn_clears_the_latch(monkeypatch):
    """A fresh turn gets a fresh chance — the consumer may have come back."""
    gw = _gateway()
    gw._tts_no_consumer_latch_set("turn-A", stalled_s=5.0)
    assert gw._tts_no_consumer_skip("turn-B") is False
    assert gw._tts_no_consumer_latch is None
    # And with the latch cleared, the new turn can learn its own bad news.
    gw._tts_no_consumer_latch_set("turn-B", stalled_s=5.0)
    assert gw._tts_no_consumer_skip("turn-B") is True


def test_stale_latch_expires_for_one_retry(monkeypatch):
    """A latch older than 60 s must not wedge a turn whose turn id repeats —
    one honest retry, then re-latch if the consumer is still gone."""
    gw = _gateway()
    gw._tts_no_consumer_latch = ("turn-A", time.monotonic() - 61.0)
    assert gw._tts_no_consumer_skip("turn-A") is False
    assert gw._tts_no_consumer_latch is None


def test_intact_consumer_path_unchanged(monkeypatch):
    """REQ-4 AC2: no latch ever set -> the guard is invisible to a healthy
    turn (skip says proceed, nothing logged, no state left behind)."""
    gw = _gateway()
    calls = _warn_count(gw, monkeypatch)
    assert gw._tts_no_consumer_skip("turn-live") is False
    assert gw._tts_no_consumer_skip("turn-live") is False
    assert calls == []
    assert getattr(gw, "_tts_no_consumer_latch", None) is None
