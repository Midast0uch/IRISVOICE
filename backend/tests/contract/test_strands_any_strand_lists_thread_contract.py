"""Any strand of a thread lists the whole thread.

Live 2026-10-06: the composer's `#` list asks GET /api/threads/{id}/strands with
the conversation ON SCREEN. In a child strand that id is not the thread root, the
endpoint answered 404, and `#` listed no strands. The endpoint resolves the id
through `thread_root_of` (the one resolver); an unknown id still answers 404.

Guard: fails on the old endpoint (404 for a child strand).
"""
from __future__ import annotations

import importlib

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


def test_a_child_strand_lists_its_whole_thread(env):
    cs, client = env
    root = cs.create_conversation(title="Router budget")["id"]
    a = client.post(f"/api/threads/{root}/strands", json={"name": "fix the cap", "tags": ["build"]}).json()
    b = client.post(f"/api/threads/{root}/strands", json={"name": "people", "tags": ["people"]}).json()

    want = [root, a["id"], b["id"]]
    for asked in (root, a["id"], b["id"]):
        r = client.get(f"/api/threads/{asked}/strands")
        assert r.status_code == 200, f"asking with {asked} gave {r.status_code}"
        assert [s["id"] for s in r.json()] == want


def test_an_unknown_id_is_still_404(env):
    _cs, client = env
    assert client.get("/api/threads/nope/strands").status_code == 404
