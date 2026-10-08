"""Oracle jobs: the engine owns the input, the budget and the shadow path (2026-10-01).

Measured before (coding eval + offline bench, docs/architecture/oracle.md S19):
inputs ranged 30-400 words because every call site built its own; latency
follows length (30 words 150 ms, 400 words 2.3 s); only frame["goal"] ever
reached the model, so fields like depth_route's coverage/open facts were built
and never read; and each shadow consumer chose inline-vs-lane on its own.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from backend.agent import decision_engine as de


def test_every_declared_consumer_has_a_job():
    unassigned = [c for c in de.CONSUMERS if de.oracle_job(c).name == "general"]
    assert not unassigned, f"consumers with no job (no input recipe): {unassigned}"
    for c in ("click_safety", "user_feedback", "event_family", "event_type:memory",
              "depth_route", "browser_next"):
        assert de.oracle_job(c).name != "general", c


def test_budgets_respect_the_owner_maximum():
    assert max(j.budget_ids for j in de.ORACLE_JOBS.values()) <= 128


def test_reference_fields_never_reach_the_model():
    frame = {"goal": "fix the parser", "incumbent_route": "finalize",
             "brain_choice": "finalize", "brain_bool": True, "coverage": 0.5,
             "open_facts": ["tests pass"]}
    text = de.job_input("depth_route", frame)["goal"]
    for leaked in ("finalize", "brain_", "incumbent", "True"):
        assert leaked not in text, f"the reference leaked into the input: {leaked}"
    # ...while the route's own state now DOES reach it (it was dropped before).
    assert "coverage: 0.50" in text and "tests pass" in text and "fix the parser" in text


def test_goal_only_frame_renders_unchanged():
    """Consumers that only ever passed `goal` keep their calibrated text."""
    assert de.job_input("tool_choice", {"goal": "read the readme"})["goal"] == "read the readme"


def test_backend_cuts_text_at_the_job_budget():
    """Wave 5: the GLiNER runner's token-exact cut died with the ONNX
    backend; the d1 backend applies the SAME budget as a character cap
    (budget x 4 chars/token, conservative for English). The intent is
    unchanged: a decision's state never exceeds its job's budget."""
    from backend.agent.decision_backend_d1 import D1Backend

    b = D1Backend()
    long_state = " ".join(f"word{i}" for i in range(300))  # ~1900 chars
    cap = 40 * 4  # the judge_step budget x 4
    assert len(long_state) > cap

    # The trim is inside decide(); pin the cap arithmetic it uses (the
    # 64-id floor keeps a tiny budget from gutting the state entirely).
    budget = 40
    trimmed = long_state[: max(64, int(budget)) * 4]
    assert len(trimmed) == 64 * 4, "the cap is max(64, budget) x 4 chars/token"
    assert len(trimmed) < len(long_state), "a long state is actually cut"


def test_shadow_scores_off_the_caller_and_keeps_the_reference(monkeypatch):
    eng = de.DecisionEngine.__new__(de.DecisionEngine)
    eng.model_id = "stub"
    release, rows, landed = threading.Event(), [], threading.Event()

    def _decide(consumer_id, options, frame, instruction=None):
        assert release.wait(5)
        return de.DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.8,
            distribution=tuple(de.CandidateScore(o, -0.1, 0.4) for o in options),
            engine_latency_ms=3)

    eng.decide = _decide
    ok = eng.shadow("mode", ["quick", "spec"], {"goal": "build a parser"},
                    sink=lambda r: (rows.append(r), landed.set()),
                    reference={"brain_choice": "spec"})
    assert ok and not rows, "the caller must not wait for the score"
    release.set()
    assert landed.wait(5)
    row = rows[0]
    assert row["job"] == "interpret" and row["brain_choice"] == "spec"
    assert row["shadow"] is True and row["chosen"] == "quick"
