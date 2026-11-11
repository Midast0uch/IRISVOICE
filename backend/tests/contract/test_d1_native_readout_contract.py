"""The d1 readout — the NATIVE Decision Index API (2026-11-01).

WHY THIS FILE EXISTS

d1 is a post-trained decision model: one state is read once and typed
questions are answered in ONE forward pass with zero generated tokens.

For d1-3B there was no server support for that API, so this backend rebuilt the
trained prompt by hand (LiquidAI/d1-3B prompt.py: coded options + letter-token
readout over ``/completion``). d1-2B ships the template in its GGUF
(``tokenizer.chat_template.systemone``) and llama.cpp serves it at
``POST /v1/systemone``, applying the model's per-type logit temperature
(``lfm3.decision.temperature.*`` = 1.3374 for d1-2B). The hand-built prompt is
retired: it missed d1-2B's trailing ``<think></think>`` and its temperature, so
its confidence was not the model's calibrated confidence.

Pinned here: the native request shape (state + typed questions), the criteria
mapping for each declared type, the answer mapping into the engine's
DecisionScore envelope, the image field, the fail-closed paths, the readout
tag on the row-level engine identity, and the shared d1 build test.

OFFLINE and deterministic: the HTTP client is stubbed.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from backend.agent import decision_backend_d1 as d1mod
from backend.agent.decision_backend_d1 import D1Backend, is_d1_build
from backend.agent.decision_engine import OracleState
from backend.agent import decision_engine as de

SERVED = r"D:\models\LiquidAI\d1-2B-GGUF\d1-2B-Q4_K_M.gguf"


class _Resp:
    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body or {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """A pooled-client stand-in: records every POST, answers from a map."""

    def __init__(self, answers=None, status: int = 200,
                 modalities=("text", "decisions")) -> None:
        self.answers = answers or {}
        self.status = status
        self.modalities = list(modalities)
        self.posts: list[tuple[str, dict]] = []

    def get(self, url, timeout=None):
        model = {
            "id": SERVED,
            "architecture": {"output_modalities": self.modalities},
        }
        return _Resp(200, {"data": [model]})

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json or {}))
        if self.status != 200:
            return _Resp(self.status, {})
        return _Resp(200, {"answers": self.answers})


@pytest.fixture()
def wire(monkeypatch):
    """Install a fake client and hand back (backend, client)."""
    def _install(answers=None, status: int = 200, modalities=("text", "decisions")):
        client = _Client(answers=answers, status=status, modalities=modalities)
        monkeypatch.setattr(d1mod, "_pooled", lambda: client)
        return D1Backend(), client

    return _install


# ── the build test ──────────────────────────────────────────────────────────

def test_the_served_build_is_recognised_by_token():
    """One shared test for every site that must accept the live d1 release:
    main.py's boot refusal, the backend's /v1/models check, the server cmd and
    the eval preflight all read this."""
    assert is_d1_build(SERVED)
    assert is_d1_build(r"C:\models\d1-3B-AD-Q4_K_M.gguf")
    assert not is_d1_build(r"C:\models\LFM2.5-2.6B-Q4_K_M.gguf")
    assert not is_d1_build("")


# ── the request ────────────────────────────────────────────────────────────

def test_choice_sends_one_typed_question_with_the_menu_descriptions(wire):
    """A choice question carries label -> description (the per-turn menu
    text), the consumer's instruction, and the state once."""
    b, client = wire({"q": {
        "type": "choice", "choice": "read_file",
        "probabilities": {"read_file": 0.9, "NONE": 0.1}, "confidence": 0.9,
    }})
    state = OracleState(
        job="route", fields=("goal",), text="goal: read the engine",
        budget_ids=384,
        option_criteria=(("read_file", "Read a file not read in this step"),
                         ("NONE", "No tool")),
    )
    got = b.decide("tool_choice", ["read_file", "NONE"], state)
    assert got is not None
    url, body = client.posts[-1]
    assert url.endswith("/v1/systemone")
    assert body["state"] == "goal: read the engine"
    q = body["questions"]["q"]
    assert q["type"] == "choice"
    assert q["criteria"] == {
        "read_file": "Read a file not read in this step", "NONE": "No tool"}
    assert q["instructions"]


