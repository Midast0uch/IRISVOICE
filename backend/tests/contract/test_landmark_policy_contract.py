"""Wave E2 (spec research-memory-chain-browser D9; brief 7.9): landmark tiers.

A landmark says a claim is TRUE (tier + evidence); activation_count says how
USEFUL its recall has been. Only outside evidence promotes; the model's own
claim never does; usefulness alone never makes a candidate permanent; a changed
dependency makes it stale; a contradiction demotes it and keeps its evidence.
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium.landmark import (
    PROMOTE_MIN_EVIDENCE,
    LandmarkIndex,
    add_landmark_evidence,
    demote_landmarks_for_thread,
    ensure_landmark_policy_columns,
    mark_landmarks_stale_by_dependency,
    set_landmark_falsification,
)
from backend.memory.mycelium.spaces import PERMANENCE_THRESHOLD


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    initialise_mycelium_schema(c)
    ensure_landmark_policy_columns(c)
    c.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, "
        "traversal_sequence, cumulative_score, activation_count, is_permanent, conversation_ref, "
        "absorbed, created_at) VALUES ('lm1', 'fix a.py', 'tc', '[]', '[]', 0.9, 0, 0, 's1', 0, ?)",
        (time.time(),),
    )
    c.commit()
    yield c
    c.close()


def _tier(c):
    return c.execute("SELECT tier FROM mycelium_landmarks WHERE landmark_id='lm1'").fetchone()[0]


def test_a_new_landmark_is_a_candidate(conn):
    assert _tier(conn) == "candidate"


def test_one_kind_does_not_promote_two_do_and_a_model_claim_never(conn):
    assert PROMOTE_MIN_EVIDENCE == 2
    assert add_landmark_evidence(conn, "lm1", "model_claim", "I fixed it", "s1") is None
    assert add_landmark_evidence(conn, "lm1", "task_complete", "ep", "s1") == "candidate"
    # The same kind in the same session again is not independent evidence.
    assert add_landmark_evidence(conn, "lm1", "task_complete", "ep", "s1") == "candidate"
    assert add_landmark_evidence(conn, "lm1", "test_pass", "pytest", "s1") == "landmark"
    ev = json.loads(conn.execute("SELECT evidence FROM mycelium_landmarks").fetchone()[0])
    assert {e["kind"] for e in ev} == {"task_complete", "test_pass"}


def test_usefulness_alone_never_makes_a_candidate_permanent(conn):
    idx = LandmarkIndex(conn)
    for _ in range(PERMANENCE_THRESHOLD + 2):
        idx.activate("lm1")
    assert conn.execute("SELECT is_permanent FROM mycelium_landmarks").fetchone()[0] == 0
    add_landmark_evidence(conn, "lm1", "task_complete", "ep", "s1")
    add_landmark_evidence(conn, "lm1", "user_confirm", "yes", "s1")
    idx.activate("lm1")
    assert conn.execute("SELECT is_permanent FROM mycelium_landmarks").fetchone()[0] == 1


def test_dependency_edit_makes_it_stale_and_new_evidence_restores_it(conn):
    set_landmark_falsification(conn, "lm1", ["backend/a.py", "cmd:pytest"], ["step-2"])
    add_landmark_evidence(conn, "lm1", "task_complete", "ep", "s1")
    add_landmark_evidence(conn, "lm1", "test_pass", "pytest", "s1")
    row = conn.execute("SELECT traversal_sequence, falsify_if FROM mycelium_landmarks").fetchone()
    assert json.loads(row[0]) == ["step-2"] and "backend/a.py" in row[1]
    assert mark_landmarks_stale_by_dependency(conn, "backend/a.py") == 1
    assert _tier(conn) == "stale"
    assert add_landmark_evidence(conn, "lm1", "test_pass", "pytest again", "s2") == "landmark"


def test_a_contradiction_demotes_and_keeps_the_history(conn):
    add_landmark_evidence(conn, "lm1", "task_complete", "ep", "s1")
    add_landmark_evidence(conn, "lm1", "test_pass", "pytest", "s1")
    assert demote_landmarks_for_thread(conn, "s1", "case abc recurred") == 1
    tier, contradictions, ev, falsify = conn.execute(
        "SELECT tier, contradictions, evidence, falsify_if FROM mycelium_landmarks").fetchone()
    assert tier == "demoted" and contradictions == 1
    assert len(json.loads(ev)) == 2 and "recurred" in falsify
    # Demoted stays demoted: its history is the point.
    assert add_landmark_evidence(conn, "lm1", "user_confirm", "yes", "s3") == "demoted"


def test_bootstrap_permanent_landmarks_become_tier_landmark_on_migration():
    c = sqlite3.connect(":memory:")
    initialise_mycelium_schema(c)
    # initialise_mycelium_schema already ran the migration on an empty table;
    # simulate a LIVE store that predates it.
    for col in ("tier", "evidence", "depends_on", "falsify_if", "last_verified", "contradictions"):
        try:
            c.execute(f"ALTER TABLE mycelium_landmarks DROP COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    c.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, "
        "traversal_sequence, cumulative_score, activation_count, is_permanent, absorbed, created_at) "
        "VALUES ('b1', 'boot', 'bootstrap', '[]', '[]', 1.0, 3, 1, 0, 0), "
        "('r1', 'runtime', 'tc', '[]', '[]', 0.6, 9, 1, 0, 0)"
    )
    ensure_landmark_policy_columns(c)
    tiers = dict(c.execute("SELECT landmark_id, tier FROM mycelium_landmarks"))
    assert tiers == {"b1": "landmark", "r1": "candidate"}
