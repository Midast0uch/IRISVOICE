"""Contract: a conversation deleted or renamed in chat leaves a TOMBSTONE in the memory.

Titles live ONLY in conversations.db (MEMORY-SURFACE-BUILD section 1, section 4 cases 1, 2, 8).
When chat deletes a conversation the memory keeps every event and claim under its id but loses
its NAME. So each deleted conversation types ONE STRAND_DELETED event, each rename one
STRAND_RENAMED event, through the REAL memory_events lane into a REAL (temp) memory_events
store. Nothing about the writer is stubbed; the conversation store is the real module on a
temp conversations.db.

Pins: one event per affected conversation (a root with N strands writes N + 1), the title and
the ids in the payload, evidence/actor "user", off the request path (a blocked lane never
delays the delete), a lost tombstone is counted and never fails the delete, and the new labels
are WORDS of an existing family (the closed alphabet is not widened).
"""
from __future__ import annotations

import json
import time

import pytest

import backend.memory as _memory_pkg
from backend.memory import event_alphabet as ea
from backend.tests.contract._events_fixture import BlockedLane, memory_interface, rows, store  # noqa: F401


@pytest.fixture()
def cs(tmp_path, monkeypatch, store):  # noqa: F811
    """The real conversation_store on a temp conversations.db, wired to the temp memory store."""
    import backend.conversation_store as cs

    monkeypatch.setattr(cs, "_DB_PATH", str(tmp_path / "conversations.db"))
    monkeypatch.setattr(cs, "_conn", None)
    monkeypatch.setattr(cs, "_conversations", {})
    monkeypatch.setattr(cs, "_counter", 0)
    monkeypatch.setattr(cs, "_tombstones_lost", 0, raising=False)
    monkeypatch.setattr(_memory_pkg, "_memory_interface", memory_interface(store))
    yield cs
    if cs._conn is not None:
        cs._conn.close()


def _payload(row):
    return json.loads(row["payload"])


def _braid(cs):
    """A root with two strands (one is a helper that reports to the first)."""
    root = cs.create_conversation(title="Plan the trip", conv_id="conv-root")
    cs.add_message(root["id"], role="user", text="where to?")
    first = cs.create_strand("conv-root", "research", tags=["web"])
    helper = cs.create_strand("conv-root", "helper", tags=["swarm"], reports_to=first["id"])
    cs.add_message(first["id"], role="user", text="one")
    cs.add_message(first["id"], role="assistant", text="two")
    return root, first, helper


def test_the_labels_are_words_of_an_existing_family_not_new_values():
    labels = ea.registered_labels()
    for word in ("STRAND_DELETED", "STRAND_RENAMED"):
        assert labels[word].family == "memory" and labels[word].actor == "user"
        assert labels[word].family in ea.FAMILIES and labels[word].actor in ea.ACTORS


def test_deleting_a_root_with_two_strands_writes_three_tombstones(cs, store):  # noqa: F811
    root, first, helper = _braid(cs)
    assert cs.delete_conversation("conv-root") is True

    got = {r["thread_id"]: r for r in rows(store, "STRAND_DELETED")}
    assert sorted(got) == sorted(["conv-root", first["id"], helper["id"]]), (
        "N strands + the root must write N + 1 events, one per conversation, thread_id = its id")
    for r in got.values():
        assert (r["family"], r["evidence"], r["actor"], r["label_source"]) == ("memory", "user", "user", "rule")
        assert _payload(r)["at"] > 0
    root_p, first_p, helper_p = (_payload(got[k]) for k in ("conv-root", first["id"], helper["id"]))
    assert (root_p["title"], root_p["parent_id"], root_p["message_count"]) == ("Plan the trip", None, 1)
    assert (first_p["title"], first_p["parent_id"], first_p["tags"], first_p["message_count"]) == (
        "research", "conv-root", ["web"], 2)
    assert (helper_p["title"], helper_p["parent_id"], helper_p["tags"], helper_p["reports_to"]) == (
        "helper", "conv-root", ["swarm"], first["id"])
    # the chat rows are gone; the memory keeps the names
    assert cs.get_conversation("conv-root") is None and cs.get_strand(first["id"]) is None


