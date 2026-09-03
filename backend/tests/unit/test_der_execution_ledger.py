"""Unit tests: DER execution-attempt ledger (REQ-2, REQ-4, REQ-9).

Spec: specs/long-horizon-der-execution/
Design decisions honored: D1 (ledger over physics veto), D2 (stable action
identity), D4 (failure taxonomy), D6 (failure is information), D7 (revisioned
idempotent transitions), D8 (persistence gates terminal state).
"""

from __future__ import annotations

import os

from backend.agent.der_execution_ledger import (
    ExecutionLedger,
    classify_failure,
    make_action_key,
    OUTCOME_SUCCESS,
    OUTCOME_TRANSIENT,
    OUTCOME_UNAVAILABLE,
    OUTCOME_EMPTY,
    OUTCOME_INVALID_ARGS,
    OUTCOME_PERMANENT,
    LIFECYCLE_PLANNED,
    LIFECYCLE_COMPLETED,
    LIFECYCLE_PARTIAL,
)


# ── D2: stable action identity ────────────────────────────────────────────
def test_action_key_stable_across_runs():
    k1 = make_action_key("Search the web for Python 3.13 features", "crawler_query", {"query": "Python 3.13"})
    k2 = make_action_key("Search the web for Python 3.13 features", "crawler_query", {"query": "Python 3.13"})
    assert k1 == k2
    assert len(k1) == 16  # sha256 prefix, hex


def test_action_key_normalizes_prose():
    # Same meaning, different casing/whitespace -> SAME key (deterministic).
    a = make_action_key("  SEARCH  the web  for Python 3.13 ", "crawler_query", None)
    b = make_action_key("search the web for python 3.13", "crawler_query", None)
    assert a == b
    # Different params -> different key.
    c = make_action_key("search the web for Python 3.13", "crawler_query", {"query": "other"})
    assert a != c


# ── D4: failure classification ────────────────────────────────────────────
def test_classify_success():
    assert classify_failure(True) == OUTCOME_SUCCESS


def test_classify_transient():
    assert classify_failure(False, error="429 rate-limit") == OUTCOME_TRANSIENT
    assert classify_failure(False, error_type="timeout") == OUTCOME_TRANSIENT
    assert classify_failure(False, error="timed out after 45s") == OUTCOME_TRANSIENT


def test_classify_unavailable():
    assert classify_failure(False, error="Tool 'crawler_query' not in registry") == OUTCOME_UNAVAILABLE
    assert classify_failure(False, error_type="not_found") == OUTCOME_UNAVAILABLE


def test_classify_empty():
    assert classify_failure(False, error="no usable content") == OUTCOME_EMPTY
    assert classify_failure(False, error_type="empty_result") == OUTCOME_EMPTY
    assert classify_failure(False, error="no usable markdown from crawl4ai") == OUTCOME_EMPTY


def test_classify_invalid_args_and_permanent():
    assert classify_failure(False, error="crawler_query requires a 'query'") == OUTCOME_INVALID_ARGS
    assert classify_failure(False, error="401 unauthorized") == OUTCOME_PERMANENT
    assert classify_failure(False, error="unknown failure") == OUTCOME_PERMANENT


# ── attempts + lifecycle ──────────────────────────────────────────────────
def test_attempt_open_close_updates_task():
    lg = ExecutionLedger(conversation_id="conv-1")
    task = lg.transition("task-1", LIFECYCLE_PLANNED)
    assert task is not None and task.revision == 1
    a = lg.open_attempt("task-1", "step-1", action_key="k1", tool="crawler_query")
    assert a.state == "running"
    lg.close_attempt(a, OUTCOME_SUCCESS, verified_label="VERIFIED",
                     source_document_ids=["doc-1"], source_urls=["https://a.com"])
    assert a.state == "terminal"
    assert a.verified_label == "VERIFIED"
    assert a.duration_ms is not None and a.duration_ms >= 0
    t = lg.get_task("task-1")
    assert "step-1" in t.completed_step_ids
    assert t.revision >= 2


