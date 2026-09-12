"""Unit tests: goal-contract pure core (specs/goal-contract-coverage T12).

Pure logic only — no I/O, no LLM, no DB. Covers: extract_required
determinism + fallback + cap + dedupe (REQ-1 AC1.1/AC1.5/AC1.6), map_to_steps
omission (AC1.2/AC1.3), mark_coverage set-union + VERIFIED-term rule + weak
check + degenerate (REQ-2 AC2.1-AC2.5), progress_ratio no-progress vs
slow-progress (REQ-3 AC3.4), amend floor protection + shrink/grow (REQ-4),
add_ceiling cap + floor-dedupe (REQ-4 AC4.2), is_blocked vocabulary incl.
APPROVAL_UNAVAILABLE (REQ-9 AC9.2), parse_steering_amendment remove/add/
repromote/noise (REQ-4 AC4.1).
"""
from __future__ import annotations

from backend.agent import goal_contract as gc
from backend.agent.goal_contract import Contract


# ── extract_required (REQ-1 AC1.1/AC1.5/AC1.6) ──────────────────────────────


def test_extract_deterministic_same_input_same_output():
    req = "1. compare Bun vs Deno 2. list three features"
    assert gc.extract_required(req) == gc.extract_required(req)


def test_extract_enumerated_and_count_facts():
    facts = gc.extract_required(
        "1. compare Bun vs Deno\n2. list three features\n3. give install steps"
    )
    assert len(facts) == 3


def test_extract_fallback_single_fact_for_plain_request():
    facts = gc.extract_required("summarize the situation")
    assert facts == ("summarize the situation",)


def test_extract_empty_request_fallback():
    assert gc.extract_required("") == ("",)
    assert gc.extract_required("   ") == ("",)


def test_extract_dedupes_normalized_text():
    facts = gc.extract_required("List three features; list THREE features")
    assert len(facts) == 1


def test_extract_caps_at_required_cap():
    from backend.agent import der_constants as dc

    many = "\n".join(f"{i}. deliverable number {i} for the report" for i in range(1, 40))
    facts = gc.extract_required(many)
    assert len(facts) == dc.GOAL_REQUIRED_FACTS_CAP


# ── map_to_steps (REQ-1 AC1.2/AC1.3) ────────────────────────────────────────


def test_map_to_steps_returns_omitted_facts():
    facts = ("compare Bun vs Deno", "list three features")
    steps = [{"expected_output": "A Bun vs Deno comparison table"}]
    assert gc.map_to_steps(facts, steps) == ("list three features",)


def test_map_to_steps_empty_when_all_mapped():
    facts = ("compare Bun vs Deno",)
    steps = [{"expected_output": "compare Bun vs Deno in depth"}]
    assert gc.map_to_steps(facts, steps) == ()


def test_map_to_steps_handles_object_and_string_steps():
    class Step:
        expected_output = "install steps for Bun here"

    facts = ("install steps for Bun", "compare Bun vs Deno")
    assert gc.map_to_steps(facts, [Step(), "unrelated text"]) == (
        "compare Bun vs Deno",
    )


# ── mark_coverage (REQ-2 AC2.1-AC2.5) ───────────────────────────────────────


def test_mark_coverage_set_union_counts_once():
    c = Contract(required=("compare Bun vs Deno",))
    cov = gc.mark_coverage(
        c,
        ["VERIFIED", "VERIFIED"],
        ["Bun vs Deno comparison part one", "Bun vs Deno comparison part two"],
    )
    assert cov.covered == ("compare Bun vs Deno",)
    assert cov.C == 1.0
    assert cov.g == 0.0


def test_mark_coverage_requires_verified_and_terms():
    c = Contract(required=("compare Bun vs Deno",))
    cov = gc.mark_coverage(c, ["UNVERIFIED"], ["Bun vs Deno comparison"])
    assert cov.C == 0.0
    cov2 = gc.mark_coverage(c, ["VERIFIED"], ["unrelated weather text"])
    assert cov2.C == 0.0


def test_mark_coverage_partial_fraction():
    c = Contract(required=("compare Bun vs Deno", "list three features"))
    cov = gc.mark_coverage(
        c, ["VERIFIED", "FAILED"], ["Bun vs Deno comparison", "nothing useful"]
    )
    assert cov.C == 0.5
    assert cov.g == 0.5
    assert cov.required_n == 2


def test_mark_coverage_empty_result_never_covers():
    c = Contract(required=("compare Bun vs Deno",))
    assert gc.mark_coverage(c, ["VERIFIED"], [""]).C == 0.0


def test_mark_coverage_degenerate_empty_required_is_one():
    cov = gc.mark_coverage(Contract(required=()), [], [])
    assert cov.C == 1.0


# ── progress_ratio (REQ-3 AC3.4) ────────────────────────────────────────────


def test_progress_ratio_no_progress_is_zero():
    assert gc.progress_ratio(0.5, 0.5, 0.5, 1000.0) == 0.0


def test_progress_ratio_slow_but_progressing_stays_positive():
    rho = gc.progress_ratio(0.4, 0.5, 0.6, 2000.0)
    assert rho > 0.0


def test_progress_ratio_degenerate_inputs_zero():
    assert gc.progress_ratio(0.0, 0.5, 0.0, 100.0) == 0.0
    assert gc.progress_ratio(0.0, 0.5, 0.5, 0.0) == 0.0


