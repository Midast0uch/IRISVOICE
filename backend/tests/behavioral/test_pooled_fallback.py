"""Behavioral: with fewer than 2 sessions in EVERY domain, behaviour is the
pooled gate — preserving current (pre-REQ-3) behaviour (REQ-3 AC3).

Spec: specs/phase-6-der-integrity/requirements.md REQ-3 AC3.

D-4: pooled runs first and per-domain gating can only ADD rejections. When
no domain has >=2 held-out sessions, per-domain iteration must not run at
all — the outcome must be IDENTICAL to the pooled-only gate that existed
before REQ-3, and the fallback must be observable (REQ-3 AC4), not silent.
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
    project-local `.mcm/der_params.json` — otherwise a passing test would
    leave persistent side effects on the developer's machine."""
    return os.path.join(tempfile.mkdtemp(), "der_params.json")


class TestPooledFallback:
    def test_all_domains_singleton_falls_back_to_pooled(self):
        rec = _recorder()
        # Three DIFFERENT domains, one session each -> no domain has >=2.
        rec.record_session_exit(
            "s0", "coding", natural_exit=True, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        rec.record_session_exit(
            "s1", "research", natural_exit=True, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        rec.record_session_exit(
            "s2", "voice", natural_exit=False, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        # run_once requires MORE exits than held_out_count.
        rec.record_session_exit(
            "s3-extra", "extra", natural_exit=True, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=3, params_path=_isolated_params_path())
        # Pin U_SPLIT at the "never split" value so `_propose_one` moves past
        # it to a genuinely consolidating candidate (0.4 > 0.0) that
        # `_score_proposal`'s conservative rule treats as an improvement —
        # isolating the POOLED gate's own accept/reject decision from the
        # never-split hack (covered separately by test_never_split_rejected).
        tuner.params["U_SPLIT"] = 0.0
        result = tuner.run_once(domain=None)
        assert result is not None
        assert result["applied"] is True, (
            "fixture must produce a pooled-accepted proposal so the fallback "
            f"branch actually runs; got {result}"
        )
        # AC4: the fallback itself must be observable.
        assert "_fallback" in result["domains"]
        assert "pooled" in result["domains"]["_fallback"]

    def test_pooled_outcome_matches_direct_pooled_gate(self):
        """The applied/rejected outcome under fallback must be identical to
        scoring the pooled batch directly — no domain iteration silently
        changed the answer."""
        rec = _recorder()
        rec.record_session_exit(
            "s0", "coding", natural_exit=True, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        rec.record_session_exit(
            "s1", "research", natural_exit=False, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        # run_once requires MORE exits than held_out_count.
        rec.record_session_exit(
            "s2-extra", "voice", natural_exit=True, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=2, params_path=_isolated_params_path())
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        baseline, live = tuner._score_with_liveness(held_out)
        key, value = tuner._propose_one()
        expected_proposed = tuner._score_proposal(key, value, held_out, baseline)
        expected_pooled_accepts = OuterTuner._compound_accepts(expected_proposed, baseline, live)

        result = tuner.run_once(domain=None)
        assert result["applied"] == expected_pooled_accepts

    def test_no_domain_column_behaves_as_general_singleton_or_fallback(self):
        """Sessions with no domain given collapse to 'general' (D-4 /
        `_domain_groups`); with only one such session per distinct domain
        label, the pooled fallback still applies."""
        rec = _recorder()
        rec.record_session_exit(
            "s0", "", natural_exit=True, verified_count=9,
            tokens_total=5000.0, executed_steps=10,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=1, params_path=_isolated_params_path())
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        groups = tuner._domain_groups(held_out)
        # Empty/blank domain collapses to "general" (Dict.get(...) or "general").
        assert "general" in groups
        assert all(len(rows) < 2 for rows in groups.values())
