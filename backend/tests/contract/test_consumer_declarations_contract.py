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
    # RESTORE (2026-10-10): the upgraded spec carries no labels, and the
    # registry is PROCESS-GLOBAL — leaving it mutated made 'done' vanish from
    # binary_consumers() for every later test in the same process (measured:
    # test_oracle_calibration_contract's binary-set test failed in group
    # runs, passed solo). Re-register the production shape so this test
    # leaves the registry as it found it. No assertion above is weakened.
    de.register_consumer_spec(de.ConsumerSpec(
        consumer_id="done", task_name="done",
        instruction="Is the objective complete?", labels=("yes", "no"),
    ))


# ── AC13.5: a dynamic consumer inherits its family ──────────────────────────

def test_event_type_inherits_its_family_declaration():
    assert de.declared_type("event_type:memory") == "choice"
    assert de.declared_type("event_type:anything_at_all") == "choice"


# ── the job-routing surface (T1.8, T1.9, AC10.7) ────────────────────────────

def test_dead_job_assignments_are_removed_and_the_new_ones_added():
    # STALE-BY-SPEC update (2026-10-11): `browser_next` was removed at T1.8
    # because it had NO call site; it returns WITH one (the node loop's
    # browser_act hook -> browser_next_shadow, test_browser_next_contract).
    # `web_depth` still has none and stays removed.
    assert de.CONSUMER_JOBS["browser_next"] == "route"
    assert "web_depth" not in de.CONSUMER_JOBS
    assert de.CONSUMER_JOBS["depth_route"] == "route"
    assert de.CONSUMER_JOBS["call_closing"] == "judge_call"
    assert de.CONSUMER_JOBS["tool_approval"] == "approve"
    # 19 - 2 dead + 1 new + 1 tool_approval - 1 mode (owner removal, 2026-10-10)
    # + 1 browser_next (2026-10-11, now with a call site)
    # - 1 use_thinking (owner removal, 2026-10-13)
    assert len(de.CONSUMER_JOBS) == 18
    assert "mode" not in de.CONSUMER_JOBS


