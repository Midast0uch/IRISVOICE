"""The canonical event record (docs/Design/EVENT_TAXONOMY.md section 7): one typed
row per event in memory_events + a reference row on the Immortus chain; values
outside the closed alphabet are refused, never coerced; other domains use the
generic problem words."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

import backend.gateway.iris_ffi as _ffi
from backend.memory import memory_events as me


@pytest.fixture()
def store(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="memenv-")) / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(tmp), key_hex="00" * 32)
    monkeypatch.setattr(_ffi, "_engine", eng)
    conn = sqlite3.connect(str(tmp), check_same_thread=False)
    me.ensure_schema(conn)
    yield conn
    conn.close()
    eng._conn.close()


def _rows(conn):
    cur = conn.execute("SELECT * FROM memory_events ORDER BY ts, rowid")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def test_emit_writes_the_typed_row_and_a_chain_reference(store):
    eid = me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1",
                        episode_id="t1:turn1", exec_domain="voice", topic_domain="general",
                        sigma_from="1.00,1.00,1.05,0.35", sigma_to="2.00,1.00,1.50,0.20",
                        payload={"text_ref": "msg-9"})
    row = _rows(store)[0]
    assert row["event_id"] == eid
    assert (row["family"], row["label"], row["valence"], row["actor"], row["evidence"]) == (
        "feedback", "CORRECTION", "sets_back", "user", "user")
    assert row["schema_version"] == 1 and row["label_source"] == "rule"
    assert row["hash_signature"] and row["hash_scheme"] == 1
    chain = store.execute(
        "SELECT nbl_outcome, result FROM memory_chain WHERE thread_id='t1'").fetchall()
    assert chain[0][0] == "event:CORRECTION"
    assert json.loads(chain[0][1])["event_id"] == eid


def test_values_outside_the_alphabet_are_refused_not_coerced(store):
    assert me.emit_event(store, label="CORRECTION", evidence="vibes", thread_id="t1") is None
    assert me.emit_event(store, label="CORRECTION", evidence="user", actor="robot",
                         thread_id="t1") is None
    assert _rows(store) == []


def test_an_unknown_label_is_layer_3_kept_with_its_family_hint(store):
    me.emit_event(store, label="FORM_REJECTED", family_hint="problem", evidence="verifier",
                  thread_id="t1")
    row = _rows(store)[0]
    assert row["label"] == "FORM_REJECTED" and row["family"] == "problem"
    assert row["valence"] is None


def test_a_non_coding_failure_uses_the_generic_problem_words(store):
    t = "t1:turn"
    assert me.record_step(store, thread_id="t1", task_id=t, step_id="1", tool="crawler_query",
                          params={"query": "x"}, success=False, verified="FAILED",
                          error_text="walled: 403 challenge") == ["OBSTACLE"]
    assert me.record_step(store, thread_id="t1", task_id=t, step_id="2", tool="browser_act",
                          params={"target": "m3"}, success=True,
                          verified="VERIFIED") == ["RESOLUTION"]
    assert me.record_task_end(store, thread_id="t1", task_id=t, success=True) == [
        "VERIFIED_RESOLUTION", "LESSON"]
    rows = _rows(store)
    labels = [r["label"] for r in rows]
    assert labels == ["OBSTACLE", "RESOLUTION", "VERIFIED_RESOLUTION", "LESSON"]
    ev = {r["label"]: r for r in rows}
    assert ev["OBSTACLE"]["cause_key"] == "no|world|blocked"   # FAULTLINE 'walled'
    assert ev["VERIFIED_RESOLUTION"]["evidence"] == "completion"
    assert ev["LESSON"]["evidence"] == "claim"
    assert ev["RESOLUTION"]["evidence"] == "verifier"
    assert {r["episode_id"] for r in rows} == {t}
