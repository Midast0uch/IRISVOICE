"""The memory and the chat store stay connected (owner 2026-11-23: "text is not kept" for some conversations; moments and
goals without enough information).

Measured before: 46 of the timeline's 48 beads were CLEANED EVALUATION RUNS (the runner deletes its chats by SQL, so no
title and no tombstone was left), the corridor invented message lengths for them, a moment carried no words at all, and 25
conversations held answers without questions. Each test FAILS on the code before this change.
"""
from __future__ import annotations

import json
import sqlite3

from backend.tests.contract.test_claim_story_contract import _event
from backend.tests.contract.test_memory_api_contract import NOW, env  # noqa: F401  (the fixture)


def _ev(con, eid, thread, ts, family, label, payload):
    _event(con, eid, thread, ts)
    con.execute("UPDATE memory_events SET family = ?, label = ?, payload = ? WHERE event_id = ?", (family, label, json.dumps(payload), eid))


def test_a_cleaned_evaluation_is_not_a_conversation_of_yours(env):  # noqa: F811
    con = sqlite3.connect(str(env.mem))
    con.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_label_ts ON memory_events(family, label, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_thread_ts ON memory_events(thread_id, ts)")
    _ev(con, "g1", "conv-90001", NOW - 50, "intent", "GOAL_SET", {})                  # its chat was cleaned by the runner: no tombstone
    _ev(con, "g2", "conv-90002", NOW - 40, "intent", "GOAL_SET", {})                  # you deleted this one: a tombstone
    _ev(con, "t2", "conv-90002", NOW - 30, "memory", "STRAND_DELETED", {"title": "My trip"})
    con.commit()
    con.close()
    snap = env.sq.snapshot(db=env.mem, conv_db=env.cs._DB_PATH)
    ids = {s["id"]: s for s in snap["sessions"]}
    assert "conv-90001" not in ids
    assert ids["conv-90002"]["chat"] == "deleted" and ids["conv-90002"]["objective"] == "My trip"
    assert ids[env.ids["root"]]["chat"] == "kept"
    m = env.client.get("/api/memory/thread-model/conv-90001").json()["session"]       # still opens, and says what it is
    assert m["chat"] == "eval" and m["ghost"] is True


def test_a_moment_says_what_it_was_about_from_where_the_words_are(env):  # noqa: F811
    root = env.ids["root"]
    ts = env.sq.ts_of(env.cs.get_conversation(root)["messages"][0]["timestamp"])
    con = sqlite3.connect(str(env.mem))
    _ev(con, "m1", root, ts + 1, "intent", "GOAL_SET", {"oracle": "new_request"})
    _ev(con, "m2", root, ts + 2, "control", "PLAN_MADE", {"steps": 2, "titles": ["Read the notes", "Write the plan"]})
    _ev(con, "m3", root, ts + 3, "problem", "ATTEMPT", {"action": "read_file:./data/tax.txt"})
    _ev(con, "m4", root, ts + 4, "knowledge", "OBSERVED", {"kind": "test_pass", "command": "pytest -q"})
    _ev(con, "m5", root, ts + 5, "delivery", "ANSWER_GIVEN", {"display_chars": 400, "spoken_chars": 0})
    _ev(con, "m6", "conv-90009", NOW - 20, "intent", "GOAL_SET", {"oracle": "new_request"})     # no chat, no run: nothing is guessed
    con.commit()
    con.close()
    d = {e["id"]: e["detail"] for e in env.client.get(f"/api/memory/thread-model/{root}").json()["events"]}
    assert d["m1"].startswith("“Please plan the release.") and len(d["m1"]) <= 152
    assert d["m2"] == "2 steps: Read the notes → Write the plan"
    assert d["m3"] == "read file · ./data/tax.txt" and d["m4"] == "a test passed · pytest -q"
    assert d["m5"].startswith("“Plan: ")
    g = env.client.get("/api/memory/thread-model/conv-90009").json()["events"]
    assert g[0]["detail"] is None
    snap = env.sq.snapshot(db=env.mem, conv_db=env.cs._DB_PATH)
    assert {e["id"]: e["detail"] for e in snap["events"]}["m2"] == "2 steps: Read the notes → Write the plan"


def test_a_turn_keeps_both_sides(env):  # noqa: F811
    c = env.cs.create_conversation(title="both sides")["id"]
    assert env.cs.ensure_user_message(c, "what is 2 + 2", source="ws_text_message") is True     # nobody had saved it
    env.cs.add_message(c, "assistant", "4", turn_id="T1")
    env.cs.add_message(c, "user", "and 3 + 3")                                                  # the frontend saved this one
    assert env.cs.ensure_user_message(c, "and 3 + 3", source="ws_text_message") is False
    env.cs.add_message(c, "assistant", "6", turn_id="T2")
    assert [(m["role"], m["text"]) for m in env.cs.get_conversation(c)["messages"]] == [
        ("user", "what is 2 + 2"), ("assistant", "4"), ("user", "and 3 + 3"), ("assistant", "6")]
    assert env.cs.ensure_user_message("conv-none", "x") is False


def test_the_text_path_saves_the_question_before_the_answer():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2].joinpath("iris_gateway.py").read_text(encoding="utf-8")
    i = src.index("_ensure_user(_conv_for_turn")
    assert src.index("_store_add(\n", i) - i < 400


