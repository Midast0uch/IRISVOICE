"""W4 (owner 2026-11-23): a claim's card must inform, and every conversation a claim is connected to must open.

Measured before: 283 of 389 claims were one "kind" (the coordinate space of their steps); the source chat is kept for 2 of
389, so cards said "not kept", while 252 have events in memory for a conversation that taught or proved them - and only
the snapshot's 48 newest threads could open. Each test FAILS on the code before this change.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from backend.tests.contract.test_memory_api_contract import NOW, env  # noqa: F401  (the fixture)


@pytest.mark.parametrize("text,cls,work", [
    ("SpecEngine built", "bootstrap", "built"),
    ("Which color do I prefer for status indicators? Answer with the color only.", None, "you"),
    ("The project is in C:\\x\\c05. Add a --shout flag to greet.py. With --shout the greeting is printed in upper case.", None, "code"),
    ("Make the tests in test_durations.py pass by implementing parse_duration in durations.py.", None, "code"),
    ("Open https://en.wikipedia.org/wiki/Moon in the live browser, click the link", None, "web"),
    ("The project is in C:\\x. Run main.py in this project and tell me exactly how many lines it prints.", None, "run"),
    ("Read settings.ini and tell me the exact value of retries. Do not change any file.", None, "files"),
    ("Describe the differences between a thread and a process in Python.", None, "words"),
])
def test_a_claim_says_what_kind_of_work_it_is(text, cls, work):
    from backend.memory.surface_queries import claim_work

    assert claim_work(text, cls) == work


def _claim(con, lid, text, ref, evidence):
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
                " cumulative_score, micro_abstract_text, activation_count, conversation_ref, created_at, tier, evidence)"
                " VALUES (?, ?, 'task_x', '[]', '[]', 0.6, NULL, 1, ?, ?, 'landmark', ?)", (lid, text, ref, NOW - 500, json.dumps(evidence)))


def _event(con, eid, thread, ts):
    cols = [r for r in con.execute("PRAGMA table_info(memory_events)")]
    vals = {"event_id": eid, "ts": ts, "schema_version": 1, "thread_id": thread, "family": "tool", "label": "TOOL_OK", "valence": "advances",
            "actor": "agent", "evidence": "test", "payload": "{}", "links": "{}"}
    for c in cols:   # a NOT NULL column without a default gets an empty value
        if c[1] not in vals and c[3] and c[4] is None and not c[5]:
            vals[c[1]] = "" if "CHAR" in (c[2] or "").upper() or "TEXT" in (c[2] or "").upper() else 0
    vals = {k: v for k, v in vals.items() if k in {c[1] for c in cols}}
    con.execute(f"INSERT INTO memory_events ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", list(vals.values()))


def test_the_story_names_what_it_found_and_every_conversation(env):  # noqa: F811
    con = sqlite3.connect(str(env.mem))
    text = "The project is in C:\\x\\demo. Read settings.ini and tell me the exact value of retries"
    _claim(con, "S1", text, "conv-gone-1", [{"kind": "task_complete", "session": "conv-gone-1", "at": NOW - 400},
                                            {"kind": "test_pass", "session": "conv-mem-2", "at": NOW - 300},
                                            {"kind": "recurrence", "session": env.ids["root"], "at": NOW - 200}])
    _event(con, "e-m2-1", "conv-mem-2", NOW - 310)
    _event(con, "e-m2-2", "conv-mem-2", NOW - 300)
    ep = {r[1] for r in con.execute("PRAGMA table_info(episodes)")}
    row = {"id": "ep-s1", "session_id": "conv-mem-2", "task_summary": "Read settings.ini and tell me the exact value of retries",
           "full_content": "[Step 1] reading\n[Step 2] retries is 7.", "outcome_type": "success", "outcome_score": 1.0, "duration_ms": 4000,
           "tool_sequence": json.dumps([{"tool": "read_file", "target": "settings.ini", "success": True}]), "timestamp": "2026-11-20 10:00:00"}
    other = dict(row, id="ep-s2", task_summary="Name three sorting algorithms", full_content="[Step 1] quick, merge, heap")
    for r in (row, other):
        r = {k: v for k, v in r.items() if k in ep}
        con.execute(f"INSERT INTO episodes ({','.join(r)}) VALUES ({','.join('?' * len(r))})", list(r.values()))
    con.commit()
    con.close()
    d = env.client.get("/api/memory/claims/S1/story").json()
    assert d["work"] == "files"
    assert d["found"] == "retries is 7." and d["found_in"] == "conv-mem-2"                 # the run that asked it, not the other task
    assert d["steps"] == [{"tool": "read_file", "target": "settings.ini", "ok": True}]
    assert d["runs"]["n"] == 1 and d["runs"]["ok"] == 1 and d["runs"]["seconds"] == 4.0
    assert d["proof"]["conversations"] == 3
    by = {c["id"]: c for c in d["conversations"]}
    assert by["conv-mem-2"]["opens"] == "memory" and by["conv-mem-2"]["moments"] == 2 and by["conv-mem-2"]["roles"] == ["proved"]
    assert by[env.ids["root"]]["opens"] == "chat" and by[env.ids["root"]]["title"] == "Plan the release"
    assert by["conv-gone-1"]["opens"] is None and "learned" in by["conv-gone-1"]["roles"]    # nothing is left of it: said, not hidden
    assert [c["opens"] for c in d["conversations"]].index(None) == len(d["conversations"]) - 1
    assert d["conversations_open"] == 2 and d["conversations_total"] == 3
    assert env.client.get("/api/memory/claims/NOPE/story").status_code == 404


def test_any_conversation_the_memory_holds_opens_as_a_corridor(env):  # noqa: F811
    con = sqlite3.connect(str(env.mem))
    _event(con, "e-t-1", "conv-old-7", NOW - 900)
    _event(con, "e-t-2", "conv-old-7", NOW - 800)
    con.commit()
    con.close()
    d = env.client.get("/api/memory/thread-model/conv-old-7").json()
    s = d["session"]
    assert s["id"] == "conv-old-7" and s["ghost"] is True and s["started"] < s["ended"]
    assert [e["id"] for e in d["events"]] == ["e-t-1", "e-t-2"]
    snap = env.sq.snapshot(db=env.mem, conv_db=env.cs._DB_PATH)
    assert set(s) >= set(snap["sessions"][0]) - {"sync"}                                    # the snapshot's own session shape
    assert set(d["events"][0]) == set(snap["events"][0])
    kept = env.client.get(f"/api/memory/thread-model/{env.ids['root']}").json()["session"]
    assert kept["ghost"] is False and kept["objective"] == "Plan the release" and kept["messages"]
    assert env.client.get("/api/memory/thread-model/conv-never").status_code == 404
