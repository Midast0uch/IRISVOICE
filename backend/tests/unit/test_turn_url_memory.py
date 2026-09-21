"""Failure-path turn-URL memory (AC2.1 / AC9.3 / AC10.2, session-319).

WHY THIS FILE EXISTS
--------------------
Turn URL memory (`_der_crawled_urls`) used to be written ONLY inside
`_der_finalize_step`, and the step loop skips finalize entirely for a failed
step. So a crawl that returned partial results and was then judged FAILED
recorded nothing, and the next step re-fetched the same addresses. That is the
owner's reported symptom: "it still recrawls the same URLs if there's an
error".

The harvest now lives in one module-level helper (`_remember_turn_urls`) called
from BOTH the finalize path and `_der_handle_step_failure`. These tests pin that
behaviour directly, so the guarantee holds for every tool call — not just the
websearch scenario it was found in.

The helper is deliberately module-level rather than a method: the behavioral
suite drives `_der_finalize_step` with a hand-rolled kernel double, and a new
instance method would not exist on it.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.agent_kernel import _remember_turn_urls


def _kernel(conv: str = "conv-test"):
    """Minimal stand-in: the helper only needs conversation_id + its own attrs."""
    return SimpleNamespace(conversation_id=conv)


def test_failed_step_still_records_source_urls():
    """The regression this work exists for: a FAILED step's URLs must land."""
    k = _kernel()
    n = _remember_turn_urls(
        k, "--- Source: https://a.example/1\n--- Source: https://b.example/2\n"
    )
    assert n == 2
    assert k._der_crawled_urls["conv-test"] == {
        "https://a.example/1",
        "https://b.example/2",
    }


def test_attempted_seeds_join_the_refusal_set():
    """AC9.3: a parked/failed fetch must be refused next time, not re-paid."""
    k = _kernel()
    _remember_turn_urls(
        k,
        "--- Attempted: https://x.example/dead https://y.example/dead\n",
    )
    assert k._der_crawled_urls["conv-test"] == {
        "https://x.example/dead",
        "https://y.example/dead",
    }


def test_dead_addresses_are_remembered_separately():
    """AC10.2: dead addresses join the refusal set AND their own set."""
    k = _kernel()
    _remember_turn_urls(k, "--- Dead: https://gone.example/404\n")
    assert "https://gone.example/404" in k._der_crawled_urls["conv-test"]
    assert "https://gone.example/404" in k._der_dead_urls["conv-test"]


def test_memory_accumulates_across_failure_then_success():
    """The whole point: a failure then a success must ADD UP, not overwrite.

    Before the fix the failure contributed nothing, so the second call's set
    was the only memory and the first step's addresses were re-fetched.
    """
    k = _kernel()
    _remember_turn_urls(k, "--- Attempted: https://first.example/1\n")
    _remember_turn_urls(k, "--- Source: https://second.example/2\n")
    assert k._der_crawled_urls["conv-test"] == {
        "https://first.example/1",
        "https://second.example/2",
    }


def test_trailing_punctuation_is_stripped():
    """URLs are harvested out of prose-ish result text; trailing . , ; ) must go."""
    k = _kernel()
    _remember_turn_urls(k, "--- Attempted: https://a.example/1, https://b.example/2).\n")
    assert k._der_crawled_urls["conv-test"] == {
        "https://a.example/1",
        "https://b.example/2",
    }


def test_empty_or_missing_result_is_safe():
    """A total crash yields no URLs — and must NOT raise or write junk."""
    k = _kernel()
    assert _remember_turn_urls(k, None) == 0
    assert _remember_turn_urls(k, "") == 0
    assert _remember_turn_urls(k, "RuntimeError: transport_error") == 0
    # Nothing recorded, so no set is fabricated.
    assert getattr(k, "_der_crawled_urls", {}) == {}


def test_conversations_are_isolated():
    """Turn memory is per-conversation; one turn must not refuse another's URLs."""
    a, b = _kernel("conv-a"), _kernel("conv-b")
    _remember_turn_urls(a, "--- Source: https://a.example/only\n")
    _remember_turn_urls(b, "--- Source: https://b.example/only\n")
    assert a._der_crawled_urls["conv-a"] == {"https://a.example/only"}
    assert b._der_crawled_urls["conv-b"] == {"https://b.example/only"}


def test_helper_never_raises_on_a_broken_kernel():
    """URL memory is advisory: a broken kernel must not break the DER loop."""
    class _Hostile:
        conversation_id = "c"
        @property
        def _der_crawled_urls(self):
            raise RuntimeError("boom")
        @_der_crawled_urls.setter
        def _der_crawled_urls(self, value):
            raise RuntimeError("boom")

    assert _remember_turn_urls(_Hostile(), "--- Source: https://a.example/1\n") == 0