def test_oracle_jobs_gained_only_the_call_closing_job():
    """AC10.7 gives `call_closing` its own job; tool_approval (2026-10-10) adds
    the `approve` job; the review-verdict frame fix (2026-10-16) adds
    `judge_review`. The prior jobs keep their names; fields/budgets evolve
    with the frame fixes (route gained `last_result` + evidence fields
    2026-10-10; approve widened to 384 for the v2 frame — the physical reason
    is stated in test_oracle_jobs_contract)."""
    # 11, not 10 (2026-10-16, review-verdict frame fix): review_verdict shared
    # `judge_step` with the ENFORCED `escalate_incomplete`, and judge_step's
    # 96-id budget (384 chars) cut "RECENT RESULTS" out of review_verdict's
    # 800-char frame — the completed steps' own results, the evidence its
    # question ("did this step do its part?") is about. A dedicated job raises
    # ONLY review_verdict's ceiling; escalate_incomplete keeps its input, its
    # identity and its threshold. The isolation is asserted here because it is
    # the whole reason the job is separate.
    # 12, not 11 (2026-10-17, depth_met/v3): depth_met gets its own
    # `judge_depth` job - judge_goal's 128-id budget (512 chars) cut its
    # EVIDENCE to almost nothing and its field order rendered the criteria
    # first. judge_depth declares evidence FIRST, then coverage, open_facts,
    # goal, at the 384-id owner ceiling; `grade` is deliberately absent (it is
    # the incumbent reference and must stay out of the input). done/sufficient
    # keep judge_goal, so their input is untouched - the same isolation
    # pattern judge_review set (2026-10-16).
    # 13, not 12 (2026-10-18, web_intent/v3): web_intent gets its own
    # `interpret_web` job - the interpret job's 64-id budget (256 chars) cut
    # 6 of 14 live goals behind an ~80-char Windows path prefix, leaving d1
    # reading a path instead of the request. 128 ids covers the longest
    # measured goal (347 chars). user_feedback keeps `interpret` (isolation,
    # the judge_review precedent).
    # 14, not 13 (2026-10-19, needs_action/v4): needs_action gets its own
    # `interpret_step` job. It used to share click_safety's `guard` job (goal
    # only); MEASURED on 294 real pairs, the goal alone leaves a write/edit
    # step ambiguous ("Write the slugify function to textutils.py" read as an
    # answer at p=0.11) and the step's EXPECTED OUTPUT resolves it.
    assert len(de.ORACLE_JOBS) == 14
    assert de.ORACLE_JOBS["interpret_web"].fields == ("goal",)
    assert de.ORACLE_JOBS["interpret_web"].budget_ids == 128
    assert de.CONSUMER_JOBS["web_intent"] == "interpret_web"
    assert de.ORACLE_JOBS["interpret_step"].fields == ("goal", "expected")
    assert de.ORACLE_JOBS["interpret_step"].budget_ids == 160
    assert de.CONSUMER_JOBS["needs_action"] == "interpret_step"
    assert de.CONSUMER_JOBS["user_feedback"] == "interpret"
    assert de.ORACLE_JOBS["judge_depth"].fields == (
        "evidence", "coverage", "open_facts", "goal")
    assert de.ORACLE_JOBS["judge_depth"].budget_ids == 384
    assert de.CONSUMER_JOBS["depth_met"] == "judge_depth"
    assert de.CONSUMER_JOBS["done"] == "judge_goal"
    assert de.CONSUMER_JOBS["sufficient"] == "judge_goal"
    assert de.ORACLE_JOBS["judge_review"].fields == ("goal",)
    # 288, not 200 (2026-10-17, review_verdict/v3): the v3 frame renders 3
    # ENVELOPE lines as evidence (each head+tail capped at 200 — the outcome
    # of a tool run lives at the TAIL of its output, so the v1 raw
    # result[:120] head cut threw the signal away; measured: constant verdict,
    # oof AUROC 0.5113 live, vs replay AUROC 1.0000 with envelope evidence).
    # 3 x 200 + STEP[:300] + TOOL + OBJECTIVE[:200] is ~1150 chars = 288 ids
    # x 4; at 200 ids/800 chars the cap cut the OBJECTIVE — the bar the review
    # rubric judges against. 384 stays the owner ceiling.
    assert de.ORACLE_JOBS["judge_review"].budget_ids == 288
    assert de.CONSUMER_JOBS["review_verdict"] == "judge_review"
    assert de.CONSUMER_JOBS["escalate_incomplete"] == "judge_step"
    assert de.ORACLE_JOBS["judge_step"].budget_ids == 96
    assert de.ORACLE_JOBS["judge_call"].fields == ("goal", "call", "result")
    # STALE-BY-SPEC update (2026-10-11, tool_approval/v3): `calls_this_step`
    # joins the approve job - the step's own calls were invisible (the frame
    # carried the previous STEP's result once per node). Budget unchanged.
    assert de.ORACLE_JOBS["approve"].fields == (
        "goal", "calls_this_step", "last_result", "proposed_tool",
        "tool_description", "args", "offered_tools")
    # 384, not 256 (2026-10-10, tool_approval/v2): the enriched frame
    # (goal 200 + last_result 400 + description 200 + args 400 + offered
    # names 200 chars) physically requires it — at 256 the cap cut the args,
    # the very evidence v2 exists to deliver. Widened for a physical reason,
    # stated here. 512 stays the absolute ceiling.
    assert max(j.budget_ids for j in de.ORACLE_JOBS.values()) <= 384


def test_consumers_grew_by_exactly_two():
    """STALE-BY-SPEC update (2026-10-10, owner): `mode` was REMOVED from the
    declared set — its incumbent is a free keyword rule, so enforcing it could
    never pay, and its AUROC fell below the bar at volume (0.591 at 77 rows).
    The removal is complete (CONSUMERS, CONSUMER_DECLARATIONS, CONSUMER_JOBS,
    the scoring site and its tests all changed in the SAME commit), so the
    declared set is not left half-changed.

    STALE-BY-SPEC update (2026-10-18, owner: "address tool_approval pre-call
    guard so it can be flipped"): `tool_approval` JOINED the declared set - it
    earned the hardened bar on the v6 cohort (433 rows, oof AUROC 0.7313, ECE
    0.0398, precision@t 0.9034) and its live decision exists (the pre-call
    guard in node_executor). TIER_REFUSE_ONLY: it may only reject a call, and
    its correction budget bounds it."""
    assert set(de.CONSUMERS) - _PRIOR_CONSUMERS == {
        "depth_route", "call_closing", "tool_approval"}
    # owner-directed removals: `mode` (2026-10-10) and `use_thinking` (2026-10-13)
    assert _PRIOR_CONSUMERS - set(de.CONSUMERS) == {"mode", "use_thinking"}
    assert "tool_approval" in de.TIER_REFUSE_ONLY