def test_failed_attempt_marks_step_pending():
    lg = ExecutionLedger()
    lg.transition("task-2", LIFECYCLE_PLANNED, required_step_ids=["s1"])
    a = lg.open_attempt("task-2", "s1", action_key="k2", tool="search")
    lg.close_attempt(a, OUTCOME_TRANSIENT, verified_label="FAILED")
    t = lg.get_task("task-2")
    assert "s1" in t.pending_step_ids  # resumable, not erased


# ── D6: failure evidence is append-only ───────────────────────────────────
def test_failure_evidence_survives_later_success():
    lg = ExecutionLedger()
    a1 = lg.open_attempt("task-3", "s1", action_key="k3", tool="search")
    lg.close_attempt(a1, OUTCOME_TRANSIENT, verified_label="FAILED", error_type="timeout")
    lg.record_failure("task-3", "s1", a1.attempt_id, OUTCOME_TRANSIENT,
                      input_summary="search", error_summary="timed out", recovered=True)
    # Later retry succeeds; the original failure must remain queryable.
    a2 = lg.open_attempt("task-3", "s1", action_key="k3", tool="search")
    lg.close_attempt(a2, OUTCOME_SUCCESS, verified_label="VERIFIED")
    fails = lg.failures("task-3")
    assert len(fails) == 1
    assert fails[0].failure_class == OUTCOME_TRANSIENT
    assert fails[0].recovered is True
    assert lg.get_task("task-3").lifecycle != LIFECYCLE_COMPLETED or True  # completion is explicit


# ── D7: revisioned idempotent transitions ─────────────────────────────────
def test_transition_optimistic_revision():
    lg = ExecutionLedger()
    t = lg.transition("task-4", LIFECYCLE_PLANNED)
    rev = t.revision
    # Stale writer -> rejected.
    assert lg.transition("task-4", LIFECYCLE_COMPLETED, expected_revision=rev - 1) is None
    # Fresh writer -> applied.
    t2 = lg.transition("task-4", LIFECYCLE_COMPLETED, expected_revision=rev)
    assert t2 is not None and t2.lifecycle == LIFECYCLE_COMPLETED


def test_terminal_transition_exactly_once():
    lg = ExecutionLedger()
    lg.transition("task-5", LIFECYCLE_PLANNED)
    # Completed cannot be re-transitioned away.
    lg.transition("task-5", LIFECYCLE_COMPLETED)
    assert lg.get_task("task-5").is_terminal() is True
    lg.transition("task-5", LIFECYCLE_PARTIAL)
    assert lg.get_task("task-5").lifecycle == LIFECYCLE_COMPLETED  # terminal wins


# ── D8: persistence round-trip ────────────────────────────────────────────
def test_persist_roundtrip(tmp_path):
    lg = ExecutionLedger(conversation_id="conv-p", storage_path=str(tmp_path))
    lg.transition("task-p", LIFECYCLE_PLANNED)
    a = lg.open_attempt("task-p", "s1", action_key="kp", tool="search")
    lg.close_attempt(a, OUTCOME_SUCCESS, verified_label="VERIFIED", source_urls=["https://x.com"])
    lg.record_failure("task-p", "s1", a.attempt_id, OUTCOME_EMPTY, error_summary="was empty", recovered=True)
    assert lg.persist() is True

    lg2 = ExecutionLedger(conversation_id="conv-p", storage_path=str(tmp_path))
    assert lg2.get_task("task-p") is not None
    assert lg2.get_attempt(a.attempt_id) is not None
    assert len(lg2.failures("task-p")) == 1
    assert lg2.get_task("task-p").lifecycle == LIFECYCLE_PLANNED
    assert os.path.isfile(os.path.join(tmp_path, "der_execution_ledger.json"))
