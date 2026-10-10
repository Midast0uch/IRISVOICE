"""The d1 readout — the REFERENCE implementation, restored (2026-10-10).

WHY THIS FILE EXISTS

d1 is a post-trained decision model: its calibrated distribution lives in the
LETTER-CODE tokens of its trained prompt shape (LiquidAI/d1-3B prompt.py):
options render as ``A {text}``, the model replies with the code, and the
readout max-pools each code with its space-prefixed form at the ONE answer
slot. The Wave-2 change that retired letters in favour of option-NAME tokens
read a distribution the model was never trained to calibrate: measured live
on our own llama-server and GGUF (2026-10-10, logs/_probe_d1_reference.py,
_probe_d1_styles.py), the name readout's confidence sat flat at 0.90-0.96 on
right and wrong answers alike (one isotonic knot, OOF AUROC 0.476 across 116
web_intent rows), while the reference letter readout on the SAME server
answered 5/5 varied tool questions and 4/4 noul questions with confidence
spreading 0.47-0.99 with the difficulty of the case. The Wave-2 "letters
collapse to a constant answer" finding came from the probe era of the
bytes[0]-as-id defect (see _extract_logprobs) and does not reproduce under
the correct format.

Pinned here: the renderers (coded options, yes/no criteria lines), the
manual im_start prompt, the /completion transport, the letter readout
(distinct single-token codes, space-form pooling, fail-closed), the readout
tag on the row-level engine identity, and the fail-closed refusal of an
undeclared consumer. OFFLINE and deterministic: the tokenizer is stubbed.
"""
from __future__ import annotations

from pathlib import Path

from backend.agent.decision_backend_d1 import D1Backend, _option_codes
from backend.agent import decision_engine as de

_BACKEND_SRC = Path("backend/agent/decision_backend_d1.py")


# ── the renderers ───────────────────────────────────────────────────────────

def test_choice_renders_coded_options_with_descriptions():
    """Each option renders as `{code} {text}`; the code carries the answer,
    the declared description carries the meaning (prompt.py _option_line,
    desc style)."""
    crit = {"pass": "The step did its part", "veto": "Must not run"}
    out = D1Backend._question_choice("a state", "Did it work?", crit,
                                     ["pass", "veto"])
    assert "A The step did its part" in out
    assert "B Must not run" in out
    assert "Reply with the option code only." in out
    assert "QUESTION:\nDid it work?" in out


def test_choice_renders_the_label_as_text_when_no_description():
    """No declared description: the label with underscores as spaces is the
    text (prompt.py: `desc or label.replace("_", " ")`)."""
    out = D1Backend._question_choice("s", "q", {}, ["read_file", "edit_file"])
    assert "A read file" in out
    assert "B edit file" in out


def test_noul_renders_the_yes_no_criteria_lines():
    """The declaration's true/false descriptions render as the reference's
    Yes:/No: lines — evidence the model was trained to read."""
    crit = {"true": "The task is finished", "false": "The task needs work"}
    out = D1Backend._question_noul("a state", "Is it done?", crit)
    assert "Is it done?" in out
    assert "Yes: The task is finished" in out
    assert "No: The task needs work" in out
    assert "Reply with yes or no only." in out


def test_noul_without_criteria_renders_the_bare_instruction():
    out = D1Backend._question_noul("a state", "Is it done?", None)
    assert "Yes:" not in out and "No:" not in out
    assert "Reply with yes or no only." in out


def test_state_block_matches_the_reference_newlines():
    """prompt.py state_block: a string renders as itself + TWO newlines, and
    QUESTION: follows directly (the retired shape added a third)."""
    out = D1Backend._question_noul("a state", "Is it done?")
    assert "a state\n\nQUESTION:\nIs it done?" in out


# ── the prompt wrapper and the transport ────────────────────────────────────

