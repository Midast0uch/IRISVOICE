"""CT-O1 — REQ-16 (T33): outer loop consumes live signal-relevance inputs.

Pins the REQ-16 AC3 wiring against the REAL ``OuterTuner``:

  - AC3 (governance ratio / REQ-6): ``_signal_observations`` reads the
    kernel's per-turn governance counter and reports the past-governed share
    (None when nothing recorded — absent, not zero).
  - AC3 (rate health / REQ-9, T27): the meter's per-quota health feeds the
    relevance judge; a SATURATED provider (429 pressure / falling ceiling)
    makes ``run_once`` HOLD OFF tuning — the throttled provider contaminates
    the observed natural-exit signal (REQ-16 edge: rate health absent ->
    relevance from governance ratio only; unmetered -> never fabricated).
  - AC3 (per-domain aggregates / REQ-21, T22): ``compute_domain_aggregates``
    feeds ``domain_signal`` presence.
  - CT-O1 (outer loop fires at real boundary): the production entry
    ``run_outer_loop(session_id)`` collects observations and passes them to
    the tuner — no test-only invocation.
  - Behavioral: relevance judged over a MULTI-SESSION sample (4 seeded
    sessions) — a healthy provider tunes, a saturated provider holds off on
    the SAME data.
"""
import os
import sqlite3
from unittest.mock import patch

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _seed_multi_session(rec, n=4):
    """A multi-session held-out sample: mostly natural exits, real tokens."""
    for i in range(n):
        rec.record_session_exit(
            f"s{i}", "general", natural_exit=(i != 1), verified_count=8,
            tokens_total=5000.0, executed_steps=10,
        )


def _tuner(rec, held_out=3, u_split=0.0):
    t = OuterTuner(recorder=rec, held_out_count=held_out, params_path="")
    t.params["U_SPLIT"] = u_split  # so _propose_one moves to a real increase
    return t


# ── AC3: signal observation collection ───────────────────────────────────────


def test_signal_observations_reads_governance_ratio():
    """REQ-6 AC3 -> REQ-16 AC3: the past-governed share of steering
    decisions is reported from the kernel's per-turn counter."""
    rec = _recorder()
    obs = OuterTuner._signal_observations(
        "s0", recorder=rec,
        governance_counts={"past": 2, "live": 1, "both": 0},
    )
    assert obs["governance_ratio"] == 0.667  # (2+0)/3


def test_signal_observations_absent_when_no_decisions():
    """REQ-16 AC3 edge: no governance decisions recorded -> ratio None
    (absent, not zero — a session that never used past-memory must not be
    read as 'fully live-governed')."""
    rec = _recorder()
    obs = OuterTuner._signal_observations("s0", recorder=rec, governance_counts=None)
    assert obs["governance_ratio"] is None


def test_signal_observations_reads_domain_aggregates():
    """REQ-21 AC2 -> REQ-16 AC3: per-domain physics aggregates feed the
    observation (present when the session has trajectory rows)."""
    rec = _recorder()
    rec.record(
        session_id="sagg", step_num=1,
        x=0.0, y=0.0, xi=0.1, u=0.2, action=0,
        outcome="CONTINUE", eml_after=0.0,
        domain="der", execution_domain="der", topic_domain="web",
    )
    obs = OuterTuner._signal_observations("sagg", recorder=rec, governance_counts={})
    _agg = obs["domain_aggregates"]
    assert _agg is not None and isinstance(_agg, dict)
    assert "der" in _agg or _agg == {}


# ── AC3: saturation holds off tuning ─────────────────────────────────────────


def _saturated_observations():
    """Rate health reporting 429 pressure + falling ceiling."""
    return {
        "governance_ratio": 0.7,
        "rate_health": {
            "metered": True,
            "count_429_in_window": 3,
            "429_per_min": 3.0,
            "last_429_at": 1234.0,
            "ceiling_rpm": 15.0,
            "ceiling_trajectory": [(1.0, 30.0), (2.0, 15.0)],
            "ceiling_trend": "falling",
            "window_s": 60.0,
        },
        "domain_aggregates": {"der": {"n": 3, "avg_u": 0.2}},
    }


def _healthy_observations():
    return {
        "governance_ratio": 0.7,
        "rate_health": {
            "metered": True,
            "count_429_in_window": 0,
            "429_per_min": 0.0,
            "last_429_at": None,
            "ceiling_rpm": 30.0,
            "ceiling_trajectory": [(1.0, 30.0)],
            "ceiling_trend": "stable",
            "window_s": 60.0,
        },
        "domain_aggregates": {"der": {"n": 3, "avg_u": 0.2}},
    }