def test_choice_without_descriptions_falls_back_to_the_label_text(wire):
    b, client = wire({"q": {
        "type": "choice", "choice": "edit_file",
        "probabilities": {"edit_file": 0.8, "read_file": 0.2},
        "confidence": 0.8,
    }})
    b.decide("tool_choice", ["read_file", "edit_file"], {"goal": "g"})
    q = client.posts[-1][1]["questions"]["q"]
    assert q["criteria"] == {"read_file": "read file", "edit_file": "edit file"}


def test_a_long_option_description_is_capped_but_the_name_is_not(wire):
    """The native API generates ZERO tokens, so the decision latency is the
    prefill of the prompt the server renders. The criteria block is the bulk
    of it: the 27-tool menu was 1619 tokens / 177 ms with the full tool
    documentation and 703 tokens / 82 ms with each option's text capped
    (measured 2026-11-01, RTX 3070).

    The cap is on the TEXT only. The option NAME is never shortened, so the
    answer still names a real option. The cap also IMPROVES the pick: with
    the full documentation the model chose a self-improvement tool for 13 of
    30 research tasks; capped it chose the research tool (family-correct
    29/30 against 17/30)."""
    b, client = wire({"q": {
        "type": "choice", "choice": "read_file",
        "probabilities": {"read_file": 0.9, "NONE": 0.1}, "confidence": 0.9,
    }})
    long_text = "Locate a GUI element on the user's LIVE SCREEN by description. " \
                "ONLY use when the task requires SEEING what is on the screen. " \
                "Do NOT use it to retrieve data that earlier steps collected."
    state = OracleState(
        job="route", fields=("goal",), text="goal: read the engine",
        budget_ids=384,
        option_criteria=(("read_file", long_text), ("NONE", "No tool")),
    )
    b.decide("tool_choice", ["read_file", "NONE"], state)
    q = client.posts[-1][1]["questions"]["q"]
    text = q["criteria"]["read_file"]
    assert len(text) <= 120, "the option text must be capped (%d chars)" % len(text)
    assert text.endswith("…")
    assert "read_file" in q["criteria"], "the option NAME is never shortened"
    assert long_text[:40] in text, "the cap keeps the FIRST part of the text"


def test_noul_sends_only_the_declared_yes_no_text(wire):
    """The call site owns the question (the example was needs_action, retired 2026-11-10); the
    declaration owns the Yes:/No: descriptions. The server's template adds
    the prefixes, so ours must be stripped."""
    b, client = wire({"q": {"type": "noul", "noul": 0.7}})
    instruction = (
        "Does this step take an ACTION in the project - read, write, edit, "
        "create, implement, fix, run, search or browse - or does it only give "
        "an ANSWER from what is already known?"
    )
    b.decide("done", ["yes", "no"], {"goal": "Read main.py"},
             instruction=instruction)
    q = client.posts[-1][1]["questions"]["q"]
    assert q["type"] == "noul"
    assert q["instructions"] == instruction
    assert set(q["criteria"]) == {"true", "false"}
    for text in q["criteria"].values():
        assert not text.lower().startswith(("yes:", "no:")), text


def test_images_ride_the_images_field_as_data_uris(wire):
    b, client = wire({"q": {
        "type": "choice", "choice": "safe",
        "probabilities": {"safe": 0.95, "unsafe": 0.05}, "confidence": 0.95,
    }})
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    frame = OracleState(job="guard", fields=("goal",), text="goal: click",
                        budget_ids=128, images=(png,))
    b.decide("click_safety", ["safe", "unsafe"], frame)
    body = client.posts[-1][1]
    assert body["images"] == [
        "data:image/png;base64," + base64.b64encode(png).decode("ascii")]


# ── the answer mapping ─────────────────────────────────────────────────────

def test_choice_answer_becomes_a_distribution_in_menu_order(wire):
    b, _ = wire({"q": {
        "type": "choice", "choice": "B",
        "probabilities": {"A": 0.25, "B": 0.6, "C": 0.15}, "confidence": 0.6,
    }})
    got = b.decide("tool_choice", ["A", "B", "C"], {"goal": "g"})
    assert got.consumer_id == "tool_choice"
    assert got.chosen == "B"
    assert got.confidence == pytest.approx(0.6)
    assert [c.name for c in got.distribution] == ["A", "B", "C"]
    assert [c.prob for c in got.distribution] == pytest.approx([0.25, 0.6, 0.15])
    assert got.engine_latency_ms is not None