def test_the_prompt_is_the_manual_im_start_shape():
    """prompt.py prefix_text + suffix_text: BOS, user turn, im_end, assistant
    header — no chat template, no system turn."""
    got = D1Backend._decision_prompt("body text")
    assert got == ("<|startoftext|><|im_start|>user\nbody text"
                   "<|im_end|>\n<|im_start|>assistant\n")


def test_the_transport_is_raw_completion():
    src = _BACKEND_SRC.read_text(encoding="utf-8")
    assert "{_server_port()}/completion" in src
    # No POST to the chat route (the bare string stays in _extract_logprobs's
    # docstring, which documents BOTH llama.cpp response shapes it parses).
    assert "{_server_port()}/v1/chat/completions" not in src, (
        "the chat-completions transport applies the server's chat template - "
        "the reference builds its own markup")


def test_images_ride_the_completion_image_data_field():
    """The declared images become /completion image_data entries (base64),
    never content parts of a chat message."""
    src = _BACKEND_SRC.read_text(encoding="utf-8")
    assert '"image_data"' in src
    assert "_message_content" not in src, "the chat content-parts builder is gone"


# ── the letter readout ──────────────────────────────────────────────────────

def test_option_codes_follow_the_reference_rule():
    assert _option_codes(["A", "B"]) == ["A", "B"]  # native letters
    assert _option_codes(["read_file", "edit_file"]) == ["A", "B"]
    assert _option_codes([f"t{i}" for i in range(27)]) == [
        f"{i:02d}" for i in range(27)]


def _backend_with_tokenizer(monkeypatch, table):
    """Stub /tokenize: `table` maps form -> token id (None = multi-token)."""
    b = D1Backend()
    seen: dict = {}

    def fake_single(form):
        if form in table:
            return table[form]
        seen.setdefault(form, 0)
        seen[form] += 1
        return 1000 + len(seen)  # distinct single tokens for unknown forms

    monkeypatch.setattr(b, "_single_token_id", fake_single)
    return b


def test_letter_readout_pools_the_code_with_its_space_form(monkeypatch):
    b = _backend_with_tokenizer(monkeypatch, {"A": 10, " A": 11,
                                              "B": 12, " B": 13})
    got = b._letter_readout(["read_file", "edit_file"])
    assert got is not None
    plan, width = got
    assert width == 1, "the answer slot is ONE position"
    assert plan["read_file"] == ((10, 11),)
    assert plan["edit_file"] == ((12, 13),)


def test_letter_readout_falls_back_when_codes_collide(monkeypatch):
    """Two options whose codes tokenize to the SAME id: the fallback pool
    must separate them (reference aliases)."""
    b = _backend_with_tokenizer(monkeypatch, {"A": 10, " A": 10,
                                              "B": 10, " B": 10})
    got = b._letter_readout(["alpha", "beta"])
    assert got is not None
    plan, _ = got
    ids = {plan["alpha"][0][0], plan["beta"][0][0]}
    assert len(ids) == 2, "colliding codes must be separated by the pool"


def test_letter_readout_fails_closed_when_no_code_exists(monkeypatch):
    b = D1Backend()

    def always_none(form):
        return None

    monkeypatch.setattr(b, "_single_token_id", always_none)
    assert b._letter_readout(["alpha", "beta"]) is None


# ── the row-level identity carries the readout ─────────────────────────────

def test_model_id_carries_the_readout_tag():
    """The report scopes rows by this string: a readout change must
    re-identify the backend so old rows fail closed into other_backend
    instead of blending (AC25.8)."""
    b = D1Backend()
    assert b.model_id == f"{b.backend_id}+letters"
    assert de.CURRENT_READOUT_MODE == "letters"


# ── AC1.6: an undeclared consumer still scores nothing ─────────────────────

def test_undeclared_consumer_is_refused_before_scoring(monkeypatch):
    b = D1Backend()
    b._loaded = True
    monkeypatch.setattr(b, "_serves_d1", lambda force=False: (True, ""))
    assert b.decide("never_declared", ["a", "b"], {"goal": "x"}) is None
