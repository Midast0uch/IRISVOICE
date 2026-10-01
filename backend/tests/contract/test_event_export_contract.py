"""Trajectory export + reward v1 + curation report (EVENT_TAXONOMY sections 7 and 8, step 4).

The reward is DERIVED, never stored, and SUCCESS-GATED: a run the verifier liked but
nobody outside confirmed earns 0.0 - and outside evidence counts only on a label that is
a fact (``counts_as_outside_evidence``: label_source rule or user), never an Oracle/Brain
guess. Real ``emit_event`` / ``record_step`` / ``record_task_end`` on temp stores."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import backend.gateway.iris_ffi as _ffi
from backend.memory import event_export as ex
from backend.memory import memory_events as me

_REPO = Path(__file__).resolve().parents[3]


@pytest.fixture()
def store(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="memexp-")) / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(tmp), key_hex="00" * 32)
    monkeypatch.setattr(_ffi, "_engine", eng)
    conn = sqlite3.connect(str(tmp), check_same_thread=False)
    me.ensure_schema(conn)
    yield conn
    conn.close()
    eng._conn.close()


def _run(store, task, steps=2, finish=True):
    """A task that hits an error then fixes it; ``finish`` adds task completion (outside evidence)."""
    me.record_step(store, thread_id="s1", task_id=task, step_id="1", tool="run_command",
                   params={"command": "pytest"}, success=False, verified="FAILED",
                   error_text="AssertionError: expected 3 got 2")
    for n in range(2, steps + 1):
        me.record_step(store, thread_id="s1", task_id=task, step_id=str(n), tool="edit_file",
                       params={"path": "a.py"}, success=True, verified="VERIFIED", description="fix")
    if finish:
        me.record_task_end(store, thread_id="s1", task_id=task, success=True)


def test_a_run_the_verifier_liked_but_nobody_outside_confirmed_earns_nothing(store):
    _run(store, "s1:liked", finish=False)
    out = ex.export_episode(store, "s1:liked")
    labels = [e["label"] for e in out["events"]]
    assert "BUG" in labels and "FIX" in labels                     # the verifier liked it
    assert not any(l.startswith("VERIFIED_") for l in labels)
    assert out["reward"]["success"] is False
    assert out["reward"]["reward"] == 0.0


def test_task_completion_is_outside_evidence_and_makes_the_episode_a_success(store):
    _run(store, "s1:done")
    out = ex.export_episode(store, "s1:done")
    r = out["reward"]
    assert r["success"] is True and r["version"] == ex.REWARD_VERSION == 1
    assert 0.5 < r["reward"] <= 1.0 and r["evidence"] == ["completion"]
    # Derived, never stored: the table holds no reward column.
    cols = {c[1] for c in store.execute("PRAGMA table_info(memory_events)")}
    assert not any("reward" in c for c in cols)


def test_events_come_out_in_order_with_their_parsed_blobs(store):
    _run(store, "s1:done")
    events = ex.export_episode(store, "s1:done")["events"]
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)
    verified = next(e for e in events if e["label"] == "VERIFIED_FIX")
    assert verified["links"]["case"] and verified["evidence"] == "completion"
    assert isinstance(verified["payload"], dict) and verified["label_source"] == "rule"
    assert ex.export_episode(store, "s1:none")["events"] == []
    assert ex.export_episode(store, "s1:none")["reward"]["reward"] is None


def test_among_successes_the_cheaper_episode_ranks_higher_and_every_success_beats_a_failure(store):
    _run(store, "s1:cheap", steps=2)
    _run(store, "s1:dear", steps=9)
    _run(store, "s1:liked", finish=False)
    cheap, dear, liked = (ex.export_episode(store, t)["reward"] for t in ("s1:cheap", "s1:dear", "s1:liked"))
    assert cheap["reward"] > dear["reward"] > 0.5 > liked["reward"] == 0.0
    assert cheap["cost"]["steps"] < dear["cost"]["steps"]


@pytest.mark.parametrize("label_source", ["oracle", "brain"])
def test_outside_evidence_on_a_guessed_label_is_not_outside_evidence(store, label_source):
    """An Oracle-typed CONFIRMATION (evidence 'user') is a guess about a user message: it must
    never turn a verifier-liked run into a success. The same holds for a VERIFIED_* guess."""
    me.record_step(store, thread_id="s1", task_id="s1:g", step_id="1", tool="edit_file",
                   params={"path": "a.py"}, success=True, verified="VERIFIED")
    me.emit_event(store, label="CONFIRMATION", evidence="user", thread_id="s1", episode_id="s1:g",
                  label_source=label_source, label_confidence=0.9)
    me.emit_event(store, label="VERIFIED_RESOLUTION", evidence="completion", thread_id="s1",
                  episode_id="s1:g", label_source=label_source, label_confidence=0.9)
    r = ex.export_episode(store, "s1:g")["reward"]
    assert r["success"] is False and r["reward"] == 0.0


def test_a_user_labeled_verified_event_counts(store):
    me.emit_event(store, label="VERIFIED_RESOLUTION", evidence="user", thread_id="s1",
                  episode_id="s1:u", label_source="user")
    assert ex.export_episode(store, "s1:u")["reward"]["success"] is True


def _seed_report_store(store):
    _run(store, "s1:done")                                   # trusted outside evidence
    _run(store, "s1:liked", finish=False)                    # inside evidence only
    me.emit_event(store, label="CONFIRMATION", evidence="user", thread_id="s1", episode_id="s1:guess",
                  label_source="oracle")                     # guessed outside evidence only
    me.emit_event(store, label="FORM_REJECTED", family_hint=None, evidence="claim", thread_id="s1",
                  episode_id="s1:liked")                     # Layer 3: unclassified
    me.record_recall_delivered(store, thread_id="s1", task_id="s1:done", step_id="2", source="neighbors",
                               recall_trace_id="rt-1")
    me.record_recall_delivered(store, thread_id="s1", task_id="s1:done", step_id="3", source="neighbors",
                               recall_trace_id="rt-2")
    me.record_step(store, thread_id="s1", task_id="s1:done", step_id="2", tool="edit_file",
                   params={"path": "a.py"}, success=True, verified="VERIFIED", recall_trace_ids=["rt-1"])
    store.execute(
        "INSERT INTO memory_events (event_id, ts, schema_version, label, evidence, label_source, family) "
        "VALUES ('x1', 1, 1, 'LANDMARK_PROMOTED', 'test', 'rule', 'memory'), "
        "('x2', 2, 1, 'LANDMARK_DEMOTED', 'verifier', 'rule', 'memory')")
    store.commit()


def test_the_report_counts_the_section_8_measurements(store):
    _seed_report_store(store)
    rep = ex.curation_report(store)
    assert rep["by_family"]["problem"] >= 3 and rep["label_source"]["oracle"] == 1
    assert rep["unclassified"]["n"] == 1 and rep["unclassified"]["top_labels"][0]["label"] == "FORM_REJECTED"
    assert rep["unclassified"]["rate"] == round(1 / rep["events"], 4)
    eps = rep["episodes"]
    assert eps["total"] == 3 and eps["with_outside_evidence"] == 1          # s1:done only
    assert eps["guessed_outside_only"] == 1                                 # s1:guess: reported apart
    assert rep["recall_attribution"] == {"delivered": 2, "helped": 1, "misled": 0, "coverage": 0.5}
    assert rep["landmarks"] == {"promoted": 1, "stale": 0, "demoted": 1}


def test_the_report_on_an_empty_store_says_so():
    c = sqlite3.connect(":memory:")
    assert ex.curation_report(c) == {"events": 0}
    me.ensure_schema(c)
    assert ex.curation_report(c)["events"] == 0
    c.close()


def test_the_script_runs_read_only_on_a_temp_store(store):
    _seed_report_store(store)
    db_path = store.execute("PRAGMA database_list").fetchone()[2]
    script = _REPO / "scripts" / "event_curation_report.py"
    text = subprocess.run([sys.executable, str(script), "--db", db_path], capture_output=True,
                          text=True, timeout=120, cwd=str(_REPO))
    assert text.returncode == 0, text.stderr
    assert "unclassified (family NULL): 1" in text.stdout
    assert "guessed-outside only" in text.stdout and "coverage=50.0%" in text.stdout
    machine = subprocess.run([sys.executable, str(script), "--db", db_path, "--json"],
                             capture_output=True, text=True, timeout=120, cwd=str(_REPO))
    assert json.loads(machine.stdout)["episodes"]["with_outside_evidence"] == 1
    before = store.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0]
    assert before == json.loads(machine.stdout)["events"]            # it wrote nothing
