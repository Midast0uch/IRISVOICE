"""MEMORY rule emitters (docs/Design/EVENT_TAXONOMY.md, build step 2): RECALL_DELIVERED with a
recall_trace_id, RECALL_HELPED / RECALL_MISLED attributed only to the step that received the
recall, and LANDMARK_PROMOTED / _STALE / _DEMOTED from the landmark policy functions (evidence =
the policy kind mapped into the alphabet). Real writer, temp stores."""
from __future__ import annotations

import sqlite3
import time

import pytest

from backend.memory import memory_events as me
from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium.landmark import (
    add_landmark_evidence,
    demote_landmarks_for_thread,
    ensure_landmark_policy_columns,
    mark_landmarks_stale_by_dependency,
    set_landmark_falsification,
)
from backend.tests.contract.test_event_emitters_knowledge_contract import _rows as _rows_now, store  # noqa: F401
from backend.utils.durability_queue import lane


def _rows(conn, label=None):
    """Landmark events are written by the memory_events lane (one writer per
    connection); read after it drains."""
    assert lane("memory_events").flush(10.0)
    return _rows_now(conn, label)


# ── MEMORY ──────────────────────────────────────────────────────────────────

def test_recall_delivered_is_typed_with_its_trace_and_refs_only(store):
    me.record_recall_delivered(store, thread_id="s1", task_id="s1:t1", step_id="2", source="neighbors",
                               recall_trace_id="rt-aaa", refs=["chain-1", "chain-2"])
    (ev,) = _rows(store, "RECALL_DELIVERED")
    assert (ev["family"], ev["episode_id"], ev["step_index"], ev["evidence"]) == (
        "memory", "s1:t1", "2", "none")
    assert ev["links"] == {"recall_trace_id": "rt-aaa"}
    assert ev["payload"] == {"source": "neighbors", "refs": ["chain-1", "chain-2"]}


def _step(store, step, ok, traces, verified=None):
    return me.record_step(
        store, thread_id="s1", task_id="s1:t1", step_id=step, tool="browser_act",
        params={"target": "m1"}, success=ok, verified=verified or ("VERIFIED" if ok else "FAILED"),
        error_text="" if ok else "boom: it failed", recall_trace_ids=traces)


def test_a_delivered_recall_is_helped_when_its_step_succeeds_and_misled_when_it_fails(store):
    assert "RECALL_HELPED" in _step(store, "2", True, ["rt-ok"])
    assert "RECALL_MISLED" in _step(store, "3", False, ["rt-bad"])
    (h,), (m,) = _rows(store, "RECALL_HELPED"), _rows(store, "RECALL_MISLED")
    assert h["links"]["recall_trace_id"] == "rt-ok" and h["step_index"] == "2"
    assert m["links"]["recall_trace_id"] == "rt-bad" and m["step_index"] == "3"
    assert (h["evidence"], m["evidence"]) == ("verifier", "verifier")  # the verifier ruled
    assert (h["valence"], m["valence"]) == ("advances", "sets_back")


def test_a_trace_is_credited_once_and_a_step_without_traces_credits_nothing(store):
    _step(store, "2", True, ["rt-ok"])
    _step(store, "2", True, ["rt-ok"])        # a retried finalize
    _step(store, "3", True, [])               # nothing was delivered to this step
    _step(store, "4", True, None)
    assert len(_rows(store, "RECALL_HELPED")) == 1


def test_recall_events_never_enter_the_chain(store):
    """A chain row per recall event would feed the NEXT recall (recall of recall)."""
    me.record_recall_delivered(store, thread_id="s1", task_id="s1:t1", step_id="2", source="neighbors",
                               recall_trace_id="rt-x")
    _step(store, "2", True, ["rt-x"])
    chain = store.execute("SELECT nbl_outcome FROM memory_chain WHERE nbl_outcome LIKE 'event:RECALL%'")
    assert chain.fetchall() == []


@pytest.fixture()
def lm_conn():
    # Like the production Mycelium connection: usable from the lane thread.
    c = sqlite3.connect(":memory:", check_same_thread=False)
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


@pytest.mark.parametrize("first,second,alphabet", [
    ("task_complete", "test_pass", "test"),
    ("test_pass", "user_confirm", "user"),
    ("test_pass", "recurrence", "recurrence"),
    ("recurrence", "task_complete", "completion"),
])
def test_promotion_types_the_evidence_that_promoted_it(lm_conn, first, second, alphabet):
    assert add_landmark_evidence(lm_conn, "lm1", first, "r", "s1") == "candidate"
    assert _rows(lm_conn) == []                       # not promoted yet: no event
    assert add_landmark_evidence(lm_conn, "lm1", second, "r", "s1") == "landmark"
    (ev,) = _rows(lm_conn, "LANDMARK_PROMOTED")
    assert (ev["family"], ev["evidence"], ev["valence"]) == ("memory", alphabet, "advances")
    assert ev["payload"]["landmark"] == "lm1" and ev["payload"]["to"] == "landmark"


def test_a_model_claim_never_promotes_and_types_nothing(lm_conn):
    assert add_landmark_evidence(lm_conn, "lm1", "model_claim", "I fixed it", "s1") is None
    assert _rows(lm_conn) == []


def test_stale_and_demoted_are_typed_and_a_restoring_proof_is_a_promotion(lm_conn):
    set_landmark_falsification(lm_conn, "lm1", ["backend/a.py"], ["step-2"])
    add_landmark_evidence(lm_conn, "lm1", "task_complete", "ep", "s1")
    add_landmark_evidence(lm_conn, "lm1", "test_pass", "pytest", "s1")
    assert mark_landmarks_stale_by_dependency(lm_conn, "backend/a.py") == 1
    (stale,) = _rows(lm_conn, "LANDMARK_STALE")
    assert stale["payload"]["path"] == "backend/a.py" and stale["payload"]["landmark"] == "lm1"
    assert mark_landmarks_stale_by_dependency(lm_conn, "backend/zzz.py") == 0   # nothing changed
    assert len(_rows(lm_conn, "LANDMARK_STALE")) == 1
    add_landmark_evidence(lm_conn, "lm1", "user_confirm", "yes", "s2")          # stale -> landmark
    assert len(_rows(lm_conn, "LANDMARK_PROMOTED")) == 2
    assert demote_landmarks_for_thread(lm_conn, "s1", "case abc recurred") == 1
    (dem,) = _rows(lm_conn, "LANDMARK_DEMOTED")
    assert (dem["thread_id"], dem["evidence"], dem["valence"]) == ("s1", "verifier", "sets_back")
    assert demote_landmarks_for_thread(lm_conn, "s1", "again") == 0             # already demoted
    assert len(_rows(lm_conn, "LANDMARK_DEMOTED")) == 1
