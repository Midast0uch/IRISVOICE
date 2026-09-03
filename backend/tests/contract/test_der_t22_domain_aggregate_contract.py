"""CT-ON4 — REQ-21 (T22): per-domain physics aggregation.

Drives the REAL ``CaduceanTrajectoryRecorder.compute_domain_aggregates`` and
``record`` against an in-memory SQLite store with the production schema.

Pinned contracts:
  - AC1 : avg |u|, oscillation rate, convergence rate, split/collapse counts
          aggregated per execution_domain (and per topic_domain) per session.
  - AC2 : the aggregates surface as a read-only dict signal (as_dict()) —
          the outer loop / narration gate consumer surface.
  - AC3 : off the hot path; one-sample domain reported with n=1; no rows ->
          absent (empty), never zero-dict noise; failure -> skipped, never
          raises.
  - Edge: pre-ontology store (no axis column) -> empty, no error.
  - Bands reuse production narration thresholds (U_SPLIT / U_CONVERGED) so
    the aggregation and narration speak the same physics.
"""

import sqlite3

import pytest

from backend.agent.caducean_trajectory import (
    CaduceanTrajectoryRecorder,
    PhysicsAggregate,
    _u_band,
)


def _make_recorder() -> CaduceanTrajectoryRecorder:
    conn = sqlite3.connect(":memory:")
    return CaduceanTrajectoryRecorder(db_conn=conn)


def _seed(rec, session="s1", step=1, u=0.3, axis=None,
          execution_domain="der", topic_domain="web"):
    """Seed one trajectory row via the REAL record() path (schema + insert)."""
    if axis == "execution_domain":
        rec.record(session_id=session, step_num=step, x=0.1, y=0.2, xi=0.3,
                   u=u, action=0, outcome="success", eml_after=1.2,
                   execution_domain=execution_domain, topic_domain="web")
    elif axis == "topic_domain":
        rec.record(session_id=session, step_num=step, x=0.1, y=0.2, xi=0.3,
                   u=u, action=0, outcome="success", eml_after=1.2,
                   execution_domain="der", topic_domain=topic_domain)
    else:
        rec.record(session_id=session, step_num=step, x=0.1, y=0.2, xi=0.3,
                   u=u, action=0, outcome="success", eml_after=1.2,
                   execution_domain=execution_domain, topic_domain=topic_domain)


# ── AC1: aggregation keyed on the ontology axes ──────────────────────────


def test_execution_domain_aggregate_separates_domains():
    rec = _make_recorder()
    _seed(rec, step=1, u=0.10, execution_domain="der", topic_domain="web")
    _seed(rec, step=2, u=0.95, execution_domain="der", topic_domain="web")
    _seed(rec, step=3, u=0.60, execution_domain="research", topic_domain="ai")

    agg = rec.compute_domain_aggregates("s1", axis="execution_domain")
    assert set(agg.keys()) == {"der", "research"}
    # der: |u| = 0.10 (split zone) + 0.95 (converged) -> avg 0.525, conv 1/2
    der = agg["der"]
    assert der.n == 2
    assert der.avg_u_mag == pytest.approx(0.525, abs=1e-4)
    assert der.convergence_rate == pytest.approx(0.5)
    assert der.oscillation_rate == pytest.approx(0.0)
    assert der.split_count == 1
    assert der.collapse_count == 1
    # research: |u| = 0.60 (oscillating band) -> avg 0.6, osc 1/1
    res = agg["research"]
    assert res.n == 1  # one-sample domain REPORTED with n=1 (edge case)
    assert res.oscillation_rate == pytest.approx(1.0)
    assert res.split_count == 0
    assert res.collapse_count == 0


def test_topic_domain_aggregate_keys_on_topic():
    rec = _make_recorder()
    _seed(rec, step=1, u=0.95, topic_domain="web")
    _seed(rec, step=2, u=0.20, topic_domain="ai")
    agg = rec.compute_domain_aggregates("s1", axis="topic_domain")
    assert set(agg.keys()) == {"web", "ai"}
    assert agg["web"].collapse_count == 1
    assert agg["ai"].split_count == 1


# ── AC2: read-only signal surface ────────────────────────────────────────


def test_aggregate_exposes_readonly_dict_signal():
    rec = _make_recorder()
    _seed(rec, step=1, u=0.80)
    agg = rec.compute_domain_aggregates("s1")
    d = agg["der"].as_dict()
    assert d["domain"] == "der"
    assert d["axis"] == "execution_domain"
    assert d["n"] == 1
    assert isinstance(d["avg_u_mag"], float)
    assert isinstance(d["oscillation_rate"], float)
    assert isinstance(d["split_count"], int)
    assert isinstance(d["collapse_count"], int)


