"""Wave E (spec research-memory-chain-browser D9): typed execution events on the
Immortus chain, cases, staleness and contradiction - driven through the real
chain writer (Python engine on a temp store), no stand-ins for the store."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.gateway.iris_ffi as _ffi
from backend.memory import memory_events as me


@pytest.fixture()
def store(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="memev-")) / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(tmp), key_hex="00" * 32)
    monkeypatch.setattr(_ffi, "_engine", eng)
    conn = sqlite3.connect(str(tmp), check_same_thread=False)
    yield conn
    conn.close()
    eng._conn.close()


def _events(conn, case_id=None):
    sql = "SELECT nbl_outcome, result FROM memory_chain WHERE nbl_outcome LIKE 'event:%'"
    args = ()
    if case_id:
        sql += " AND file_path = ?"
        args = (case_id,)
    return [(o[6:], json.loads(r)) for o, r in conn.execute(sql + " ORDER BY rowid", args)]


ERR = 'Traceback (most recent call last):\n  File "C:\\x\\a.py", line 12\nAssertionError: expected 3 got 2'


def test_bug_dead_ends_fix_verified_fix_lesson_in_time_order(store):
    t = "s1:turn1"
    assert me.record_step(store, thread_id="s1", task_id=t, step_id="1", tool="run_command",
                          params={"command": "pytest tests/test_a.py"}, success=False,
                          verified="FAILED", error_text=ERR, description="run tests") == ["BUG"]
    bad = {"path": "a.py", "old": "x", "new": "y"}
    assert me.record_step(store, thread_id="s1", task_id=t, step_id="2", tool="edit_file",
                          params=bad, success=False, verified="FAILED",
                          error_text="no match", description="edit a.py") == ["DEAD_END"]
    # The same failed action again: counted as a repeated dead end.
    me.record_step(store, thread_id="s1", task_id=t, step_id="3", tool="edit_file", params=bad,
                   success=False, verified="FAILED", error_text="no match", description="edit a.py")
    assert me.record_step(store, thread_id="s1", task_id=t, step_id="4", tool="edit_file",
                          params={"path": "a.py"}, success=True, verified="VERIFIED",
                          description="fix the off-by-one in a.py") == ["FIX"]
    assert me.record_task_end(store, thread_id="s1", task_id=t, success=True) == [
        "VERIFIED_FIX", "LESSON"]

    case = store.execute("SELECT case_id, status, depends_on, dead_end_repeats, verified_count, "
                         "open_task, falsify_if FROM memory_cases").fetchall()
    assert len(case) == 1
    case_id, status, deps, repeats, vcount, open_task, falsify = case[0]
    assert status == "verified" and vcount == 1 and open_task is None
    assert "a.py" in json.loads(deps)
    assert repeats == 1
    assert falsify and "recurs" in falsify
    kinds = [k for k, _ in _events(store, case_id)]
    assert kinds == ["BUG", "DEAD_END", "DEAD_END", "FIX", "VERIFIED_FIX", "LESSON"]
    lesson = _events(store, case_id)[-1][1]
    assert lesson["candidate"] is True and lesson["author"] == "model"
    assert lesson["provenance"]["case"] == case_id


def test_dependency_edit_makes_the_case_stale_and_recurrence_demotes_it(store):
    me.record_step(store, thread_id="s1", task_id="s1:a", step_id="1", tool="run_command",
                   params={"command": "pytest"}, success=False, verified="FAILED", error_text=ERR)
    me.record_step(store, thread_id="s1", task_id="s1:a", step_id="2", tool="edit_file",
                   params={"path": "a.py"}, success=True, verified="VERIFIED", description="fix")
    me.record_task_end(store, thread_id="s1", task_id="s1:a", success=True)

    # Another task edits the file the fix depends on.
    me.record_step(store, thread_id="s2", task_id="s2:b", step_id="1", tool="write_file",
                   params={"path": "a.py"}, success=True, verified="VERIFIED", description="rewrite")
    assert store.execute("SELECT status FROM memory_cases").fetchone()[0] == "stale"

    # The same failure comes back: a contradiction, history kept.
    assert me.record_step(store, thread_id="s3", task_id="s3:c", step_id="1", tool="run_command",
                          params={"command": "pytest"}, success=False, verified="FAILED",
                          error_text=ERR.replace("12", "40")) == ["BUG"]
    status, contradictions = store.execute(
        "SELECT status, contradictions FROM memory_cases").fetchone()
    assert status == "demoted" and contradictions == 1
    kinds = [k for k, _ in _events(store)]
    assert kinds.count("VERIFIED_FIX") == 1 and kinds[-1] == "BUG"
    assert _events(store)[-1][1].get("contradicts") is True


def test_a_passing_test_command_is_outside_evidence(store):
    t = "s1:t"
    me.record_step(store, thread_id="s1", task_id=t, step_id="1", tool="run_command",
                   params={"command": "pytest"}, success=False, verified="FAILED", error_text=ERR)
    me.record_step(store, thread_id="s1", task_id=t, step_id="2", tool="edit_file",
                   params={"path": "a.py"}, success=True, verified="VERIFIED", description="fix")
    out = me.record_step(store, thread_id="s1", task_id=t, step_id="3", tool="run_command",
                         params={"command": "python -m pytest tests"}, success=True,
                         verified="VERIFIED", description="rerun")
    assert "VERIFIED_FIX" in out
    ev = me.session_evidence(store, "s1")
    assert "test_pass" in ev["kinds"] and "a.py" in ev["depends_on"] and "2" in ev["verified_steps"]


def test_events_are_written_off_the_answer_path(monkeypatch, store):
    """A blocked memory_events lane never delays the step finalize."""
    from backend.agent.agent_kernel import _memory_events_submit

    release = threading.Event()
    ran = threading.Event()

    def _blocked(conn, **kw):
        release.wait(10)
        ran.set()
        return []

    monkeypatch.setattr(me, "record_step", _blocked)
    owner = SimpleNamespace(_memory_interface=SimpleNamespace(_mycelium=SimpleNamespace(_conn=store)))
    t0 = time.monotonic()
    _memory_events_submit(owner, "record_step", thread_id="s1", task_id="s1:x", step_id="1",
                          tool="run_command", params={}, success=False, verified="FAILED")
    assert time.monotonic() - t0 < 0.5
    assert not ran.is_set()
    release.set()
    assert ran.wait(10)


def test_case_trail_only_for_a_matching_failure(store):
    me.record_step(store, thread_id="s1", task_id="s1:a", step_id="1", tool="run_command",
                   params={"command": "pytest"}, success=False, verified="FAILED", error_text=ERR)
    me.record_step(store, thread_id="s1", task_id="s1:a", step_id="2", tool="edit_file",
                   params={"path": "a.py"}, success=True, verified="VERIFIED",
                   description="fix the off-by-one in a.py")
    me.record_task_end(store, thread_id="s1", task_id="s1:a", success=True)
    trail = me.case_trail(store, "run_command", ERR.replace("12", "99"))
    assert "KNOWN CASE" in trail and "off-by-one" in trail and len(trail) <= 400
    assert me.case_trail(store, "run_command", "ModuleNotFoundError: no module named zz") == ""
