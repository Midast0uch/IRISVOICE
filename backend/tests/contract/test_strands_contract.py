"""Strands in the conversation store: the thread list and strand endpoints.

Owner decisions, 2026-10-06: a THREAD is the whole; each chat under it is a
STRAND (a conversation row with parent_id = the thread root). All strands of a
thread share one memory (`thread_root_of`). The thread list is a SUMMARY read:
the old picker downloaded every thread with every message and lagged.

These run against the real sqlite store (temp file) through the real router.
"""
from __future__ import annotations

import importlib
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as cs

    importlib.reload(cs)
    import backend.api.chat as chat

    app = FastAPI()
    app.include_router(chat.router)
    return cs, TestClient(app)


def _thread(cs, title, *messages):
    conv = cs.create_conversation(title=title)
    for text in messages:
        cs.add_message(conv["id"], role="user", text=text)
    return conv["id"]


def test_thread_list_is_summary_only_pinned_first_then_newest(env):
    cs, client = env
    old = _thread(cs, "old", "first " + "x" * 500)
    new = _thread(cs, "new", "hello\n\n   there")
    pinned = _thread(cs, "pinned", "p")
    # pin the OLDEST-updated thread: pinned must still lead
    assert client.patch(f"/api/threads/{old}", json={"pinned": True}).status_code == 200
    rows = client.get("/api/threads").json()
    assert [r["id"] for r in rows][0] == old
    assert [r["id"] for r in rows][1:] == [pinned, new]
    for r in rows:
        assert set(r) == {
            "id", "title", "pinned", "updated_at",
            "strand_count", "message_count", "last_preview",
        }, "the thread list must carry summary fields only - no message bodies"
        assert len(r["last_preview"]) <= 80
    by_id = {r["id"]: r for r in rows}
    assert by_id[new]["last_preview"] == "hello there"
    assert by_id[old]["pinned"] is True and by_id[new]["pinned"] is False
    assert by_id[old]["strand_count"] == 1 and by_id[old]["message_count"] == 1


def test_strands_share_a_thread_and_report_back(env):
    cs, client = env
    root = _thread(cs, "the whole", "root message")
    r = client.post(
        f"/api/threads/{root}/strands",
        json={"name": "  Build it ", "tags": [" Build ", "PLAN", "build", "mine"]},
    )
    assert r.status_code == 201
    s1 = r.json()
    assert s1["title"] == "Build it"
    assert s1["tags"] == ["build", "plan", "mine"], "trimmed, lowercased, de-duplicated"
    assert s1["reports_to"] is None and s1["message_count"] == 0

    helper = client.post(
        f"/api/threads/{root}/strands",
        json={"name": "swarm run", "tags": ["swarm"], "reports_to": s1["id"]},
    ).json()
    assert helper["reports_to"] == s1["id"]

    strands = client.get(f"/api/threads/{root}/strands").json()
    assert [s["id"] for s in strands] == [root, s1["id"], helper["id"]]
    assert all(
        set(s) == {"id", "title", "tags", "reports_to", "updated_at", "message_count"}
        for s in strands
    )

    # the thread list shows ONE row for the whole, counting every strand's messages
    cs.add_message(helper["id"], role="assistant", text="swarm says hi")
    rows = client.get("/api/threads").json()
    assert [r["id"] for r in rows] == [root], "a strand must not appear as its own thread"
    assert rows[0]["strand_count"] == 3 and rows[0]["message_count"] == 2
    assert rows[0]["last_preview"] == "swarm says hi"

    # a strand's messages stay keyed by its own conversation id (no migration)
    assert cs.get_conversation(helper["id"])["messages"][0]["text"] == "swarm says hi"


def test_strand_bounds_and_errors(env):
    cs, client = env
    root = _thread(cs, "t")
    other = _thread(cs, "other")
    url = f"/api/threads/{root}/strands"
    assert client.post(url, json={"name": "a", "tags": [f"t{i}" for i in range(9)]}).status_code == 422
    assert client.post(url, json={"name": "a", "tags": ["x" * 25]}).status_code == 422
    assert client.post(url, json={"name": "a", "tags": ["x" * 24] + [f"t{i}" for i in range(7)]}).status_code == 201
    assert client.post(url, json={"name": "   "}).status_code == 422
    assert client.post(url, json={"name": "a", "reports_to": other}).status_code == 422
    assert client.post("/api/threads/nope/strands", json={"name": "a"}).status_code == 404
    assert client.get("/api/threads/nope/strands").status_code == 404
    assert client.patch("/api/strands/nope", json={"name": "a"}).status_code == 404
    assert client.patch("/api/threads/nope", json={"pinned": True}).status_code == 404


def test_patch_strand_and_thread(env):
    cs, client = env
    root = _thread(cs, "t")
    sid = client.post(f"/api/threads/{root}/strands", json={"name": "a"}).json()["id"]
    p = client.patch(f"/api/strands/{sid}", json={"name": "renamed", "tags": [" Research "]})
    assert p.json()["title"] == "renamed" and p.json()["tags"] == ["research"]
    assert client.patch(f"/api/strands/{sid}", json={"tags": ["x" * 30]}).status_code == 422
    t = client.patch(f"/api/threads/{root}", json={"title": "Whole", "pinned": True}).json()
    assert t["title"] == "Whole" and t["pinned"] is True

    # survives a restart: the cache is rebuilt from disk, strand columns are in SQLite
    cs._conversations.clear()
    cs.load_from_db()
    assert client.get(f"/api/threads/{root}/strands").json()[1]["tags"] == ["research"]


def test_thread_root_of_is_one_resolver_for_the_whole_thread(env):
    cs, client = env
    root = _thread(cs, "t")
    a = client.post(f"/api/threads/{root}/strands", json={"name": "a"}).json()["id"]
    b = client.post(f"/api/threads/{root}/strands", json={"name": "b"}).json()["id"]
    assert cs.thread_root_of(root) == cs.thread_root_of(a) == cs.thread_root_of(b) == root
    assert cs.thread_root_of("unknown-id") == "unknown-id"


def test_existing_conversation_endpoints_keep_their_shape(env):
    cs, _ = env
    cid = _thread(cs, "t", "hi")
    conv = cs.get_conversations()[0]
    assert set(conv) == {"id", "title", "created_at", "updated_at", "messages", "pinned"}
    assert cs.get_conversation(cid)["messages"][0]["text"] == "hi"


def test_migration_is_idempotent_and_adds_columns_to_an_old_store(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0)"
    )
    con.execute("INSERT INTO conversations VALUES ('conv-1','old','t','t',0)")
    con.commit()
    con.close()
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(db))
    import backend.conversation_store as cs

    importlib.reload(cs)
    cs.load_from_db()
    cs._conn.close()
    cs._conn = None
    cs._get_conn()  # second open: ALTERs are guarded, must not raise
    assert [t["id"] for t in cs.list_threads()] == ["conv-1"]


def test_thread_list_query_uses_the_parent_index(env):
    cs, _ = env
    plan = " | ".join(
        r[3] for r in cs._get_conn().execute("EXPLAIN QUERY PLAN " + cs._THREAD_LIST_SQL)
    )
    assert "idx_conversations_parent" in plan, plan
    assert "idx_messages_conv" in plan, plan
