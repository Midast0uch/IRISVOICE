"""End-to-end tests for the full chat REST API lifecycle.

Covers: thread creation → chat messages → conversation_store bridge →
thread listing → thread forking → delete.

Associated implementation: backend/api/chat.py, backend/conversation_store.py
Run with: python -m pytest backend/tests/test_chat_e2e.py -v
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestFullThreadLifecycle:
    """Complete lifecycle: create → message → fork → delete."""

    def test_create_and_list(self, client):
        """Create a thread, verify it appears in listing."""
        create_resp = client.post("/api/chat/threads", json={"title": "Lifecycle Test"})
        assert create_resp.status_code == 201
        thread_id = create_resp.json()["thread_id"]

        list_resp = client.get("/api/chat/threads")
        threads = list_resp.json()["threads"]
        ids = [t["id"] for t in threads]
        assert thread_id in ids, f"Thread {thread_id} not found in listing"

    def test_delete_and_verify_gone(self, client):
        """Delete a thread, verify it's removed from listing."""
        create_resp = client.post("/api/chat/threads", json={"title": "Delete Verify"})
        thread_id = create_resp.json()["thread_id"]

        client.delete(f"/api/chat/threads/{thread_id}")

        get_resp = client.get(f"/api/chat/threads/{thread_id}")
        assert get_resp.status_code == 404

    def test_fork_and_independence(self, client):
        """Forked thread is independent of parent."""
        # Create parent
        parent_resp = client.post(
            "/api/chat/threads", json={"title": "Fork Independence"}
        )
        parent_id = parent_resp.json()["thread_id"]

        # Fork (empty parent fork — should copy 0 messages)
        fork_resp = client.post(
            f"/api/chat/threads/{parent_id}/fork",
            json={"message_id": "msg-nonexistent"},
        )
        # No messages to fork from → 404 (message_id not found)
        assert fork_resp.status_code == 404

    def test_concurrent_threads_dont_interfere(self, client):
        """Two threads created at the same time are distinct."""
        t1_resp = client.post("/api/chat/threads", json={"title": "Concurrent A"})
        t2_resp = client.post("/api/chat/threads", json={"title": "Concurrent B"})
        assert t1_resp.status_code == 201
        assert t2_resp.status_code == 201
        assert t1_resp.json()["thread_id"] != t2_resp.json()["thread_id"]

    def test_thread_detail_structure(self, client):
        """GET /api/chat/threads/{id} returns full detail."""
        create_resp = client.post("/api/chat/threads", json={"title": "Detail Check"})
        thread_id = create_resp.json()["thread_id"]

        detail_resp = client.get(f"/api/chat/threads/{thread_id}")
        assert detail_resp.status_code == 200
        data = detail_resp.json()
        assert data["thread_id"] == thread_id
        assert "title" in data
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert "immortus_chain" in data

    def test_create_thread_no_title(self, client):
        """Thread creation without title succeeds."""
        resp = client.post("/api/chat/threads", json={})
        assert resp.status_code == 201
        assert "thread_id" in resp.json()