def test_a_plan_keeps_its_step_titles():
    from backend.tests._kernel_source import kernel_source

    src = kernel_source()
    i = src.index('"PLAN_MADE", thread_id=_session')
    assert '"titles"' in src[i:i + 700]


def test_every_chat_with_words_is_a_bead_before_any_probe(env):  # noqa: F811
    """Live 2026-11-23: 41 of 48 beads were probe ids no chat ever knew, while 288 chats with words (older than the event log)
    had no bead at all."""
    old = env.cs.create_conversation(title="An old talk")["id"]
    env.cs.add_message(old, "user", "hello from before the event log")
    con = sqlite3.connect(str(env.mem))
    con.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_label_ts ON memory_events(family, label, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_thread_ts ON memory_events(thread_id, ts)")
    for i in range(6):
        _ev(con, f"p{i}", f"probe-{i}", NOW + 100 + i, "intent", "GOAL_SET", {})
    con.commit()
    con.close()
    snap = env.sq.snapshot(threads=4, db=env.mem, conv_db=env.cs._DB_PATH)
    ids = [x["id"] for x in snap["sessions"]]
    assert old in ids and env.ids["root"] in ids and not all(i.startswith("probe-") for i in ids)
    s = next(x for x in snap["sessions"] if x["id"] == old)
    assert s["chat"] == "kept" and s["messages"][0]["text"] == "hello from before the event log" and s["started"] <= s["ended"] if s["ended"] else True


def test_a_moment_under_the_app_connection_finds_its_words_by_turn(env):  # noqa: F811
    root = env.ids["root"]                                     # its reply is saved under turn T1-long
    env.cs.add_message(root, "user", "what did we decide")
    env.cs.add_message(root, "assistant", "To ship on Friday.", turn_id="turn-777")
    con = sqlite3.connect(str(env.mem))
    _ev(con, "s1", "session_iris", NOW - 5000, "intent", "GOAL_SET", {})
    _ev(con, "s2", "session_iris", NOW - 4990, "delivery", "ANSWER_GIVEN", {"display_chars": 18})
    con.execute("UPDATE memory_events SET episode_id = 'session_iris:turn-777' WHERE event_id IN ('s1', 's2')")
    con.commit()
    con.close()
    d = {e["id"]: e["detail"] for e in env.client.get("/api/memory/thread-model/session_iris").json()["events"]}
    assert d["s1"] == "“what did we decide”" and d["s2"] == "“To ship on Friday.”"