# ── amend floor protection (REQ-4) ──────────────────────────────────────────


def test_amend_agent_floor_removal_refused():
    c = Contract(required=("compare Bun vs Deno",))
    assert gc.amend(c, remove=("compare Bun vs Deno",), source="agent") is c


def test_amend_agent_floor_add_refused():
    c = Contract(required=("compare Bun vs Deno",))
    assert gc.amend(c, add=("sneaky new floor fact",), source="agent") is c


def test_amend_user_remove_shrinks_and_raises_c():
    c = Contract(required=("compare Bun vs Deno", "list three features"))
    n = gc.amend(c, remove=("compare Bun vs Deno",), source="user", reason="t")
    assert n.required == ("list three features",)
    assert n.version == c.version + 1
    before = gc.mark_coverage(c, ["VERIFIED"], ["three features here"]).C
    after = gc.mark_coverage(n, ["VERIFIED"], ["three features here"]).C
    assert after > before


def test_amend_user_add_grows_and_lowers_c():
    c = Contract(required=("list three features",))
    n = gc.amend(c, add=("compare Bun vs Deno",), source="user", reason="t")
    assert len(n.required) == 2
    assert n.version == c.version + 1
    before = gc.mark_coverage(c, ["VERIFIED"], ["three features here"]).C
    after = gc.mark_coverage(n, ["VERIFIED"], ["three features here"]).C
    assert after < before


def test_amend_identity_preserved_noop_returns_same():
    c = Contract(required=("compare Bun vs Deno",))
    assert gc.amend(c, source="user") is c


# ── add_ceiling (REQ-4 AC4.2) ───────────────────────────────────────────────


def test_add_ceiling_capped_and_floor_deduped():
    from backend.agent import der_constants as dc

    c = Contract(required=("compare Bun vs Deno",))
    n = gc.add_ceiling(c, ["compare Bun vs Deno"])
    assert n is c  # floor duplicate: no change
    many = [f"discovery number {i} about runtime internals" for i in range(40)]
    n2 = gc.add_ceiling(c, many)
    assert len(n2.ceiling) == dc.GOAL_CEILING_CAP


# ── is_blocked (REQ-9 AC9.2, REQ-5 AC5.1) ───────────────────────────────────


def test_is_blocked_approval_unavailable_and_terminals():
    from backend.agent.nodes.outcome import Reason

    assert gc.is_blocked("approval_unavailable") is True
    assert gc.is_blocked(Reason.APPROVAL_UNAVAILABLE) is True
    assert gc.is_blocked(Reason.ROBOTS_REFUSED) is True
    assert gc.is_blocked(Reason.PERMISSION_DENIED) is True
    assert gc.is_blocked(Reason.BUDGET_EXCEEDED) is False
    assert gc.is_blocked(None) is False


def test_reason_vocabulary_member_distinct():
    from backend.agent.nodes.outcome import Reason

    assert Reason.APPROVAL_UNAVAILABLE.value == "approval_unavailable"
    assert Reason.APPROVAL_UNAVAILABLE != Reason.PERMISSION_DENIED
    assert Reason.PERMISSION_DENIED.value == "permission_denied"


# ── parse_steering_amendment (REQ-4 AC4.1) ───────────────────────────────────


def test_steering_remove_parses_floor_fact():
    p = gc.parse_steering_amendment(
        "drop the Bun vs Deno comparison", ["compare Bun vs Deno"]
    )
    assert p["remove"] == ("compare Bun vs Deno",)


def test_steering_add_parses_new_fact_clean():
    p = gc.parse_steering_amendment(
        "Also add install steps for Bun", ["compare Bun vs Deno"]
    )
    assert p["add"] == ("install steps for Bun",)


def test_steering_repromote_blocked_fact():
    p = gc.parse_steering_amendment(
        "retry the Bun vs Deno comparison now",
        ["other fact"],
        ["compare Bun vs Deno"],
    )
    assert p["repromote"] == ("compare Bun vs Deno",)


def test_steering_noise_is_noop():
    p = gc.parse_steering_amendment("looks good, continue", ["compare Bun vs Deno"])
    assert p == {"add": (), "remove": (), "repromote": ()}


# ── surplus extraction + bonus-pass helpers (REQ-4 AC4.2, REQ-3 AC3.5) ─────


def test_surplus_results_propose_ceiling_not_floor():
    c = Contract(required=("compare Bun vs Deno",))
    surplus = [
        f for f in gc.extract_required(
            "Bun vs Deno comparison plus install steps for Bun on Windows"
        )
        if f not in c.required
    ]
    n = gc.add_ceiling(c, surplus)
    assert len(n.ceiling) >= 1
    assert all(f not in c.required for f in n.ceiling)
    # floor untouched, ceiling never blocks: coverage unchanged
    before = gc.mark_coverage(c, ["VERIFIED"], ["Bun vs Deno comparison"]).C
    after = gc.mark_coverage(n, ["VERIFIED"], ["Bun vs Deno comparison"]).C
    assert after == before


def test_facts_mapped_counts_planner_hits():
    facts = gc.extract_required("1. compare Bun vs Deno 2. list three features")
    steps = [{"expected_output": "Bun vs Deno comparison table"}]
    omitted = gc.map_to_steps(facts, steps)
    assert len(facts) - len(omitted) == 1  # mapped = seeded - omitted