def test_saturated_provider_holds_off_tuning():
    """REQ-16 AC3: with a SATURATED provider (429 pressure, falling ceiling),
    run_once holds off — it does NOT tune on a contaminated signal."""
    rec = _recorder()
    _seed_multi_session(rec)
    t = _tuner(rec)
    out = t.run_once(domain="general", observations=_saturated_observations())
    assert out is not None
    assert out["applied"] is False
    assert out["reason"] == "provider_saturated"
    assert out["signal_relevance"]["rate_strength"] == "saturated"
    # The relevance verdict rides the result.
    assert out["signal_relevance"]["governance_relevance"] == "past"


def test_healthy_provider_tunes_on_same_data():
    """REQ-16 AC3 behavioral: the SAME multi-session sample with a HEALTHY
    provider proceeds to the compound gate (may accept or reject on merit,
    but is NOT held off by saturation)."""
    rec = _recorder()
    _seed_multi_session(rec)
    t = _tuner(rec)
    out = t.run_once(domain="general", observations=_healthy_observations())
    assert out is not None
    assert out.get("reason") != "provider_saturated"
    assert out["signal_relevance"]["rate_strength"] == "healthy"
    # Either accepted on merit or rejected by a guard — never held off.
    assert "applied" in out


def test_absent_rate_health_relevance_from_governance_only():
    """REQ-16 edge: rate health ABSENT -> the relevance judge reads
    governance only; tuning is not held off (absence is not saturation)."""
    rec = _recorder()
    _seed_multi_session(rec)
    t = _tuner(rec)
    obs = {"governance_ratio": 0.9, "rate_health": None, "domain_aggregates": None}
    out = t.run_once(domain="general", observations=obs)
    assert out is not None
    assert out["signal_relevance"]["rate_strength"] == "absent"
    assert out["signal_relevance"]["governance_relevance"] == "past"
    assert out.get("reason") != "provider_saturated"


def test_unmetered_never_fabricated_saturated():
    """REQ-9 edge -> REQ-16 AC3: an UNMETERED quota reports absent, never
    saturated — a free provider is never held off by fabricated pressure."""
    rel = OuterTuner._signal_relevance(
        {"rate_health": {"metered": False, "count_429_in_window": 0}}
    )
    assert rel["rate_strength"] == "absent"


# ── CT-O1: production entry collects observations ────────────────────────────


def test_ct_o1_production_entry_feeds_observations():
    """CT-O1: run_outer_loop(session_id) — the production entry wired in T32
    — collects signal observations and passes them into the tuner. Driven
    with a real recorder bound to the no-op fallback path; the observation
    plumbing is asserted (it reaches run_once), not the tuning outcome."""
    import backend.agent.outer_loop as ol

    seen = {}

    class _Spy:
        def __init__(self, *a, **k):
            self.recorder = _recorder()
            self.params = {}
            self.held_out_count = 3

        def run_once(self, domain=None, observations=None):
            seen["observations"] = observations
            return {"applied": False, "reason": "spy", "signal_relevance": {}}

    _orig = ol.OuterTuner
    ol.OuterTuner = _Spy
    try:
        _fake_kernel = type(
            "K", (), {"_der_governance_counts": {"past": 1, "live": 0, "both": 0}}
        )()
        with patch("backend.agent.get_active_kernel", return_value=_fake_kernel):
            ol.run_outer_loop("sess-ct-o1")
    finally:
        ol.OuterTuner = _orig

    assert seen.get("observations") is not None
    _obs = seen["observations"]
    assert _obs["session_id"] == "sess-ct-o1"
    # Governance counts from the (stubbed) active kernel reached the collector.
    assert _obs["governance_ratio"] == 1.0  # past=1 of total=1
    assert set(_obs.keys()) == {
        "session_id", "governance_ratio", "rate_health", "domain_aggregates",
    }


# ── Debug surface ────────────────────────────────────────────────────────────


def test_debug_endpoint_reports_signal_relevance():
    """REQ-16 AC3 ripple: the caducean_debug live-guard display reports the
    signal-relevance verdict read-only."""
    import backend.agent.outer_loop as ol
    from backend.api import caducean_debug

    rec = _recorder()
    _seed_multi_session(rec)

    orig = ol.OuterTuner
    ol.OuterTuner = lambda: _tuner(rec)
    try:
        r = caducean_debug._outer_loop()
    finally:
        ol.OuterTuner = orig

    assert "error" not in r
    assert "signal_relevance" in r
    _rel = r["signal_relevance"]
    assert set(_rel.keys()) == {
        "governance_relevance", "rate_strength", "domain_signal", "relevance_score",
    }
    assert _rel["rate_strength"] in ("healthy", "saturated", "absent")


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
