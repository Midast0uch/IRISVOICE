"""Wave 5 (REQ-6): the sampled rung's contract.

AC6.1   `sampled` is a bar status BETWEEN shadow and enforced, derived under
        stated conditions, never from a partial measurement.
AC6.2   a sampled consumer decides on a bounded fraction of consults, only
        where a wrong answer is cheap and reversible; the incumbent remains
        the fallback for every other consult.
AC6.3   a sampled row is labelled by OUTCOME (joined on turn_id), never by
        the incumbent.
AC6.4   the fraction is a named constant with a kill switch.
AC6.6b  no tier, no sampling - and tier C (call_closing) is refused outright.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

import pytest

from backend.agent import consumer_bar as cb
from backend.agent import decision_engine as de


# ── AC6.6b / AC6.2: the two gates, no defaults ─────────────────────────────


def test_untiered_and_refused_consumers_can_never_be_sampled(monkeypatch):
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE_FRACTION", "1.0")  # even at 100%
    assert de.sampled_consult_ok("call_closing", "scope") is False, (
        "tier C is refused outright")
    assert de.sampled_consult_ok("presentation", "scope") is False, (
        "no ground truth, no sampling (Gate 2)")
    assert de.sampled_consult_ok("mode", "scope") is False
    # STALE-BY-SPEC update (2026-10-11, owner: "the Oracle decides all tools
    # if capable"): tool_choice is SAMPLABLE now that a pick only NARROWS the
    # model's menu (the model still writes the arguments, or finishes). The
    # reversibility gate moved to the PICK: test_a_sampled_side_effect_pick_
    # never_acts below pins that a sampled pick of a non-read-only tool never
    # narrows anything without the eval switch.
    assert de.sampled_consult_ok("tool_choice", "scope") is True
    assert de.sampled_consult_ok("done", "scope") is False
    assert de.sampled_consult_ok("needs_action", "scope") is True


def _tool_box(chosen):
    from backend.agent.decision_engine import CandidateScore, DecisionScore
    from backend.agent.tool_decision import ToolDecisionBox

    class _Eng:
        model_id = "stub"

        def decide(self, consumer_id, options, frame):
            return DecisionScore(consumer_id=consumer_id, chosen=chosen, confidence=0.9,
                                 distribution=tuple(CandidateScore(o, -0.1, 0.1) for o in options),
                                 engine_latency_ms=1)

    class _Bridge:
        def record_decision(self, *a, **k):
            pass

    class _Router:
        def generate(self, *a, **k):
            return ("", "", [])

    return ToolDecisionBox(router=_Router(), tool_bridge=_Bridge(),
                           get_available_tools=lambda: [],
                           validate_tool_call=lambda t, p: (True, None),
                           decision_engine=_Eng())


def test_a_sampled_side_effect_pick_never_acts(monkeypatch):
    """AC6.6 Gate 1 per PICK (2026-10-11): a sampled tool pick narrows the
    model's menu only to a READ-ONLY tool; a side-effect pick acts on a sample
    only under the eval switch (throw-away work folders)."""
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE_FRACTION_TOOL_CHOICE", "1.0")
    monkeypatch.delenv("IRIS_ORACLE_SAMPLE_SIDE_EFFECTS", raising=False)
    menu = ["read_file", "edit_file", "run_command"]
    kw = dict(goal="fix m.py", candidates=menu, scope_key="s")
    assert _tool_box("edit_file").choose_node_tool(**kw) is None
    got = _tool_box("read_file").choose_node_tool(**kw)
    assert got is not None and got[0] == "read_file" and got[1]["route"] == "sampled"
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE_SIDE_EFFECTS", "1")
    assert _tool_box("edit_file").choose_node_tool(**kw)[0] == "edit_file"


def test_the_fraction_is_bounded_and_the_kill_switch_kills(monkeypatch):
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE_FRACTION", "0")
    assert de.sampled_consult_ok("needs_action", "scope") is False
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE", "0")
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE_FRACTION", "1.0")
    assert de.sampled_consult_ok("needs_action", "scope") is False, (
        "the kill switch wins over any fraction")


def test_sampling_is_deterministic_and_bounded(monkeypatch):
    """A re-asked consult answers the same way; over many scopes the hit rate
    tracks the stated fraction."""
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE_FRACTION", "0.5")
    a = de.sampled_consult_ok("needs_action", "t1|s1|x")
    assert de.sampled_consult_ok("needs_action", "t1|s1|x") == a
    monkeypatch.setenv("IRIS_ORACLE_SAMPLE_FRACTION", "0.25")
    hits = sum(
        de.sampled_consult_ok("needs_action", f"turn-{i}")
        for i in range(400))
    assert 40 < hits < 160, (  # 25% of 400 = 100; very wide band, no flake
        f"hit rate {hits}/400 is not near the stated fraction")


def test_default_fraction_is_the_named_constant(monkeypatch):
    monkeypatch.delenv("IRIS_ORACLE_SAMPLE_FRACTION", raising=False)
    monkeypatch.delenv("IRIS_ORACLE_SAMPLE", raising=False)
    assert de.SAMPLE_FRACTION == 0.05
    hits = sum(
        de.sampled_consult_ok("needs_action", f"turn-{i}")
        for i in range(400))
    assert hits <= 60, f"{hits}/400 far above the 5% default"


# ── AC6.3: sampled rows are labelled by the turn OUTCOME ────────────────────


def test_a_sampled_row_joins_on_turn_id_from_the_turn_outcome(monkeypatch):
    rows: list = []
    monkeypatch.setattr(de, "_TURN_PENDING", de.OrderedDict())
    monkeypatch.setattr(de, "_OUTCOME_SINK", rows.append)
    scope = {"turn_id": "tA", "step_id": "s3"}
    de.register_turn_pending(scope, de.sampled_row("needs_action", True, 0.91))
    assert rows == [], "the row waits for the turn outcome - never parity"
    assert de.resolve_turn_pending("tA", True) == 1
    (row,) = rows
    assert row["outside_label"] is True
    assert row["outcome_label"] == "turn_ok"
    assert row["label_source"] == "outcome", "T5.10: NOT an incumbent label"
    assert row["turn_id"] == "tA" and row["route"] == "sampled"


def test_a_failed_turn_labels_the_sampled_row_against_it(monkeypatch):
    rows: list = []
    monkeypatch.setattr(de, "_TURN_PENDING", de.OrderedDict())
    monkeypatch.setattr(de, "_OUTCOME_SINK", rows.append)
    de.register_turn_pending({"turn_id": "tB"}, de.sampled_row(
        "needs_action", False, 0.7))
    assert de.resolve_turn_pending("tB", False) == 1
    assert rows[0]["outside_label"] is False
    assert rows[0]["outcome_label"] == "turn_fail"


def test_a_choice_rowed_sampled_consult_carries_the_outcome_only(monkeypatch):
    """A choice consumer's answer is a NAME - it has no boolean reading, so
    the row carries the turn outcome label but NO outside_label (never
    rank-scored against an incommensurable reference)."""
    rows: list = []
    monkeypatch.setattr(de, "_TURN_PENDING", de.OrderedDict())
    monkeypatch.setattr(de, "_OUTCOME_SINK", rows.append)
    de.register_turn_pending({"turn_id": "tB2"}, de.sampled_row(
        "recovery_strategy", "retry_same", 0.7))
    assert de.resolve_turn_pending("tB2", False) == 1
    assert rows[0]["outcome_label"] == "turn_fail"
    assert "outside_label" not in rows[0]


# ── AC6.1: `sampled` in the bar record ──────────────────────────────────────


def test_sampled_requires_eligibility_and_outcome_rows():
    """Stated conditions only: tier-eligible AND at least one outcome row.
    Below the bar + zero outcome rows is SHADOW - no implication from a
    partial measurement."""
    bar = lambda **kw: cb.derive_status(         # noqa: E731
        50, 0.80, 0.10, **kw)  # every legacy clause fails -> shadow first
    assert bar(sampling_eligible=True, outcome_rows=3) == (
        "sampled", "enforcement bar unmet (rows 50 < 100); rung live")
    assert bar(sampling_eligible=False, outcome_rows=3)[0] == "shadow"
    assert bar(sampling_eligible=True, outcome_rows=0)[0] == "shadow"


def test_the_full_bar_still_wins_over_sampled():
    """AC9.4: no clause relaxed - enforcement still needs the hardened bar."""
    status, gap = cb.derive_status(
        500, 0.99, 0.01, sampling_eligible=True, outcome_rows=10)
    assert status == "enforced" and gap == ""


def test_superseded_flips_still_skips_sampled_consumers():
    """AC13.8, kept visible: a `sampled` consumer is not inspected (it is
    live-ish, but enforcing nothing) - stated, not silently absent."""
    record = {"needs_action": cb.ConsumerBar(
        consumer_id="needs_action", rows=50, precision=0.9, ece=0.1,
        status="sampled", config={"candidate_cap": 8})}
    assert cb.superseded_flips(record, {"candidate_cap": 6}) == []


# ── T5.0 (AC6.3a): the scope rides every Oracle row payload ─────────────────


def test_scope_is_bound_as_values_and_filterable():
    token = de.set_scope(turn_id="t99", step_id=None, node_exec_id="s9#1",
                         noise="kept? no")
    try:
        s = de.scope_now()
        assert s == {"turn_id": "t99", "node_exec_id": "s9#1"}, s
        # A step_id of None/"" joins as ABSENT, never as a literal "None".
        assert "step_id" not in s
    finally:
        de._SCOPE.reset(token)
    assert de.scope_now() == {}


def test_shadow_rows_carry_the_scope(monkeypatch):
    """T5.0: a shadow row carries turn_id/step_id so the outcome join has
    something to attach to. Values are bound at SUBMIT time, before the row
    goes to the lane."""
    from backend.utils.durability_queue import lane

    eng = de.DecisionEngine.__new__(de.DecisionEngine)
    eng.model_id = "stub"
    rows, landed = [], threading.Event()

    def _decide(consumer_id, options, frame, instruction=None):
        return de.DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.8,
            distribution=tuple(
                de.CandidateScore(o, -0.1, 0.4) for o in options),
            engine_latency_ms=1)

    eng.decide = _decide
    token = de.set_scope(turn_id="t-scope", step_id="s-9")
    try:
        ok = eng.shadow("mode", ["quick", "spec"], {"goal": "x"},
                        sink=lambda r: (rows.append(r), landed.set()))
    finally:
        de._SCOPE.reset(token)
    assert ok and landed.wait(10), "the lane must drain"
    (row,) = rows
    assert row["turn_id"] == "t-scope" and row["step_id"] == "s-9"
    assert "node_exec_id" not in row
    assert lane("oracle_shadow").flush(5.0)


# ── T5.14 (AC14.5): label integrity in the report ───────────────────────────


def test_label_integrity_counts_adjudicated_against_untested_and_abandoned():
    from scripts.consumer_enforcement_report import _label_integrity

    grp = [
        {"label_source": "outcome", "outcome_label": "correct",
         "outside_label": True},
        {"label_source": "outcome", "outcome_label": "premature",
         "outside_label": False},
        {"label_source": "outcome", "outcome_label": "untested"},
        {"label_source": "outcome", "outcome_label": "abandoned"},
        {"label_source": "incumbent"},   # parity rows are not in the ratio
    ]
    assert _label_integrity(grp) == pytest.approx(0.5)
    assert _label_integrity([]) is None
    assert _label_integrity([{"label_source": "incumbent"}]) is None


# ── AC6.3a-1 (THE RIDGE): write-time dedup now scopes by turn + step ────────


def test_dedup_scopes_by_scope_so_turns_stay_distinct(monkeypatch):
    """Same scoring tuple, DIFFERENT turn -> both rows survive (the join needs
    each turn's own row). Same tuple, SAME turn+step -> still collapses (the
    B6 store-distinct goal is preserved)."""
    from backend.agent import tool_bridge as tb

    from backend.agent.tool_bridge import AgentToolBridge

    written = []
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    monkeypatch.setattr(
        bridge, "_record_tool_event",
        lambda session_id, tool, kind, args, result: written.append(kind))
    monkeypatch.setattr(tb, "_SHADOW_DEDUP", OrderedDict())

    meta = {"consumer_id": "web_intent", "engine": "e", "confidence": 0.9,
            "chosen": "no", "brain_choice": "no"}
    bridge.record_decision(dict(meta, turn_id="t1", step_id="s1"), "shadow")
    bridge.record_decision(dict(meta, turn_id="t1", step_id="s1"), "shadow")
    bridge.record_decision(dict(meta, turn_id="t2", step_id="s1"), "shadow")
    assert written == ["shadow", "shadow"], (
        "a turn-scoped duplicate was dropped - the outcome join would have "
        "nothing to attach to (AC6.3a-1)")

