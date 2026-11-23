"""W4 (memory cortex, owner 2026-11-23): a claim's card must say WHERE it was learned and WHAT that turn found.

Measured before: the card showed only the claim's text (for most claims the TASK, not the finding) and a sync meter;
the source of an evaluation-born claim (conversation_ref = the run's WebSocket session id) resolved to nothing
(/api/memory/strand/<ref> answered 404). GET /api/memory/claims/<id>/source resolves the conversation (directly, or
through der_fan_traces session -> conversation), the turn that ASKED the claim's task, the user's question, IRIS's
answer and that turn's tool results - "not_stored" when the source is not kept here, "unrelated" when the named
conversation never asked the task (measured live: a greet.py claim pointed at a probe conversation; a match by time
showed that conversation's unrelated answer).

The first four tests FAIL on the code before this change (the route did not exist; proven against the committed
router). The last pins the 404 of an unknown claim (it also held before - a missing route is a 404).
"""
from __future__ import annotations

import sqlite3

from backend.tests.contract.test_memory_api_contract import NOW, env  # noqa: F401  (the fixture)


def _landmark(env, lid: str, ref: str, text: str = "Look up a fact") -> None:  # noqa: F811
    con = sqlite3.connect(str(env.mem))
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
                " cumulative_score, micro_abstract_text, activation_count, conversation_ref, absorbed, created_at, tier,"
                " evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lid, lid.lower(), "task_x", "[]", "[]", 0.6, text, 1, ref, None, NOW - 3000, "candidate", "[]"))
    con.commit()
    con.close()


def test_a_claim_brings_the_turn_that_asked_it_with_its_answer_and_tool_results(env):  # noqa: F811
    root = env.ids["root"]
    env.cs.add_message(root, role="user", text="Open the site and read the version, please")
    env.cs.add_message(root, role="assistant", text="The version is 4.2", turn_id="T2")
    env.cs.add_message(root, role="user", text="thanks")
    env.cs.add_message(root, role="assistant", text="You are welcome", turn_id="T3")
    chat = sqlite3.connect(str(env.cs._DB_PATH))
    chat.execute("INSERT INTO tool_results (conversation_id, turn_id, step_id, call_ord, tool, target, chars, cut, content,"
                 " created_at) VALUES (?, 'T2', 's1', 0, 'browser_open', 'https://example.org', 5200, 0, ?, ?)",
                 (root, "Example  Domain\n\n version 4.2 " + "z" * 2000, NOW))
    chat.commit()
    chat.close()
    r = env.client.get("/api/memory/claims/C_LIVE/source")       # C_LIVE: "Open the site and read the version"
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "found" and d["conversation"]["id"] == root and d["turn"] == "T2"
    assert d["question"] == "Open the site and read the version, please" and d["answer"] == "The version is 4.2"
    st = d["steps"]
    assert len(st) == 1 and st[0]["tool"] == "browser_open" and st[0]["target"] == "https://example.org" and st[0]["chars"] == 5200
    assert st[0]["excerpt"].startswith("Example Domain version 4.2") and len(st[0]["excerpt"]) <= 241   # folded, bounded


def test_a_conversation_that_never_asked_the_task_is_unrelated(env):  # noqa: F811
    # the root conversation asks "Please plan the release" - never C_CAND's "Prefer small diffs"
    d = env.client.get("/api/memory/claims/C_CAND/source").json()
    assert d["status"] == "unrelated" and d["answer"] is None and d["steps"] == []


def test_an_evaluation_claim_whose_run_is_not_stored_says_so(env):  # noqa: F811
    _landmark(env, "C_EVAL", "eval-r09_three_facts-9f0349")
    d = env.client.get("/api/memory/claims/C_EVAL/source").json()
    assert d["status"] == "not_stored" and d["conversation"] is None and d["steps"] == []


def test_an_evaluation_session_resolves_through_the_traces(env):  # noqa: F811
    root = env.ids["root"]
    con = sqlite3.connect(str(env.mem))
    con.execute("CREATE TABLE IF NOT EXISTS der_fan_traces (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id TEXT,"
                " step_id TEXT, tool TEXT, args_hash TEXT, outcome TEXT, u REAL, xi REAL, conversation_id TEXT, turn_id TEXT,"
                " ctx_tokens INTEGER, ctx_window INTEGER)")
    con.execute("INSERT INTO der_fan_traces (ts, session_id, step_id, conversation_id) VALUES (?, 'eval-q1-abc', 's1', ?)", (NOW, root))
    con.commit()
    con.close()
    _landmark(env, "C_EVAL2", "eval-q1-abc", text="Please plan the release")
    d = env.client.get("/api/memory/claims/C_EVAL2/source").json()
    assert d["status"] == "found" and d["conversation"]["id"] == root and d["answer"].startswith("Plan: ")


def test_an_unknown_claim_is_not_found(env):  # noqa: F811
    assert env.client.get("/api/memory/claims/NOPE/source").status_code == 404
