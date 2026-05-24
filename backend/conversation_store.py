"""In-memory conversation store for IRIS backend."""

import time
from typing import Any

# In-memory storage — conversations are keyed by ID
_conversations: dict[str, dict[str, Any]] = {}
_counter = 0


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def create_conversation(title: str | None = None) -> dict[str, Any]:
    """Create a new conversation and return it."""
    global _counter
    _counter += 1
    cid = f"conv-{_counter}"
    conv = {
        "id": cid,
        "title": title or f"Conversation {_counter}",
        "created_at": _now(),
        "updated_at": _now(),
        "messages": [],
        "pinned": False,
    }
    _conversations[cid] = conv
    return conv


def get_conversations() -> list[dict[str, Any]]:
    """Return all conversations sorted by updated_at (most recent first), pinned first."""
    convs = list(_conversations.values())
    convs.sort(key=lambda c: (c["pinned"], c["updated_at"]), reverse=True)
    return convs


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    """Return a single conversation by ID."""
    return _conversations.get(conversation_id)


def add_message(conversation_id: str, role: str, text: str, **kwargs) -> dict[str, Any] | None:
    """Add a message to a conversation."""
    conv = _conversations.get(conversation_id)
    if not conv:
        return None
    msg = {
        "id": f"msg-{len(conv['messages']) + 1}",
        "role": role,
        "text": text,
        "timestamp": _now(),
        **kwargs,
    }
    conv["messages"].append(msg)
    conv["updated_at"] = _now()
    return msg


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation by ID."""
    if conversation_id in _conversations:
        del _conversations[conversation_id]
        return True
    return False


def update_conversation_title(conversation_id: str, title: str) -> bool:
    """Update the title of a conversation."""
    conv = _conversations.get(conversation_id)
    if conv:
        conv["title"] = title
        conv["updated_at"] = _now()
        return True
    return False


def toggle_pin_conversation(conversation_id: str) -> bool:
    """Toggle the pinned status of a conversation."""
    conv = _conversations.get(conversation_id)
    if conv:
        conv["pinned"] = not conv["pinned"]
        conv["updated_at"] = _now()
        return True
    return False