# ── AC3: edges — empty, absent, one-sample, never raises ─────────────────


def test_no_rows_returns_absent_not_zero():
    rec = _make_recorder()
    assert rec.compute_domain_aggregates("no-such-session") == {}


def test_pre_ontology_store_no_axis_column_returns_empty():
    conn = sqlite3.connect(":memory:")
    # legacy schema WITHOUT the ontology axes (pre-T22). Construction migrates
    # via idempotent ALTER (verified in the migration test below), so drop the
    # added columns to exercise the genuinely-absent path honestly.
    conn.execute(
        "CREATE TABLE caducean_trajectories ("
        " id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, step_num INTEGER, "
        " x REAL, y REAL, xi REAL, u REAL, action INTEGER, outcome TEXT, "
        " eml_after REAL, recommendation INTEGER, domain TEXT DEFAULT 'general')"
    )
    conn.execute(
        "INSERT INTO caducean_trajectories (session_id, u) VALUES ('s1', 0.5)"
    )
    rec = CaduceanTrajectoryRecorder(db_conn=conn)
    conn.execute("ALTER TABLE caducean_trajectories DROP COLUMN execution_domain")
    conn.execute("ALTER TABLE caducean_trajectories DROP COLUMN topic_domain")
    conn.commit()
    assert rec.compute_domain_aggregates("s1") == {}
    assert rec.compute_domain_aggregates("s1", axis="topic_domain") == {}


def test_aggregation_never_raises_on_bad_state():
    rec = _make_recorder()
    # u as text (corrupt row) must not raise — the aggregation skips/logs
    conn = rec._conn
    conn.execute(
        "INSERT INTO caducean_trajectories (session_id, u, execution_domain, "
        " topic_domain) VALUES ('s1', 'not-a-number', 'der', 'web')"
    )
    conn.commit()
    agg = rec.compute_domain_aggregates("s1")  # must not raise
    # the corrupt row is skipped; absent, not zero (never an error)
    assert isinstance(agg, dict)


# ── band classifier: same physics as the narration thresholds ────────────


def test_band_classifier_uses_production_bands():
    # U_SPLIT=0.5 / U_CONVERGED=0.85 — must match der_constants semantics
    assert _u_band(0.10) == "split_zone"
    assert _u_band(0.50) == "split_zone"     # at/below split -> split zone
    assert _u_band(0.51) == "oscillating"
    assert _u_band(0.84) == "oscillating"
    assert _u_band(0.85) == "converged"      # at/above converged
    assert _u_band(0.99) == "converged"


# ── schema: the two axes land on the trajectory row via record() ─────────


def test_record_persists_ontology_axes():
    rec = _make_recorder()
    _seed(rec, step=1, u=0.40, execution_domain="research",
          topic_domain="security")
    row = rec._conn.execute(
        "SELECT execution_domain, topic_domain FROM caducean_trajectories "
        "WHERE session_id = 's1'"
    ).fetchone()
    assert row == ("research", "security")


def test_record_defaults_axes_when_absent():
    rec = _make_recorder()
    rec.record(session_id="s1", step_num=1, x=0.1, y=0.2, xi=0.3, u=0.4,
               action=0, outcome="success", eml_after=1.2)  # no axes passed
    row = rec._conn.execute(
        "SELECT execution_domain, topic_domain FROM caducean_trajectories "
        "WHERE session_id = 's1'"
    ).fetchone()
    # legacy caller -> both axes fall back to the legacy `domain` value
    assert row == ("general", "general")


# ── idempotent ALTER: pre-T22 stores gain the columns, no data loss ──────


def test_pre_t22_store_migrates_without_losing_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE caducean_trajectories ("
        " id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, step_num INTEGER, "
        " x REAL, y REAL, xi REAL, u REAL, action INTEGER, outcome TEXT, "
        " eml_after REAL, recommendation INTEGER, domain TEXT DEFAULT 'general')"
    )
    conn.execute(
        "INSERT INTO caducean_trajectories (session_id, u, domain) "
        "VALUES ('s1', 0.3, 'general')"
    )
    rec = CaduceanTrajectoryRecorder(db_conn=conn)  # runs the idempotent ALTERs
    cols = {r[1] for r in conn.execute("PRAGMA table_info(caducean_trajectories)")}
    assert "execution_domain" in cols
    assert "topic_domain" in cols
    # legacy row survived the migration
    assert rec.trajectory_count() == 1
