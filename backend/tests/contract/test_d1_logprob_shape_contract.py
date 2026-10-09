"""AC0.3 (Wave 0, specs/oracle-native-decision-surface): the readout reads
``id``, never ``bytes[0]``.

llama.cpp answers two logprob shapes depending on the route:

  * ``/completion``          -> top-level ``completion_probabilities``
  * ``/v1/chat/completions`` -> OpenAI ``choices[0].logprobs.content[]``
                                ``.top_logprobs``

Both carry ``id`` (the token id) AND ``bytes`` (the utf-8 byte list). Reading
``bytes[0]`` yields a CHARACTER CODE - 116 is the letter "t" - which silently
mismatches every readout token. That defect voided two probe runs on
2026-10-08 and is the reason AC0.3 exists.

This test feeds both shapes the SERVER actually returns and asserts the same
token ids come back, so the rule cannot regress.
"""
from __future__ import annotations

from backend.agent.decision_backend_d1 import _extract_logprobs

# Payloads captured live from the shared d1 server on :8082. The 'two' entry
# is deliberate: its bytes[0] is 116 (the letter "t"), which is NOT its id.
_COMPLETION_SHAPE = {
    "completion_probabilities": [{
        "id": 5902, "token": "more", "bytes": [109, 111, 114, 101],
        "logprob": -0.559,
        "top_logprobs": [
            {"id": 5902, "token": "more", "bytes": [109, 111, 114, 101], "logprob": -0.559},
            {"id": 734, "token": "one", "bytes": [111, 110, 101], "logprob": -1.2},
            {"id": 1046, "token": "two", "bytes": [116, 119, 111], "logprob": -2.0},
        ],
    }],
}

_CHAT_SHAPE = {
    "choices": [{
        "logprobs": {"content": [{
            "id": 5902, "token": "more", "bytes": [109, 111, 114, 101], "logprob": -0.559,
            "top_logprobs": [
                {"id": 5902, "token": "more", "bytes": [109, 111, 114, 101], "logprob": -0.559},
                {"id": 734, "token": "one", "bytes": [111, 110, 101], "logprob": -1.2},
                {"id": 1046, "token": "two", "bytes": [116, 119, 111], "logprob": -2.0},
            ],
        }]},
    }],
}


def test_both_shapes_yield_the_same_token_ids():
    a = _extract_logprobs(_COMPLETION_SHAPE)
    b = _extract_logprobs(_CHAT_SHAPE)
    assert a and a == b, (a, b)
    assert set(a) == {5902, 734, 1046}


def test_bytes_first_element_is_never_used_as_an_id():
    """'two' has bytes[0] == 116 ('t'). If the parser read bytes[0] the id 116
    would appear; the true id is 1046."""
    got = _extract_logprobs(_CHAT_SHAPE)
    assert 116 not in got
    assert got[1046] == -2.0


def test_empty_payloads_return_no_logprobs():
    assert _extract_logprobs({}) == {}
    assert _extract_logprobs({"completion_probabilities": []}) == {}
    assert _extract_logprobs({"choices": [{}]}) == {}
