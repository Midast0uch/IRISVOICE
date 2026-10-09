"""REQ-10 (specs/oracle-native-decision-surface) - the `call_closing` fences.

The owner's concern: *"the agent stops its work early thinking it's done and not
adhering to the goal contract... it messes up the DER-DAG."* The concern is not
hypothetical: `done` ALREADY has a live enforcement path - `agent_kernel.py:20962`
passes `enforced=_done_dec` and `:20970` writes the Oracle's answer into
`data["done"]`, the bit the loop reads. So a NAMING CONVENTION IS NOT A DEFENCE.

Three independent fences stand instead:
  1. this file's first tests - the consumer is REFUSED at the chokepoint;
  2. `test_node_executor_never_consumes_call_closing` - the fence that matters,
     because it fails if anyone wires the answer into the loop;
  3. the existing goal-contract veto at `agent_kernel.py:20983-20989`.
"""
from __future__ import annotations

from pathlib import Path

from backend.agent import decision_engine as de

_NODE_EXECUTOR = Path("backend/agent/node_executor.py")


# ── AC10.0 fence 1: MEASUREMENT-ONLY, permanently ───────────────────────────

def test_call_closing_is_in_the_tier_c_refusal_list():
    assert "call_closing" in de.REFUSED_CONSUMERS


def test_refused_consumer_never_decides_however_the_config_is_set(monkeypatch):
    """Even when all three other keys pass, the refusal wins.

    ``_enforcement`` is stubbed to return a threshold, which is what the owner's
    switch + an earned bar + a fitted curve would produce. `decides` must still
    answer None, and `oracle_acts` must still be False at any confidence."""
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "call_closing")
    monkeypatch.setattr(de, "_enforcement", lambda cid: (0.10, ""))
    assert de.decides("call_closing") is None
    assert de.oracle_acts("call_closing", 0.999) is False
    assert "call_closing" not in de.enforced_consumers()


def test_threshold_resolution_refuses_call_closing():
    """AC10.0: excluded from threshold resolution, not merely from the switch."""
    cfg = de.EngineConfig(backend_id="d1-3b-ad-q4_k_m")
    cfg.backend_thresholds = {"d1-3b-ad-q4_k_m": 0.5}
    cfg.thresholds = {"call_closing": 0.5}       # even an explicit override
    assert cfg.threshold_for("call_closing") is None


# ── AC10.0 fence 2: THE FENCE THAT MATTERS ──────────────────────────────────

def test_node_executor_never_consumes_call_closing():
    """No code path in `node_executor.py` may read `call_closing`'s
    `DecisionScore`, `Noul` or probability into the loop's continuation, the
    `max_calls` check, or the closing return.

    This test fails if anyone wires it, and it is independent of anyone's good
    intentions or naming discipline. If a future wave legitimately needs the
    name in this file, that is a FINDING to report - not a line to edit here."""
    src = _NODE_EXECUTOR.read_text(encoding="utf-8")
    assert "call_closing" not in src, (
        "node_executor.py references `call_closing`. The consumer is "
        "MEASUREMENT-ONLY (AC10.0 fence 1) and this file owns the closing rule; "
        "reading its answer into the loop is exactly the early-stop hazard the "
        "fence exists to prevent."
    )


def test_the_closing_rule_is_still_the_truth_source():
    """AC10.4: the label is the closing rule, so the rule must not drift.

    `node_executor.py:629` closes the loop only when
    `not batch_failed and not batch_changed and (batch_done or _STATUS.search(text))`.
    If this changes, every historical `call_closing` label silently changes
    meaning."""
    src = _NODE_EXECUTOR.read_text(encoding="utf-8")
    assert "not batch_failed and not batch_changed and (batch_done or _STATUS.search(text" in src
    # The changed-file half of that rule is what AC10.5's exclusion reads.
    assert "batch_changed" in src


# ── AC10.2 / AC10.5: the candidate rule ─────────────────────────────────────

def test_changed_file_call_is_never_a_candidate():
    """AC10.5: a call that changed a file can never close the step, so its
    `step_done` claim is POLICY, not judgement - d1 is not asked about it."""
    assert de.CALL_CLOSING_CHANGED_FILE_EXCLUDED is True
    assert de.call_closing_is_candidate(
        claimed_step_done=True, batch_changed=True) is False


def test_only_claiming_calls_are_candidates():
    """AC10.2: asked ONLY about calls that claimed to close the step, so the GPU
    cost is bounded by construction and the name stays honest."""
    assert de.call_closing_is_candidate(
        claimed_step_done=False, batch_changed=False) is False
    assert de.call_closing_is_candidate(
        claimed_step_done=True, batch_changed=False) is True


# ── AC10.1 / AC10.7: the declaration ────────────────────────────────────────

def test_call_closing_is_a_declared_noul_with_its_own_job():
    assert de.declared_type(de.CALL_CLOSING_CONSUMER) == "noul"
    assert de.oracle_job(de.CALL_CLOSING_CONSUMER).name != "general"
    assert de.CONSUMER_JOBS.get(de.CALL_CLOSING_CONSUMER) == "judge_call"
    assert de.oracle_job(de.CALL_CLOSING_CONSUMER).name == "judge_call"


def test_the_name_is_never_a_loop_control_verb():
    """The name is a safety requirement (AC10.1). `done` asks whether the TASK is
    finished; this asks whether one call was the last one.

    Checked on the CODE (identifiers), not on the prose - the engine names the
    forbidden words in order to forbid them."""
    assert de.CALL_CLOSING_CONSUMER == "call_closing"
    assert "call_closing" in de.CONSUMERS
    # The two forbidden aliases must not be module-level names anywhere in the
    # engine (an alias is how a loop-control verb would sneak back in).
    assert not hasattr(de, "step_satisfied")
    assert not hasattr(de, "done_at_call")
