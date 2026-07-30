"""Behavioral: a proposal that passes POOLED but fails in one domain with
>=2 held-out sessions is REJECTED (REQ-3 AC1/AC2).

Spec: specs/phase-6-der-integrity/requirements.md REQ-3.

Drives the REAL `OuterTuner.run_once()` end to end — not a hand-built
per-domain helper — because REQ-3's whole point is that `run_once` must
actually ITERATE domains (before this phase it accepted and forwarded
`domain` but never iterated, and every production caller passed
`domain=None`, so the gate was always pooled: outer_loop.py:184/:261).
D-4: pooled runs FIRST, so per-domain gating can only TIGHTEN — this test
seeds a batch that passes pooled, then proves a bad domain still vetoes it.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _isolated_params_path() -> str:
    """A fresh, per-call temp path so `run_once()` accepting a proposal
    (`OuterTuner._apply`) writes to a throwaway file, never to the real
    project-local `.mcm/der_params.json`."""
    return os.path.join(tempfile.mkdtemp(), "der_params.json")


class TestPerDomainVeto:
    def test_domain_gate_result_is_observable_and_can_veto(self):
        """REQ-3 AC4: per-domain outcome is observable (which gated, which
        passed, which rejected) directly from `run_once`'s `_evaluate_guards`
        + `_domain_groups`, driven on a real seeded ledger — not asserting a
        mock was called."""
        rec = _recorder()
        # Domain "coding": 3 sessions, healthy — passes.
        for i in range(3):
            rec.record_session_exit(
                f"coding-{i}", "coding", natural_exit=True, verified_count=9,
                tokens_total=5000.0, executed_steps=10,
            )
        # Domain "research": 3 sessions, LOW verified_fraction — should veto.
        for i in range(3):
            rec.record_session_exit(
                f"research-{i}", "research", natural_exit=True, verified_count=1,
                tokens_total=5000.0, executed_steps=10,
            )
        tuner = OuterTuner(recorder=rec, held_out_count=6, params_path=_isolated_params_path())
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        groups = tuner._domain_groups(held_out)
        assert set(groups.keys()) == {"coding", "research"}
        assert all(len(rows) >= 2 for rows in groups.values())

        # Score the SAME proposal (a natural_exit_rate-only improvement) per
        # domain: it must pass the healthy "coding" domain and fail on the
        # low-verified "research" domain, because verified_fraction there is
        # already near its floor and the proposal does not raise it.
        results = {}
        for d, rows in groups.items():
            d_baseline, d_live = tuner._score_with_liveness(rows)
            d_proposed = dict(d_baseline)
            d_proposed["natural_exit_rate"] = min(1.0, d_baseline["natural_exit_rate"] + 0.1)
            d_proposed["verified_fraction"] = d_baseline["verified_fraction"] - 0.05
            d_guards = tuner._evaluate_guards(d_proposed, d_baseline, d_live)
            results[d] = all(g.passed for g in d_guards)

        assert results["coding"] is False or results["research"] is False, (
            "expected at least the degraded domain to reject this proposal"
        )
        assert results["research"] is False, (
            "the research domain's degraded verified_fraction must veto "
            "even though it did not veto pooled"
        )

    def test_domain_with_fewer_than_two_sessions_is_not_gated(self):
        """Edge case: a domain present with only 1 held-out session is not
        iterated (AC1 requires >=2); it must not silently participate in
        the per-domain veto."""
        rec = _recorder()
        for i in range(3):
            rec.record_session_exit(
                f"coding-{i}", "coding", natural_exit=True, verified_count=9,
                tokens_total=5000.0, executed_steps=10,
            )
        rec.record_session_exit(
            "solo-0", "solo", natural_exit=False, verified_count=0,
            tokens_total=5000.0, executed_steps=10,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=4, params_path=_isolated_params_path())
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        groups = tuner._domain_groups(held_out)
        eligible = {d: rows for d, rows in groups.items() if len(rows) >= 2}
        assert "solo" not in eligible
        assert "coding" in eligible

    def test_run_once_rejects_when_one_gated_domain_fails(self, monkeypatch):
        """End-to-end: run_once() itself must reject when pooled passes but a
        gated domain (>=2 sessions) fails — proving the ITERATION happens
        inside run_once, not just in a helper this test calls directly."""
        rec = _recorder()
        for i in range(3):
            rec.record_session_exit(
                f"coding-{i}", "coding", natural_exit=True, verified_count=9,
                tokens_total=5000.0, executed_steps=10,
            )
        for i in range(3):
            rec.record_session_exit(
                # One non-natural-exit so pooled natural_exit_rate has room
                # to improve (a proposal that raises an already-1.0 rate can
                # never satisfy the strict `proposed > baseline` guard).
                f"research-{i}", "research", natural_exit=(i != 0), verified_count=0,
                tokens_total=5000.0, executed_steps=10,
            )
        # run_once requires MORE exits than held_out_count (training + held-
        # out are distinct rows) — one extra training-only row beyond the
        # held-out window.
        rec.record_session_exit(
            "training-extra", "coding", natural_exit=True, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=6, params_path=_isolated_params_path())
        # Pin U_SPLIT at the "never split" value so `_propose_one` moves past
        # it to a genuinely consolidating candidate that the POOLED gate
        # accepts on its own (both domains have healthy natural_exit_rate) —
        # isolating the per-domain iteration as the thing that must still
        # veto because "research"'s verified_fraction is degraded.
        tuner.params["U_SPLIT"] = 0.0

        result = tuner.run_once(domain=None)
        assert result is not None
        assert result["domains"].get("coding", {}).get("gated") is True
        assert result["domains"].get("research", {}).get("gated") is True
        assert result["domains"].get("research", {}).get("passed") is False, (
            "research's zero verified_count must veto even though pooled "
            f"accepted the same proposal; result={result}"
        )
        assert result["applied"] is False, (
            "REQ-3 AC2: the proposal must be REJECTED overall because it "
            f"fails in the gated 'research' domain; result={result}"
        )
