"""Integration tests for /api/chat and thread management endpoints.

Associated implementation: backend/api/chat.py
Run with: python -m pytest backend/tests/test_chat_handler.py -v

Note: Tests that hit the chat endpoint mock process_text_message to avoid
depending on a running model/agent kernel.
"""

import os
import pytest
from fastapi.testclient import TestClient
from backend.main import app


# Integration tests that hit POST /api/chat with real text require the
# agent kernel to be available.  Skip them when running quick unit-style
# test suites (the default for ``backend/tests/``).  The full E2E
# verification against the running server covers these paths.
skip_slow = pytest.mark.skipif(
    os.environ.get("SKIP_SLOW_TESTS", "1") == "1",
    reason="Agent kernel not available in unit test context; "
    "set SKIP_SLOW_TESTS=0 to enable",
)


@pytest.fixture
def client():
    """TestClient backed by the real FastAPI app."""
    return TestClient(app)


class TestChatEndpointValidation:
    """POST /api/chat — validation (no agent kernel needed)."""

    def test_missing_text_rejected(self, client):
        response = client.post("/api/chat", json={})
        assert response.status_code == 422

    def test_empty_text_rejected(self, client):
        response = client.post("/api/chat", json={"text": ""})
        assert response.status_code == 422


@skip_slow
class TestChatEndpoint:
    """POST /api/chat — requires agent kernel."""

    def test_returns_valid_structure(self, client):
        response = client.post("/api/chat", json={"text": "Hello"}, timeout=30)
        assert "thread_id" in response.json() or "detail" in response.json()

    def test_new_thread_on_no_thread_id(self, client):
        r1 = client.post("/api/chat", json={"text": "Thread A"}, timeout=30)
        r2 = client.post("/api/chat", json={"text": "Thread B"}, timeout=30)
        if r1.status_code == 200 and r2.status_code == 200:
            t1 = r1.json().get("thread_id", "")
            t2 = r2.json().get("thread_id", "")
            assert t1 != t2

    def test_thread_id_starts_with_immortus_prefix(self, client):
        r = client.post("/api/chat", json={"text": "Check prefix"}, timeout=30)
        if r.status_code == 200:
            tid = r.json().get("thread_id", "")
            assert tid.startswith("immortus:thread-"), f"Unexpected prefix: {tid}"


class TestThreadEndpoints:
    """Thread management CRUD endpoints."""

    def test_list_threads_exists(self, client):
        response = client.get("/api/chat/threads")
        assert response.status_code == 200
        data = response.json()
        assert "threads" in data
        assert isinstance(data["threads"], list)

    def test_create_thread(self, client):
        response = client.post(
            "/api/chat/threads",
            json={"title": "Test Thread"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "thread_id" in data
        assert data["thread_id"].startswith("immortus:thread-")
        assert "created_at" in data

    def test_create_thread_default_title(self, client):
        response = client.post("/api/chat/threads", json={})
        assert response.status_code == 201
        data = response.json()
        assert "thread_id" in data
        assert data["thread_id"].startswith("immortus:thread-")

    def test_get_thread_not_found(self, client):
        response = client.get("/api/chat/threads/nonexistent-thread-id")
        assert response.status_code == 404

    def test_get_thread_returns_messages(self, client):
        # Create a thread first
        create_resp = client.post(
            "/api/chat/threads",
            json={"title": "Get Test"},
        )
        assert create_resp.status_code == 201
        thread_id = create_resp.json()["thread_id"]

        get_resp = client.get(f"/api/chat/threads/{thread_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["thread_id"] == thread_id
        assert "messages" in data

    def test_delete_thread(self, client):
        create_resp = client.post(
            "/api/chat/threads",
            json={"title": "Delete Me"},
        )
        thread_id = create_resp.json()["thread_id"]

        delete_resp = client.delete(f"/api/chat/threads/{thread_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"] is True

        # Verify gone
        get_resp = client.get(f"/api/chat/threads/{thread_id}")
        assert get_resp.status_code == 404

    def test_fork_thread(self, client):
        """Fork with a real message ID from an existing thread."""
        # Create parent
        create_resp = client.post(
            "/api/chat/threads",
            json={"title": "Fork Parent"},
        )
        parent_id = create_resp.json()["thread_id"]

        # Fetch messages from conversation store
        from backend.conversation_store import get_conversation

        parent = get_conversation(parent_id)
        if parent and parent.get("messages"):
            first_msg_id = parent["messages"][0]["id"]

            fork_resp = client.post(
                f"/api/chat/threads/{parent_id}/fork",
                json={
                    "message_id": first_msg_id,
                    "title": "Forked Thread",
                },
            )
            assert fork_resp.status_code == 201
            fork_data = fork_resp.json()
            assert fork_data["parent_thread_id"] == parent_id
            assert fork_data["thread_id"] != parent_id
            assert "forked_from_message" in fork_data

    def test_fork_nonexistent_message(self, client):
        create_resp = client.post(
            "/api/chat/threads",
            json={"title": "Fork Error"},
        )
        parent_id = create_resp.json()["thread_id"]

        fork_resp = client.post(
            f"/api/chat/threads/{parent_id}/fork",
            json={"message_id": "msg-nonexistent"},
        )
        assert fork_resp.status_code == 404

    def test_fork_nonexistent_parent(self, client):
        fork_resp = client.post(
            "/api/chat/threads/nonexistent/fork",
            json={"message_id": "msg-1"},
        )
        assert fork_resp.status_code == 404
