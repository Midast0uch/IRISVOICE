"""REQ-1 (specs/oracle-native-decision-surface): the native readout.

The A/B/C letter menu is RETIRED from scoring (AC1.4). A `choice` renders
LiquidAI's criteria block and pools over the option NAME tokens (AC1.2); a
`noul` renders the yes/no instruction and pools over the yes/no forms (AC1.3);
the transport is `/v1/chat/completions` (AC1.1); and a failure to score returns
None so the consumer fails closed, exactly as before.

These tests are OFFLINE and deterministic: the tokenizer is stubbed, so the
readout's behaviour is pinned without a live server.
"""
from __future__ import annotations

from pathlib import Path

from backend.agent import decision_engine as de
from backend.agent.decision_backend_d1 import (
    D1Backend,
    _extract_logprobs,
    _extract_logprobs_all,
)

_BACKEND_SRC = Path("backend/agent/decision_backend_d1.py")


# ── AC1.2/AC1.3: the renderers ──────────────────────────────────────────────

def test_choice_renders_the_named_criteria_block():
    """The answer IS the name; the block is `name: description`."""
    crit = {"pass": "The step did its part", "veto": "Must not run"}
    out = D1Backend._question_choice("a state", "Did it work?", crit, ["pass", "veto"])
    assert "pass: The step did its part" in out
    assert "veto: Must not run" in out
    assert "Reply with the option name only." in out
    assert "Reply with the option code only." not in out


def test_choice_renders_a_bare_name_when_no_description_is_declared():
    out = D1Backend._question_choice("s", "q", {}, ["alpha", "beta"])
    assert "alpha" in out and "beta" in out


def test_noul_renders_the_yes_no_instruction():
    out = D1Backend._question_noul("a state", "Is the task finished?")
    assert "Is the task finished?" in out
    assert "Reply with yes or no only." in out


# ── AC1.4: the letter path is GONE ──────────────────────────────────────────

def test_the_letter_menu_is_retired_from_scoring():
    src = _BACKEND_SRC.read_text(encoding="utf-8")
    assert "_LETTERS" not in src, "the A/B/C letter readout must be retired (AC1.4)"
    assert "Reply with the option code only." not in src
    # No request is posted to the retired /completion route. (The route is named
    # in the docstring, which records WHY it was retired - prose is not a call.)
    assert "/completion\"" not in src and "/completion'" not in src
    assert "{_server_port()}/completion" not in src


def test_the_transport_is_chat_completions():
    src = _BACKEND_SRC.read_text(encoding="utf-8")
    assert "/v1/chat/completions" in src


# ── AC0.3: per-position parsing (both shapes) ───────────────────────────────

def test_per_position_parse_reads_both_shapes():
    completion = {"completion_probabilities": [
        {"top_logprobs": [{"id": 10, "logprob": -1.0}]},
        {"top_logprobs": [{"id": 11, "logprob": -2.0}]},
    ]}
    chat = {"choices": [{"logprobs": {"content": [
        {"top_logprobs": [{"id": 10, "logprob": -1.0, "bytes": [116]}]},
        {"top_logprobs": [{"id": 11, "logprob": -2.0, "bytes": [116]}]},
    ]}}]}
    assert _extract_logprobs_all(completion) == [{10: -1.0}, {11: -2.0}]
    assert _extract_logprobs_all(chat) == [{10: -1.0}, {11: -2.0}]
    # Position 0 is what the answer-slot helper returns.
    assert _extract_logprobs(chat) == {10: -1.0}


# ── AC1.2: the readout, and the collision widening ──────────────────────────

def _backend_with_tokens(monkeypatch, table):
    b = D1Backend()
    b._name_ids = dict(table)          # prime the cache: no HTTP in the test
    return b


def test_readout_reads_the_first_token_when_names_are_separable(monkeypatch):
    b = _backend_with_tokens(monkeypatch, {"pass": [10], "veto": [11]})
    got = b._name_readout(["pass", "veto"])
    assert got is not None
    plan, width = got
    assert width == 1
    assert plan == {"pass": ((10,),), "veto": ((11,),)}


def test_readout_widens_when_two_names_share_their_first_token(monkeypatch):
    """`speak_all` and `speak_first_only` both begin `speak`: a first-token
    max-pool would hand them EQUAL probability. The readout must widen to the
    full name sequence instead, so no consumer loses its scoring (AC9.5)."""
    b = _backend_with_tokens(monkeypatch, {
        "speak_all": [6575, 40387],
        "speak_first_only": [6575, 95350],
        "stay_silent": [5275],
    })
    got = b._name_readout(["speak_all", "speak_first_only", "stay_silent"])
    assert got is not None
    plan, width = got
    assert width == 2, "the readout must widen past the colliding first token"
    assert plan["speak_all"] == ((6575,), (40387,))
    assert plan["speak_first_only"] == ((6575,), (95350,))


def test_readout_refuses_when_two_names_are_identical(monkeypatch):
    """Truly inseparable options cannot be scored: a coin flip reported as a
    calibrated probability is worse than no row (AC1.4)."""
    b = _backend_with_tokens(monkeypatch, {"alpha": [5], "beta": [5]})
    assert b._name_readout(["alpha", "beta"]) is None


def test_readout_refuses_a_name_with_no_tokenizer_form(monkeypatch):
    b = _backend_with_tokens(monkeypatch, {"alpha": [], "beta": [5]})
    assert b._name_readout(["alpha", "beta"]) is None


# ── AC1.6: an undeclared consumer still scores nothing ──────────────────────

def test_undeclared_consumer_is_refused_before_scoring(monkeypatch):
    b = D1Backend()
    b._loaded = True
    monkeypatch.setattr(b, "_serves_d1", lambda force=False: (True, ""))
    assert b.decide("never_declared", ["a", "b"], {"goal": "x"}) is None


# ── REQ-5 (AC5.1): the state's images become content parts, text FIRST ──────

def test_images_become_image_parts_after_the_text():
    """Measured hazard (Wave 0 probe): an image-FIRST content order got HTTP
    200 with NO logprobs on this server build, so the readout would score
    nothing and the consumer would silently fail closed. Text first, always.
    """
    parts = D1Backend._message_content("the question", [b"\x89PNGfake"])
    assert parts[0] == {"type": "text", "text": "the question"}
    assert len(parts) == 2 and parts[1]["type"] == "image_url"
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    import base64 as _b64

    assert _b64.b64decode(url.split(",", 1)[1]) == b"\x89PNGfake"


def test_a_text_only_state_sends_one_text_part():
    parts = D1Backend._message_content("the question")
    assert parts == [{"type": "text", "text": "the question"}]


def test_every_declared_consumer_has_a_scorable_shape():
    """Every consumer in CONSUMERS declares a type AND either yes/no labels
    (noul) or named options (choice)."""
    for cid in de.CONSUMERS:
        assert de.is_declared(cid), cid
