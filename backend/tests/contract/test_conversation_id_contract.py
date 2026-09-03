"""A new conversation must never be handed an existing thread.

Live failure, 2026-08-11: the user sent a prompt into what the UI presented as a
new conversation and it landed in an OLD thread, with that thread's documents
rehydrating alongside it, while React logged "Encountered two children with the
same key, `conv-1`".

One unrestored global caused all three. `create_conversation` auto-generates
"conv-N" from a module-level `_counter` that starts at 0, and `load_from_db()`
rebuilt the conversations but NOT the counter. So every backend restart began
issuing conv-1 again — an id that already existed with 15 messages behind it.
The collision was invisible because the auto-generating branch had no existence
check (only the caller-supplied branch did), the DB write is INSERT OR IGNORE so
the row survived unchanged, and the in-memory cache entry was REPLACED with an
empty one — so the existing thread looked empty and the new turn appended into
it.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A conversation_store bound to a temp DB, reloaded from scratch."""
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as cs

    importlib.reload(cs)
    return cs


def _simulate_restart(cs):
    """Exactly what a backend restart does: drop the cache, reload from disk."""
    cs._conversations.clear()
    cs._counter = 0
    cs.load_from_db()


def test_new_conversation_after_restart_does_not_reuse_an_id(store):
    first = store.create_conversation(title="first")
    store.add_message(first["id"], role="user", text="the original prompt")

    _simulate_restart(store)

    second = store.create_conversation(title="second")
    assert second["id"] != first["id"], (
        f"a restart re-issued {first['id']!r}. The user's next prompt is filed "
        f"into the previous conversation, that thread's documents rehydrate with "
        f"it, and the frontend renders two rows with the same React key."
    )
    assert second["messages"] == [], "a brand new conversation arrived non-empty"


def test_restart_preserves_the_earlier_threads_messages(store):
    first = store.create_conversation(title="first")
    store.add_message(first["id"], role="user", text="the original prompt")

    _simulate_restart(store)
    store.create_conversation(title="second")

    reloaded = store.get_conversation(first["id"])
    assert reloaded is not None, f"{first['id']} vanished after the restart"
    texts = [m["text"] for m in reloaded["messages"]]
    assert "the original prompt" in texts, (
        f"the earlier thread's messages were lost: {texts}. The cache entry was "
        f"replaced with an empty conversation on the colliding create."
    )


def test_counter_resumes_past_every_persisted_id(store):
    ids = [store.create_conversation()["id"] for _ in range(3)]
    _simulate_restart(store)

    assert store._counter >= 3, (
        f"counter resumed at {store._counter} with {ids} already on disk"
    )
    fresh = store.create_conversation()["id"]
    assert fresh not in ids, f"{fresh} collides with an existing id {ids}"


def test_ids_stay_unique_across_many_restarts(store):
    """The counter is derived from the ids themselves, so it must be
    self-correcting rather than drifting a little further out of step each time."""
    seen: set = set()
    for _ in range(6):
        _simulate_restart(store)
        for _ in range(3):
            cid = store.create_conversation()["id"]
            assert cid not in seen, f"duplicate id {cid} after a restart"
            seen.add(cid)
    assert len(seen) == 18


def test_supplied_id_that_already_exists_is_returned_not_emptied(store):
    """The pre-existing idempotent path must keep its messages too."""
    conv = store.create_conversation(title="kept", conv_id="immortus-thread-1")
    store.add_message(conv["id"], role="user", text="hello")

    again = store.create_conversation(title="ignored", conv_id="immortus-thread-1")
    assert [m["text"] for m in again["messages"]] == ["hello"]
    assert again["title"] == "kept"
