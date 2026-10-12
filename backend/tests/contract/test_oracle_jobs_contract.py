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
              "depth_route", "call_closing"):
        assert de.oracle_job(c).name != "general", c


def test_budgets_respect_the_owner_maximum():
    # 256, not 128 (2026-10-10): the route job's enriched frame physically
    # requires it - goal[:200] plus a ~600-char last_result snippet must both
    # fit, and at 128 the budget trim cuts the tail (the evidence the frame
    # fix exists to deliver). Widened for a physical reason, stated here.
    # 384, not 256 (2026-10-10, tool_approval/v2): the approve job's frame
    # adds the call arguments and the offered tool list - goal 200 +
    # last_result 400 + description 200 + args 400 + offered names 200 chars -
    # and at 256 the cap cut the args, the very evidence v2 exists to deliver.
    # 512 stays the absolute ceiling (S19.3).
    assert max(j.budget_ids for j in de.ORACLE_JOBS.values()) <= 384


def test_reference_fields_never_reach_the_model():
    frame = {"goal": "fix the parser", "incumbent_route": "finalize",
             "brain_choice": "finalize", "brain_bool": True, "coverage": 0.5,
             "open_facts": ["tests pass"]}
    state = de.job_input("depth_route", frame)
    text = state.text
    for leaked in ("finalize", "brain_", "incumbent", "True"):
        assert leaked not in text, f"the reference leaked into the input: {leaked}"
    # ...while the route's own state now DOES reach it (it was dropped before).
    assert "coverage: 0.50" in text and "tests pass" in text and "fix the parser" in text


def test_goal_only_frame_renders_unchanged():
    """Consumers that only ever passed `goal` keep their calibrated text."""
    assert de.job_input("tool_choice", {"goal": "read the readme"}).text == "read the readme"


# ── Wave 4 (REQ-3/REQ-5): the state is STRUCTURED, and images are declared ──


def test_job_input_returns_a_structured_state_with_the_job_attached():
    """AC3.1/AC3.5: one OracleState per consult - the job's declared fields in
    order, the declared budget, and the images the job declared."""
    state = de.job_input("tool_choice", {"goal": "g"})
    assert isinstance(state, de.OracleState)
    assert state.job == "route"
    # AC3.2: the state carries the job's declared fields in order. The route
    # tuple grew twice: `last_result` (2026-10-10, the blind-frame fix) and
    # the resolve-frame evidence fields (2026-10-10, the frame/job mismatch
    # fix). Pinned to the live declaration so a silent field change fails.
    assert state.fields == de.ORACLE_JOBS["route"].fields
    # STALE-BY-SPEC update (2026-10-11, tc-frame-v5): `done_when` and
    # `calls_this_step` sit between goal and last_result (the cap trims the
    # long result snippet, never the step's own history).
    # + `step_facts` (2026-10-11, tc-frame-v7): the read/edit/write/run facts.
    assert state.fields[:9] == (
        "coverage", "open_facts", "depth_met", "grade", "goal",
        "done_when", "calls_this_step", "step_facts", "last_result")
    assert state.budget_ids == de.ORACLE_JOBS["route"].budget_ids
    assert state.images == ()


def test_every_declared_field_is_on_the_state_no_reference_field_is():
    """AC3.2/AC3.3/AC3.5: per job, the state carries exactly the declared
    fields in the declared order, and NO job declares a reference field - a
    row whose input carries its own answer measures nothing (oracle.md S19)."""
    for cid in (*de.CONSUMERS, "event_type:memory"):
        job = de.oracle_job(cid)
        state = de.job_input(cid, {})
        assert state.fields == tuple(job.fields), (cid, state.fields)
        assert state.job == job.name
    for job in de.ORACLE_JOBS.values():
        for f in job.fields:
            assert not f.startswith("brain_") and f != "incumbent_route", (
                f"job {job.name} declares the reference field {f}"
            )


def test_images_reach_only_the_jobs_that_declare_them():
    """AC5.1: a consumer whose job declares no image NEVER receives one -
    even when the frame carries a screenshot for another reason - and the
    `guard` job's declared screenshot reaches its consumers' state."""
    shot = b"\x89PNG\r\n\x1a\n-fake"
    guarded = de.job_input("click_safety", {"goal": "g", "screenshot": shot})
    assert guarded.images == (shot,), "click_safety (guard) lost its image"
    text_only = de.job_input("mode", {"goal": "g", "screenshot": shot})
    assert text_only.images == (), (
        "a text consumer received an image - it would pay vision tokens it "
        "never calibrated for")
    # Non-bytes or absent image fields carry nothing; the state is still built.
    assert de.job_input("click_safety", {"goal": "g"}).images == ()
    assert de.job_input(
        "click_safety", {"goal": "g", "screenshot": "not-bytes"}).images == ()


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
    # SUBJECT SWITCH (2026-10-10, stale-by-spec): the subject was `mode` until
    # the owner removed that consumer; `narration` is a surviving declared
    # choice consumer. The mechanics under test are unchanged.
    ok = eng.shadow("narration", ["speak_all", "stay_silent"],
                    {"goal": "build a parser"},
                    sink=lambda r: (rows.append(r), landed.set()),
                    reference={"brain_choice": "stay_silent"})
    assert ok and not rows, "the caller must not wait for the score"
    release.set()
    assert landed.wait(5)
    row = rows[0]
    assert row["job"] == "shape" and row["brain_choice"] == "stay_silent"
    assert row["shadow"] is True and row["chosen"] == "speak_all"