def test_noul_answer_keeps_p_true_as_the_yes_probability(wire):
    """The engine reads P(true) by NAME from the distribution: a noul row
    stores the chosen answer's confidence, and the raw P(true) stays on the
    'yes' candidate."""
    b, _ = wire({"q": {"type": "noul", "noul": 0.2}})
    got = b.decide("done", ["yes", "no"], {"goal": "g"})
    assert got.chosen == "no"
    assert got.confidence == pytest.approx(0.8)
    by_name = {c.name: c.prob for c in got.distribution}
    assert by_name["yes"] == pytest.approx(0.2)
    assert by_name["no"] == pytest.approx(0.8)


def test_score_answer_maps_its_levels(wire):
    """No consumer declares `score` today; the mapping is pinned against the
    live answer shape (digits keyed into probabilities, a float median)."""
    got = D1Backend._score_from_answer(
        "any", "score", ["low", "medium", "high"],
        {"type": "score", "score": 1.0,
         "legend": {"0": "low", "1": "medium", "2": "high"},
         "probabilities": {"0": 0.2, "1": 0.7, "2": 0.1},
         "confidence": 0.7},
        12,
    )
    assert got.chosen == "medium"
    assert got.confidence == pytest.approx(0.7)
    assert [c.prob for c in got.distribution] == pytest.approx([0.2, 0.7, 0.1])


# ── fail-closed paths ──────────────────────────────────────────────────────

def test_undeclared_consumer_is_refused_before_any_request(wire):
    b, client = wire({"q": {"type": "noul", "noul": 0.9}})
    assert b.decide("never_declared", ["yes", "no"], {"goal": "g"}) is None
    assert client.posts == []


def test_a_noul_consumer_offered_a_non_binary_pair_is_refused(wire):
    b, client = wire({"q": {"type": "noul", "noul": 0.9}})
    assert b.decide("done", ["yes", "maybe"], {"goal": "g"}) is None
    assert client.posts == []


def test_a_missing_native_endpoint_fails_closed(wire):
    b, client = wire(status=404)
    assert b.decide("tool_choice", ["A", "B"], {"goal": "g"}) is None
    assert client.posts, "the call must have been attempted"


def test_a_malformed_answer_fails_closed(wire):
    b, _ = wire({"q": {"type": "choice", "choice": "A"}})
    assert b.decide("tool_choice", ["A", "B"], {"goal": "g"}) is None


def test_a_build_without_decision_metadata_is_not_served(wire):
    """d1-3B has no Decision Index metadata: /v1/systemone answers 501 for it.
    The availability check refuses it up front instead of hiding the cause."""
    b, client = wire(modalities=("text",))
    assert b.decide("tool_choice", ["A", "B"], {"goal": "g"}) is None
    assert client.posts == []


# ── the identity and the batch seam ────────────────────────────────────────

def test_the_row_identity_names_the_native_readout(wire):
    b, _ = wire({"q": {"type": "noul", "noul": 0.9}})
    assert b.load()
    assert b.backend_id == "d1-2b-q4_k_m"
    assert b.model_id == "d1-2b-q4_k_m+systemone"
    assert de.CURRENT_READOUT_MODE == "systemone"


def test_batch_answers_each_question_at_its_own_key(wire):
    b, client = wire({
        "q0": {"type": "noul", "noul": 0.9},
        "q1": {"type": "choice", "choice": "B",
               "probabilities": {"A": 0.1, "B": 0.9}, "confidence": 0.9},
    })
    out = b.decide_batch("shared state", [
        ("done", ["yes", "no"], "Does it act?"),
        ("tool_choice", ["A", "B"], "Which?"),
    ])
    assert len(out) == 2
    assert out[0].chosen == "yes"
    assert out[1].chosen == "B"
    body = client.posts[-1][1]
    assert body["state"] == "shared state"
    assert set(body["questions"]) == {"q0", "q1"}
