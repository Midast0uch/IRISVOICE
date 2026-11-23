"""W4 (memory cortex, owner 2026-11-23): a claim keeps what its teaching turn FOUND, at birth.

Measured before: a claim stored only its task text and a conversation ref; 387 of 389 live claims pointed at a chat
that is no longer stored, so the card could not say what the claim found. Now crystallize_landmark keeps a small
finding on the claim (turn, conversation, tools, the last step's output) and /claims/<id>/source serves it as "kept"
when the chat is gone.

Each test FAILS on the code before this change (no claim_finding, no save_finding, no finding column, no "kept").
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from backend.tests.contract.test_memory_api_contract import NOW, env  # noqa: F401  (the fixture)


def test_a_turn_becomes_a_small_bounded_finding():
    from backend.memory.interface import claim_finding

    ep = SimpleNamespace(turn_id="T9", session_id="conv-1",
                         tool_sequence=[{"tool": "none"}, {"tool": "web_search", "target": "eiffel tower height " + "x" * 200, "success": True},
                                        {"tool": "browser_open", "target": "https://en.wikipedia.org/wiki/Eiffel_Tower", "success": False}],
                         full_content="[Step 1] searching\n[Step 2] The Eiffel Tower is 330 m tall.\n\n  It opened in 1889. " + "y" * 900)
    f = json.loads(claim_finding(ep))
    assert f["turn"] == "T9" and f["conversation"] == "conv-1"
    assert [t["tool"] for t in f["tools"]] == ["web_search", "browser_open"]          # "none" is not a tool
    assert len(f["tools"][0]["target"]) == 80 and f["tools"][1]["ok"] is False
    assert f["result"].startswith("The Eiffel Tower is 330 m tall. It opened in 1889.")  # the last step, whitespace folded
    assert len(f["result"]) == 500
    assert claim_finding(SimpleNamespace(turn_id=None, session_id="c", tool_sequence=[], full_content="")) is None


def test_the_claim_keeps_it_and_a_merge_survivor_keeps_its_own():
    from backend.memory.db import app_flush
    from backend.memory.mycelium.landmark import LandmarkIndex, ensure_landmark_policy_columns

    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.execute("CREATE TABLE mycelium_landmarks (landmark_id TEXT PRIMARY KEY, label TEXT, task_class TEXT, coordinate_cluster TEXT,"
                " traversal_sequence TEXT, cumulative_score REAL, micro_abstract BLOB, micro_abstract_text TEXT,"
                " activation_count INTEGER, is_permanent INTEGER, conversation_ref TEXT, absorbed INTEGER, created_at REAL,"
                " last_activated REAL)")
    ensure_landmark_policy_columns(con)
    assert "finding" in {r[1] for r in con.execute("PRAGMA table_info(mycelium_landmarks)")}
    for lid in ("NEW", "OLD"):
        con.execute("INSERT INTO mycelium_landmarks (landmark_id, created_at) VALUES (?, ?)", (lid, NOW))
    con.execute("UPDATE mycelium_landmarks SET finding = 'theirs' WHERE landmark_id = 'OLD'")
    con.commit()
    idx = LandmarkIndex(con)
    idx.save_finding("NEW", '{"result": "mine"}')
    idx.save_finding("OLD", '{"result": "mine"}', only_if_empty=True)
    app_flush()
    got = dict(con.execute("SELECT landmark_id, finding FROM mycelium_landmarks").fetchall())
    assert got == {"NEW": '{"result": "mine"}', "OLD": "theirs"}


def test_the_card_serves_the_kept_finding_when_the_chat_is_gone(env):  # noqa: F811
    con = sqlite3.connect(str(env.mem))
    if "finding" not in {r[1] for r in con.execute("PRAGMA table_info(mycelium_landmarks)")}:
        con.execute("ALTER TABLE mycelium_landmarks ADD COLUMN finding TEXT")
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
                " cumulative_score, micro_abstract_text, activation_count, conversation_ref, created_at, tier, evidence, finding)"
                " VALUES ('C_KEPT', 'k', 'task_x', '[]', '[]', 0.6, 'Find the height of the Eiffel Tower', 1,"
                " 'eval-r09_three_facts-9f0349', ?, 'candidate', '[]', ?)",
                (NOW, json.dumps({"turn": "T9", "conversation": "eval-r09_three_facts-9f0349",
                                  "tools": [{"tool": "web_search", "target": "eiffel tower height", "ok": True}],
                                  "result": "The Eiffel Tower is 330 m tall."})))
    con.commit()
    con.close()
    d = env.client.get("/api/memory/claims/C_KEPT/source").json()
    assert d["status"] == "kept" and d["turn"] == "T9"
    assert d["question"] == "Find the height of the Eiffel Tower" and d["answer"] == "The Eiffel Tower is 330 m tall."
    assert [(s["tool"], s["target"]) for s in d["steps"]] == [("web_search", "eiffel tower height")]