def test_deleting_one_strand_writes_one_tombstone_with_its_parent(cs, store):  # noqa: F811
    root, first, helper = _braid(cs)
    assert cs.delete_conversation(helper["id"]) is True
    (row,) = rows(store, "STRAND_DELETED")
    assert row["thread_id"] == helper["id"]
    assert _payload(row)["parent_id"] == "conv-root" and _payload(row)["title"] == "helper"
    assert cs.get_strand(first["id"]) is not None, "a sibling strand must survive"


def test_deleting_an_unknown_conversation_writes_nothing(cs, store):  # noqa: F811
    assert cs.delete_conversation("conv-nope") is False
    assert rows(store) == []


def test_a_rename_writes_one_tombstone_with_both_titles(cs, store):  # noqa: F811
    cs.create_conversation(title="Old name", conv_id="conv-1")
    assert cs.update_conversation_title("conv-1", "New name") is True
    (row,) = rows(store, "STRAND_RENAMED")
    assert row["thread_id"] == "conv-1"
    assert (row["family"], row["evidence"], row["actor"]) == ("memory", "user", "user")
    p = _payload(row)
    assert (p["old_title"], p["new_title"]) == ("Old name", "New name") and p["at"] > 0


def test_renaming_a_strand_and_a_thread_through_the_store_api_types_a_rename_each(cs, store):  # noqa: F811
    root, first, _ = _braid(cs)
    cs.update_strand(first["id"], name="research v2")
    cs.update_thread("conv-root", title="Plan the big trip")
    by_thread = {r["thread_id"]: _payload(r) for r in rows(store, "STRAND_RENAMED")}
    assert by_thread[first["id"]]["old_title"] == "research"
    assert by_thread["conv-root"]["new_title"] == "Plan the big trip"


def test_a_rename_to_the_same_title_is_not_an_event(cs, store):  # noqa: F811
    cs.create_conversation(title="Same", conv_id="conv-1")
    cs.update_conversation_title("conv-1", "Same")
    assert rows(store, "STRAND_RENAMED") == []


def test_the_tombstone_never_deletes_or_rewrites_a_memory_row(cs, store):  # noqa: F811
    from backend.memory import memory_events as me

    me.emit_event(store, label="GOAL_SET", thread_id="conv-1", episode_id="conv-1:t1", chain=False)
    cs.create_conversation(title="Doomed", conv_id="conv-1")
    cs.delete_conversation("conv-1")
    labels = sorted(r["label"] for r in rows(store))
    assert labels == ["GOAL_SET", "STRAND_DELETED"], "the deleted strand's memory stays; the tombstone is added"


def test_a_blocked_lane_never_delays_the_delete_or_the_rename(cs, store):  # noqa: F811
    cs.create_conversation(title="A", conv_id="conv-a")
    cs.create_conversation(title="B", conv_id="conv-b")
    with BlockedLane():
        t0 = time.monotonic()
        assert cs.update_conversation_title("conv-a", "A2") is True
        assert cs.delete_conversation("conv-b") is True
        assert time.monotonic() - t0 < 1.0, "the tombstone write is on the lane, not on the request path"
    assert {r["label"] for r in rows(store)} == {"STRAND_RENAMED", "STRAND_DELETED"}


def test_a_lost_tombstone_is_counted_and_never_fails_the_delete(cs, store, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setattr(_memory_pkg, "_memory_interface", None)   # no memory store open
    cs.create_conversation(title="A", conv_id="conv-a")
    with caplog.at_level("WARNING"):
        assert cs.delete_conversation("conv-a") is True
    assert cs.tombstones_lost() == 1
    assert "tombstone not queued" in caplog.text and "conv-a" in caplog.text
    assert rows(store) == []
