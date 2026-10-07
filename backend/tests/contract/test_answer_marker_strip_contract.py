"""Contract: the reply never shows the prompt's ANSWER: label (reply surface).

Live 2026-10-06, recorded in __tests__/fixtures/turns/recorded_personal_ok.json:
the [RESPONSE FORMAT] prompt block teaches the reply format with a literal
"ANSWER:" label (agent_kernel.py), and the model copied the label into its
reply — the streamed delta, the final text AND the spoken line all started
with "ANSWER: The capital of Japan is Tokyo".

The single reply exit strips one leading label: AgentKernel._finalize_response
(every return of _process_structured_response goes through it) cleans the
display text and the spoken line via artifact_policy.strip_leading_answer_marker.
A marker mid-text is prose and stays. Guard: fails on the old code (no strip
at the exit — the recorded reply passed through unchanged).
"""
from __future__ import annotations

import json

import pytest

import backend.agent.event_bus as _eb_mod
from backend.agent.agent_kernel import AgentKernel


# The reply the model actually produced in the recorded turn (fixture
# recorded_personal_ok.json): the prompt's format label copied to the front.
RECORDED_REPLY = "ANSWER: The capital of Japan is Tokyo."


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, **kw):
        self.events.append((event, data))


@pytest.fixture()
def kernel(monkeypatch):
    k = AgentKernel.__new__(AgentKernel)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    bus = _Bus()
    monkeypatch.setattr(_eb_mod, "get_event_bus", lambda: bus)
    return k, bus


def test_the_recorded_leak_is_stripped_from_the_display(kernel):
    """The exact recorded reply: the label must not reach the thread."""
    k, _bus = kernel
    out = AgentKernel._process_structured_response(
        k, RECORDED_REPLY, turn_id="t-leak", conversation_id="c"
    )
    assert out == "The capital of Japan is Tokyo.", out


def test_the_recorded_leak_is_stripped_from_the_spoken_line(kernel):
    """The recorded turn's speak line carried the label too: the model's own
    TTS line is cleaned at the same exit."""
    k, _bus = kernel
    out = AgentKernel._finalize_response(k, "shown text", RECORDED_REPLY)
    assert out == "shown text"
    assert k._last_spoken_text == "The capital of Japan is Tokyo.", k._last_spoken_text


def test_a_structured_speak_line_is_cleaned_too(kernel):
    """A structured reply whose speak field carries the label: the bubble
    comes from the speak line on this branch, so it must be clean."""
    k, _bus = kernel
    payload = json.dumps({
        "speak": "ANSWER: The capital of Japan is Tokyo.",
        "show": {"format": "markdown", "content": "# Doc\n\nbody"},
    })
    out = AgentKernel._process_structured_response(
        k, payload, turn_id="t-struct", conversation_id="c"
    )
    assert out == "The capital of Japan is Tokyo.", out
    assert k._last_spoken_text == "The capital of Japan is Tokyo.", k._last_spoken_text


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("ANSWER: plain", "plain"),
        ("\n\nANSWER: after blank lines", "after blank lines"),
        ("**ANSWER:** bold label", "bold label"),
        ("__ANSWER:__ underscore label", "underscore label"),
        ("Answer: lower case", "lower case"),
        ("answer: all lower", "all lower"),
        ("ANSWER:no space", "no space"),
        ("ANSWER：full-width colon", "full-width colon"),
    ],
)
def test_one_leading_label_variant_is_dropped(kernel, reply, expected):
    k, _bus = kernel
    out = AgentKernel._finalize_response(k, reply, None)
    assert out == expected, out


@pytest.mark.parametrize(
    "reply",
    [
        # Not the format label: prose that mentions it, plural, or no colon.
        "The ANSWER: label in the prompt leaked before.",
        "Answers: one, two, three.",
        "ANSWER is the label the prompt teaches.",
        # Mid-text occurrences are prose and stay.
        "First line.\n\nANSWER: second paragraph stays.",
    ],
)
def test_prose_and_mid_text_markers_stay(kernel, reply):
    k, _bus = kernel
    out = AgentKernel._finalize_response(k, reply, None)
    assert out == reply, out
