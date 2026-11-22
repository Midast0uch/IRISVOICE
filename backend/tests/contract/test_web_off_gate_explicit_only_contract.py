"""The internet-access gate refuses ONLY an explicit web request (2026-11-22).

Found in the TG-2 small-model gate (wb_gate-20261122-170743): x06_timeframe_recall
failed 4/4, both arms, with the canned "Web search is currently disabled" reply in
the same second as the question. The task asks about EARLIER CHATS ("which auth
provider did we pick FIRST, before the switch?"). The gate called
`_is_web_search_request`, which asks the Oracle's web_intent consumer ("does this
goal need the web?"); it said yes at 0.844, over its enforcement point, and the
gate took that guess as "the user asked for a web search". The owner heard the
refusal spoken.

The guard drives the real gate function with the Oracle forced to say yes. On the
old code the turn took the Oracle's word (structural check below fails), and the
function did not exist.
"""
from __future__ import annotations

from backend.tests._kernel_source import kernel_function_source

MEMORY_Q = ("For project quill-3e05, which auth provider did we pick FIRST, before the "
            "switch? Reply with the provider name only.")


def _gate():
    from backend.agent.kernel.turn import _web_off_reply
    return _web_off_reply


def test_a_memory_question_is_not_refused_even_when_the_oracle_says_web(monkeypatch):
    from backend.agent import explorer
    # The Oracle answers "yes" whenever it is asked (an engine is passed), as it did live.
    monkeypatch.setattr(explorer, "_engine_web_intent",
                        lambda goal, engine, **k: True if engine is not None else None)
    assert explorer._is_web_intent(MEMORY_Q, engine=object()) is True   # the old gate's answer
    assert _gate()(MEMORY_Q, False) is None


def test_an_explicit_web_request_is_still_answered_with_the_toggle_hint():
    reply = _gate()("search the web for the latest rust release", False)
    assert reply and "Web search is currently disabled" in reply and "toggle" in reply
    assert _gate()("open the docs in the live browser", False)


def test_nothing_is_refused_while_the_web_is_on():
    assert _gate()("search the web for the latest rust release", True) is None


def test_the_turn_gate_does_not_ask_the_oracle():
    """The turn uses the explicit-only gate, not `_is_web_search_request` (the Oracle path)."""
    from backend.tests._kernel_source import kernel_source

    assert "engine=None" in kernel_function_source("_web_off_reply")
    text = kernel_source()
    assert "_web_off_reply(text, get_global_internet_access())" in text
    assert "self._is_web_search_request(text) or _LIVE_BROWSER_RE" not in text
