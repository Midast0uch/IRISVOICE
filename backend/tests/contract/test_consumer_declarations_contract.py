"""REQ-4 (specs/oracle-native-decision-surface): the decision type is DECLARED.

d1's two answer shapes have different readouts, so the type is a property of the
DECISION POINT, never inferred. The `len(options) == 2` heuristic is deleted
(AC4.3), and a consumer with no declared type scores NOTHING rather than
borrowing a shape or getting a generic fallback (AC1.6).
"""
from __future__ import annotations

from pathlib import Path

from backend.agent import decision_engine as de
from backend.agent.decision_backend_d1 import D1Backend

_D1_BACKEND = Path("backend/agent/decision_backend_d1.py")

# The consumer set before this spec: 13 entries. This spec adds exactly two
# (AC9.1 sanctioned exceptions 2 and 3) and removes none.
_PRIOR_CONSUMERS = {
    "tool_choice", "presentation", "narration", "recovery_strategy",
    "review_verdict", "sufficient", "done", "mode", "web_intent",
    "use_thinking", "escalate_incomplete", "needs_action", "depth_met",
}


# ── AC4.1/AC4.2: the declaration table ──────────────────────────────────────

def test_every_declared_consumer_has_a_valid_type():
    for cid, decl in de.CONSUMER_DECLARATIONS.items():
        assert decl.decision_type in de.DECISION_TYPES, cid


def test_criteria_match_the_declared_type():
    """AC4.2: choice -> name->description; noul -> names each side."""
    for cid, decl in de.CONSUMER_DECLARATIONS.items():
        if not decl.criteria:
            continue  # a dynamic menu has no static name set (by design)
        if decl.decision_type == "choice":
            assert isinstance(decl.criteria, dict), cid
        elif decl.decision_type == "noul":
            assert set(decl.criteria) == {"true", "false"}, cid


def test_the_documented_noul_consumers_are_noul():
    """AC4.4: `sufficient`, `done` and `depth_met` are documented noul
    (oracle.md AC14.6)."""
    for cid in ("sufficient", "done", "depth_met"):
        assert de.declared_type(cid) == "noul", cid


def test_click_safety_is_declared_from_the_code_not_the_prose():
    """REQ-5's prose calls it a "yes/no safety question"; the consumer AS WIRED
    passes three labels (`safe`/`unsafe`/`unsure`), so a noul declaration would
    misread its own readout. Declared choice, matching the code."""
    from backend.agent.click_safety_shadow import LABELS

    assert de.declared_type("click_safety") == "choice"
    assert set(de.CONSUMER_DECLARATIONS["click_safety"].criteria) == set(LABELS)


def test_review_verdict_carries_the_quality_bar():
    """T4.3/B3: the incumbent said pass 96% of the time because the question was
    under-specified. `refine` must be reachable on vague/incomplete/wrong-tool
    steps, not only on outright conflicts."""
    crit = de.CONSUMER_DECLARATIONS["review_verdict"].criteria
    assert set(crit) == {"pass", "refine", "veto"}
    assert "vague" in crit["refine"] and "incomplete" in crit["refine"]


# ── AC4.3/AC4.5: the heuristic is gone, the score type exists ───────────────

def test_the_inference_heuristic_is_deleted():
    src = _D1_BACKEND.read_text(encoding="utf-8")
    assert "_is_noul" not in src, (
        "the `len(opts) == 2 and opts <= {yes,no}` heuristic must be DELETED "
        "(AC4.3); the type comes from the declaration"
    )


def test_score_exists_in_the_schema_and_the_renderer():
    """AC4.5: no consumer is promoted to `score` in this wave, but the type must
    exist so an ordered-level question has a home."""
    assert "score" in de.DECISION_TYPES
    out = D1Backend._question_score("a state", "How deep is this?", ["shallow", "deep"])
    assert "shallow" in out and "deep" in out


# ── AC1.6: undeclared scores nothing ────────────────────────────────────────

def test_undeclared_consumer_scores_nothing(monkeypatch):
    """AC1.6: no inherited shape, no generic fallback. The backend refuses
    BEFORE any HTTP call, so a dead client is enough to prove it."""
    b = D1Backend()
    b._loaded = True
    monkeypatch.setattr(b, "_serves_d1", lambda force=False: (True, ""))
    assert b.decide("totally_new_thing", ["alpha", "beta"], {"goal": "x"}) is None
    assert de.is_declared("totally_new_thing") is False


def test_an_undeclared_spec_does_not_borrow_a_type():
    de.register_consumer_spec(de.ConsumerSpec(
        consumer_id="another_new_thing", task_name="x", instruction="?",
    ))
    spec = de.get_consumer_spec("another_new_thing")
    assert spec.decision_type == ""
    assert de.declared_type("another_new_thing") == ""


# ── AC13.4: a pre-REQ-4 spec is UPGRADED, not kept ──────────────────────────

def test_a_pre_req4_spec_is_upgraded():
    """The register functions are idempotent, so an already-registered consumer
    would otherwise keep its pre-REQ-4 shape forever: the change would work in
    tests (fresh registry) and never take effect in production (warm registry)."""
    de.register_consumer_spec(de.ConsumerSpec(
        consumer_id="done", task_name="done", instruction="old", labels=("yes", "no"),
    ))
    assert de.get_consumer_spec("done").decision_type == ""
    assert de.needs_upgrade(de.get_consumer_spec("done")) is True

    upgraded = de.ensure_consumer_spec("done", ["yes", "no"], "Is it done?")
    assert upgraded.decision_type == "noul"
    assert de.needs_upgrade(de.get_consumer_spec("done")) is False


# ── AC13.5: a dynamic consumer inherits its family ──────────────────────────

def test_event_type_inherits_its_family_declaration():
    assert de.declared_type("event_type:memory") == "choice"
    assert de.declared_type("event_type:anything_at_all") == "choice"


# ── the job-routing surface (T1.8, T1.9, AC10.7) ────────────────────────────

def test_dead_job_assignments_are_removed_and_the_new_ones_added():
    assert "browser_next" not in de.CONSUMER_JOBS
    assert "web_depth" not in de.CONSUMER_JOBS
    assert de.CONSUMER_JOBS["depth_route"] == "route"
    assert de.CONSUMER_JOBS["call_closing"] == "judge_call"
    assert len(de.CONSUMER_JOBS) == 18   # 19 - 2 dead + 1 new


def test_oracle_jobs_gained_only_the_call_closing_job():
    """AC10.7 gives `call_closing` its own job. The eight prior jobs keep their
    names, fields and budgets."""
    assert len(de.ORACLE_JOBS) == 9
    assert de.ORACLE_JOBS["judge_call"].fields == ("goal", "call", "result")
    assert max(j.budget_ids for j in de.ORACLE_JOBS.values()) <= 128


def test_consumers_grew_by_exactly_two():
    assert set(de.CONSUMERS) - _PRIOR_CONSUMERS == {"depth_route", "call_closing"}
    assert _PRIOR_CONSUMERS - set(de.CONSUMERS) == set()   # nothing removed
