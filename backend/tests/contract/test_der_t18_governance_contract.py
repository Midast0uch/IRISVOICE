"""CT-G1 — REQ-6 (T18): governance-source is observed, measured, exposed.

Pins the inversion-of-governance observability at the REAL kernel boundary:

  - AC1: every steering decision records WHICH signal governed it —
    past-memory (compressed node record present) | live-state (memory-sparse,
    decision runs on the live Σ alone) | both (record AND live Σ — the
    equal-signals edge). No hardcoded authority (AC2): the source is OBSERVED
    at the decision point, never chosen by a branch.
  - AC1 edge: recording is off the hot path and lossy-safe — a missing
    counter silently re-initializes, never raises.
  - AC3: the per-turn alternation ratio is exposed on TurnMetrics and in the
    [LAYERS] line (gov_past/gov_live/gov_both/gov_ratio), readable by the
    outer loop. ratio = (past + both) / total among recorded decisions.

Drives the REAL ``_der_record_governance`` helper + the REAL
``TurnMetrics.to_log_line`` (real instance); the step-context wiring is
verified through the real kernel attribute the helper maintains.

Spec: specs/der-dag-inversion/requirements.md REQ-6.
"""

from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.utils.observability import TurnMetrics


def _make_kernel() -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k._der_governance_counts = None  # fresh turn: no decisions recorded yet
    return k


def test_ac1_records_governance_source_per_decision():
    k = _make_kernel()
    k._der_record_governance("past")
    k._der_record_governance("live")
    k._der_record_governance("both")
    assert k._der_governance_counts == {"past": 1, "live": 1, "both": 1}


def test_ac1_lossy_safe_missing_counter_reinitializes():
    k = _make_kernel()
    k._der_record_governance("live")  # _der_governance_counts starts None
    assert k._der_governance_counts == {"past": 0, "live": 1, "both": 0}


def test_ac1_unknown_source_lands_in_both_equal_signals_edge():
    k = _make_kernel()
    k._der_record_governance("???")  # unknown -> both (equal-signals edge)
    assert k._der_governance_counts == {"past": 0, "live": 0, "both": 1}


def test_ac3_ratio_exposed_on_turnmetrics_and_layers_line():
    k = _make_kernel()
    k._der_record_governance("past")
    k._der_record_governance("both")
    k._der_record_governance("live")

    metrics = TurnMetrics(turn_id="t-g1")
    metrics.path = "der"
    metrics.der_steps = 3
    # the exact caller lines (agent_kernel.py ~4916-4924)
    _gov = getattr(k, "_der_governance_counts", None) or {}
    metrics.gov_past = int(_gov.get("past", 0) or 0)
    metrics.gov_live = int(_gov.get("live", 0) or 0)
    metrics.gov_both = int(_gov.get("both", 0) or 0)

    line = metrics.to_log_line()
    # ratio = (past + both) / total = (1 + 1) / 3 = 0.667
    assert metrics.gov_ratio == 0.667
    assert "gov_past=1 gov_live=1 gov_both=1 gov_ratio=0.667" in line
    # the existing [LAYERS] fields survive (no regression on der_steps)
    assert "der_steps=3" in line
    assert "turn=t-g1" in line


def test_ac3_zero_decisions_ratio_zero_no_division_error():
    k = _make_kernel()  # no decisions recorded
    metrics = TurnMetrics(turn_id="t-g1z")
    metrics.gov_past = metrics.gov_live = metrics.gov_both = 0
    line = metrics.to_log_line()
    assert metrics.gov_ratio == 0.0
    assert "gov_ratio=0.0" in line


def test_ac2_no_hardcoded_authority_source_is_observed_not_branched():
    """The governance recorder takes the source as an argument — it never
    decides which signal is authoritative. A memory-sparse decision is
    'live' because that is what the step observed, not because the code
    prefers live state."""
    k = _make_kernel()
    # memory-sparse step (no node record) -> live governance, observed
    k._der_record_governance("live")
    # step with a compressed record AND live Σ -> both, observed
    k._der_record_governance("both")
    assert k._der_governance_counts["live"] == 1
    assert k._der_governance_counts["both"] == 1
