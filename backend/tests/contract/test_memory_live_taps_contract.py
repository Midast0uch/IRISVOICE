"""Contract pin: the Memory surface's live taps (backend/utils/memory_live.py).

The frontend reads EXACTLY these keys from `iris:ws_message` (detail = {type, payload}).
Each message is one batch: `{type, payload: {<list key>: [...], "dropped": int}}`.

  memory_event     payload.events    item keys: event_id, ts, family, label, valence, actor,
                   evidence, episode_id, thread_id, topic_domain, landmark_id, recall_trace_id,
                   source, refs
  landmark_update  payload.updates   item keys: landmark_id, kind, activation_count, tier,
                   survivor_id, ts      (kind: activated|promoted|stale|demoted|dissolved|merged)
  oracle_decision  payload.decisions item keys: consumer, job, confidence, chosen, acted, options, ts
                                        (acted: enforced|sampled|shadow)

Why these pins. The surface used to invent its activity; it now draws only what a single
writer reports AFTER its row is written. So the guards are: the shape of each message; the
coalescing (a burst of rows is capped and the drop is counted and logged, never silent);
the off switch IRIS_MEMORY_LIVE=0; a failing broadcast or tap never fails the writer; and a
write that raised broadcasts nothing (the tap runs after the write).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import tempfile
import threading
import time
import types
import uuid
from pathlib import Path

import pytest

import backend.agent.tool_bridge as tb
import backend.gateway.iris_ffi as _ffi
from backend.agent.tool_bridge import AgentToolBridge
from backend.memory import memory_events as me
from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium import landmark as lm
from backend.memory.mycelium.landmark import Landmark, LandmarkIndex
from backend.memory.mycelium.profile import LandmarkMerger
from backend.utils import memory_live
from backend.utils.durability_queue import lane

EVENT_KEYS = {"event_id", "ts", "family", "label", "valence", "actor", "evidence", "episode_id",
              "thread_id", "topic_domain", "landmark_id", "recall_trace_id", "source", "refs"}
LANDMARK_KEYS = {"landmark_id", "kind", "activation_count", "tier", "survivor_id", "ts"}
DECISION_KEYS = {"consumer", "job", "confidence", "chosen", "acted", "options", "ts"}


_REAL_START_DRAIN = memory_live._start_drain


@pytest.fixture(autouse=True)
def live(monkeypatch):
    """A clean tap with a capturing sender and NO drain thread: the tests run the tick.
    `_wake` is replaced per test, so a drain thread left over from the threaded test below
    stays parked on its own event and never steals another test's rows."""
    monkeypatch.delenv("IRIS_MEMORY_LIVE", raising=False)
    monkeypatch.setattr(memory_live, "_start_drain", lambda: None)
    monkeypatch.setattr(memory_live, "_wake", threading.Event())
    memory_live.reset()
    sent: list = []
    memory_live.set_sender(lambda msg: sent.append(msg) or True)
    yield sent
    memory_live.set_sender(None)
    memory_live.reset()


def _tick(sent: list) -> list:
    memory_live.flush_once()
    out, sent[:] = list(sent), []
    return out


@pytest.fixture()
def store(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="memlive-")) / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(tmp), key_hex="00" * 32)
    monkeypatch.setattr(_ffi, "_engine", eng)
    conn = sqlite3.connect(str(tmp), check_same_thread=False)
    me.ensure_schema(conn)
    yield conn
    conn.close()
    eng._conn.close()


@pytest.fixture()
def lmconn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    initialise_mycelium_schema(c)
    lm.ensure_landmark_policy_columns(c)
    me.ensure_schema(c)
    for lid, conv in (("lm1", "s1"), ("lm2", "s2")):
        c.execute(
            "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, "
            "traversal_sequence, cumulative_score, activation_count, is_permanent, conversation_ref, "
            "absorbed, created_at) VALUES (?, 'fix a.py', 'tc', ?, '[]', 0.9, 0, 0, ?, NULL, ?)",
            (lid, json.dumps([{"node_id": "n1", "space_id": "d", "coordinates": [0.1, 0.5, 1.0],
                               "confidence": 0.5, "access_count": 3}]), conv, time.time()),
        )
    c.commit()
    yield c
    lane("memory_events").flush(10.0)
    c.close()


def _items(msgs, kind, key):
    out = []
    for m in msgs:
        if m["type"] == kind:
            assert set(m["payload"]) == {key, "dropped"}
            out.extend(m["payload"][key])
    return out


# ── shapes ─────────────────────────────────────────────────────────────────

def test_memory_event_message_shape_and_recall_fields(store, live):
    me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1",
                  episode_id="t1:turn1", topic_domain="coding", chain=False)
    me.record_recall_delivered(store, thread_id="t1", task_id="t1:turn1", step_id="s1",
                               source="neighbors", recall_trace_id="rt-abc",
                               refs=["chain-1", "chain-2"])
    me.emit_event(store, label="RECALL_HELPED", evidence="verifier", thread_id="t1",
                  links={"recall_trace_id": "rt-abc"}, chain=False)
    me.emit_event(store, label="LANDMARK_PROMOTED", evidence="test", thread_id="t1",
                  payload={"landmark": "lm9", "text": "this must not travel"}, chain=False)
    msgs = _tick(live)
    assert [m["type"] for m in msgs] == ["memory_event"]
    ev = _items(msgs, "memory_event", "events")
    assert len(ev) == 4 and all(set(e) == EVENT_KEYS for e in ev)
    corr, delivered, helped, promoted = ev
    assert (corr["label"], corr["family"], corr["evidence"], corr["actor"]) == (
        "CORRECTION", "feedback", "user", "user")
    assert corr["event_id"].startswith("ev-") and corr["topic_domain"] == "coding"
    assert corr["thread_id"] == "t1" and corr["episode_id"] == "t1:turn1"
    assert corr["recall_trace_id"] is None and corr["source"] is None and corr["refs"] is None
    assert delivered["label"] == "RECALL_DELIVERED" and delivered["recall_trace_id"] == "rt-abc"
    assert delivered["source"] == "neighbors" and delivered["refs"] == ["chain-1", "chain-2"]
    assert helped["recall_trace_id"] == "rt-abc" and helped["source"] is None
    assert promoted["landmark_id"] == "lm9"
    assert "this must not travel" not in json.dumps(msgs)        # ids and labels, no text
    # the same ids as the stored rows
    stored = {r[0] for r in store.execute("SELECT event_id FROM memory_events")}
    assert {e["event_id"] for e in ev} == stored


def test_landmark_update_message_shape_for_every_kind(lmconn, live):
    def settle():
        # the typed events go to the memory_events lane on this connection: wait for it
        # before the next statement (the lane is the connection's other writer)
        assert lane("memory_events").flush(10.0)

    idx = LandmarkIndex(lmconn)
    idx.activate("lm1")
    lm.add_landmark_evidence(lmconn, "lm1", "task_complete", "ep", "s1")
    settle()
    lm.add_landmark_evidence(lmconn, "lm1", "test_pass", "pytest", "s2")        # -> promoted
    settle()
    lm.mark_landmarks_stale_by_dependency(lmconn, "a.py")                        # no depends_on: none
    lmconn.execute("UPDATE mycelium_landmarks SET depends_on = '[\"a.py\"]' WHERE landmark_id='lm1'")
    lmconn.commit()
    lm.mark_landmarks_stale_by_dependency(lmconn, "a.py")                        # -> stale
    settle()
    lm.demote_landmarks_for_thread(lmconn, "s1", "contradicted")                 # -> demoted
    settle()
    lm._emit_landmark_event(lmconn, "LANDMARK_DISSOLVED", ["lm2"], payload={"reason": "decayed"})
    lm._emit_landmark_event(lmconn, "LANDMARK_MERGED", ["lm2"])                  # tapped in the merger
    settle()
    ups = _items(_tick(live), "landmark_update", "updates")
    assert all(set(u) == LANDMARK_KEYS for u in ups)
    by = [(u["landmark_id"], u["kind"]) for u in ups]
    assert by == [("lm1", "activated"), ("lm1", "promoted"), ("lm1", "stale"),
                  ("lm1", "demoted"), ("lm2", "dissolved")]
    activated, promoted, stale, demoted, dissolved = ups
    assert activated["activation_count"] == 1 and activated["tier"] == "candidate"
    assert promoted["tier"] == "landmark" and stale["tier"] == "stale" and demoted["tier"] == "demoted"
    assert dissolved["tier"] is None and dissolved["survivor_id"] is None
    assert all(isinstance(u["ts"], float) for u in ups)


def test_landmark_merge_update_names_the_survivor(lmconn, live):
    idx = LandmarkIndex(lmconn)
    cluster = [{"node_id": "n1", "space_id": "d", "coordinates": [0.1, 0.5, 1.0],
                "confidence": 0.5, "access_count": 3}]
    # the same task as the seeded lm1/lm2: only the same task merges (task_key, owner decision 2026-10-24)
    new = Landmark(landmark_id="lm_new", label="fix a.py", task_class="tc", coordinate_cluster=cluster,
                   traversal_sequence=["n1"], cumulative_score=0.8, micro_abstract=None,
                   micro_abstract_text=None, activation_count=0, is_permanent=False,
                   conversation_ref="s9", created_at=time.time(), last_activated=None)
    idx.save(new)
    assert LandmarkMerger(idx).try_merge(new) is not None
    ups = _items(_tick(live), "landmark_update", "updates")
    merged = [u for u in ups if u["kind"] == "merged"]
    assert merged and all(set(u) == LANDMARK_KEYS for u in merged)
    assert all(u["survivor_id"] for u in merged) and all(u["landmark_id"] != u["survivor_id"] for u in merged)


@pytest.fixture()
def ledger(monkeypatch):
    rows: list = []
    monkeypatch.setattr(_ffi, "ffi_ingest_event", lambda **kw: rows.append(kw) or True)
    return rows


def _decide(meta: dict, kind: str = "shadow") -> None:
    # a unique turn id: the shadow dedup (record_decision) keys on it
    meta = {**meta, "turn_id": "turn-" + uuid.uuid4().hex[:8]}
    AgentToolBridge().record_decision(meta, kind, session_id="s-live-" + uuid.uuid4().hex[:6])
    assert tb._LEDGER_LANE.flush(10.0)


def test_oracle_decision_message_shape_and_acted(ledger, live):
    base = {"engine": "d1", "chosen": "read_file", "confidence": 0.9123456}
    _decide({**base, "consumer_id": "tool_choice", "route": "enforced"})
    _decide({**base, "consumer_id": "tool_choice", "route": "sampled", "chosen": "grep"})
    _decide({**base, "consumer_id": "sufficient", "route": "shadow", "chosen": True,
             "brain_bool": True}, "shadow")
    # a tool execution row that carries a decision block is a decision row too
    tb._DECISION_META.set({**base, "consumer_id": "tool_choice", "route": "engine"})
    try:
        AgentToolBridge()._record_tool_event("s1", "read_file", "success", {"path": "x"}, {"success": True})
    finally:
        tb._DECISION_META.set(None)
    assert tb._LEDGER_LANE.flush(10.0)
    dec = _items(_tick(live), "oracle_decision", "decisions")
    assert all(set(d) == DECISION_KEYS for d in dec)
    assert [(d["consumer"], d["acted"], d["chosen"]) for d in dec] == [
        ("tool_choice", "enforced", "read_file"), ("tool_choice", "sampled", "grep"),
        ("sufficient", "shadow", True), ("tool_choice", "enforced", "read_file")]
    assert dec[0]["confidence"] == 0.9123 and isinstance(dec[0]["ts"], float)


def test_a_legacy_row_without_a_decision_block_is_not_a_decision(ledger, live):
    tb._DECISION_META.set(None)
    AgentToolBridge()._record_tool_event("s1", "read_file", "success", {}, {})
    assert tb._LEDGER_LANE.flush(10.0)
    assert ledger and _tick(live) == []


# ── coalescing ─────────────────────────────────────────────────────────────

def test_a_burst_is_capped_and_the_drop_is_counted_and_logged(live, caplog):
    for i in range(1000):                                  # 1000 rows inside one tick
        memory_live.memory_event(event_id=f"ev-{i}", ts=float(i), family="memory", label="OBSERVED",
                                 valence=None, actor=None, evidence="none", episode_id=None,
                                 thread_id="t", topic_domain=None, links=None, payload=None)
    st = memory_live.stats()
    assert st["tapped"] == 1000 and st["dropped"] == 1000 - memory_live.BUFFER_CAP
    with caplog.at_level(logging.WARNING, logger="backend.utils.memory_live"):
        first = _tick(live)
    assert len(first) == 1                                 # ONE message for the type
    assert len(first[0]["payload"]["events"]) == memory_live.MAX_PER_TICK == 50
    assert first[0]["payload"]["dropped"] == 800           # the surface is told of the gap
    assert any("dropped 800" in r.getMessage() and "kind=memory_event" in r.getMessage()
               for r in caplog.records), "the drop was silent"
    drained = []
    while memory_live._bufs["memory_event"]:
        drained += _tick(live)
    assert all(len(m["payload"]["events"]) <= 50 and m["payload"]["dropped"] == 0 for m in drained)
    # buffered (not dropped) rows all arrive, in order
    ids = [e["event_id"] for m in first + drained for e in m["payload"]["events"]]
    assert ids == [f"ev-{i}" for i in range(memory_live.BUFFER_CAP)]


def test_the_drain_thread_batches_on_its_own_tick(monkeypatch, live):
    """The real drain thread (not the test's manual tick): messages arrive batched and capped."""
    monkeypatch.setattr(memory_live, "_start_drain", _REAL_START_DRAIN)
    monkeypatch.setattr(memory_live, "TICK_S", 0.02)
    memory_live.reset()
    got: list = []
    done = threading.Event()

    def sender(msg):
        got.append(msg)
        if sum(len(m["payload"]["decisions"]) for m in got) >= memory_live.BUFFER_CAP:
            done.set()
        return True

    memory_live.set_sender(sender)
    for i in range(1000):
        memory_live.oracle_decision({"consumer_id": "tool_choice", "route": "shadow",
                                     "chosen": str(i), "confidence": 0.5})
    assert done.wait(5.0), "the drain thread never delivered the buffered rows"
    assert all(len(m["payload"]["decisions"]) <= memory_live.MAX_PER_TICK for m in got)
    assert len(got) >= memory_live.BUFFER_CAP // memory_live.MAX_PER_TICK
    assert sum(m["payload"]["dropped"] for m in got) == 800


# ── off switch ─────────────────────────────────────────────────────────────

def test_the_off_switch_stops_every_tap_and_not_the_writer(store, lmconn, ledger, live, monkeypatch):
    monkeypatch.setenv("IRIS_MEMORY_LIVE", "0")
    eid = me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1", chain=False)
    LandmarkIndex(lmconn).activate("lm1")
    _decide({"consumer_id": "tool_choice", "route": "enforced", "chosen": "x", "confidence": 0.9})
    assert eid and store.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0] == 1
    assert memory_live.stats()["tapped"] == 0 and _tick(live) == []
    monkeypatch.setenv("IRIS_MEMORY_LIVE", "1")
    me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1", chain=False)
    assert len(_items(_tick(live), "memory_event", "events")) == 1


# ── a failing tap or broadcast never fails the writer ──────────────────────

def test_a_failing_broadcast_never_fails_the_writer(store, live):
    def boom(msg):
        raise RuntimeError("socket gone")

    memory_live.set_sender(boom)
    eid = me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1", chain=False)
    assert eid
    memory_live.flush_once()                               # must not raise
    assert memory_live.stats()["send_failed"] == 1
    assert store.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0] == 1


def test_a_failing_tap_never_fails_the_writer(store, lmconn, ledger, live, monkeypatch):
    def boom(kind, item):
        raise RuntimeError("buffer broke")

    monkeypatch.setattr(memory_live, "_push", boom)
    assert me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1", chain=False)
    assert LandmarkIndex(lmconn).activate("lm1") is None
    _decide({"consumer_id": "tool_choice", "route": "enforced", "chosen": "x", "confidence": 0.9})
    assert len(ledger) == 1
    assert lmconn.execute("SELECT activation_count FROM mycelium_landmarks WHERE landmark_id='lm1'"
                          ).fetchone()[0] == 1


def test_the_websocket_sender_never_raises_into_the_tick(live, monkeypatch):
    """The real sender with a broken manager: the tick logs and counts, the writer is untouched."""
    memory_live.set_sender(None)

    class _Loop:
        def is_running(self):
            return True

    class _Ws:
        def get_connection_count(self):
            return 1

        def broadcast(self, msg):
            raise RuntimeError("broadcast exploded")

    gw = type("GW", (), {"_main_loop": _Loop(), "_ws_manager": _Ws()})()
    monkeypatch.setitem(sys.modules, "backend.iris_gateway", types.SimpleNamespace(_iris_gateway=gw))
    memory_live.landmark_update("lm1", "activated", activation_count=1)
    memory_live.flush_once()                               # must not raise
    assert memory_live.stats()["send_failed"] == 1


# ── the tap runs AFTER the write ───────────────────────────────────────────

def test_a_failed_write_broadcasts_nothing(store, lmconn, ledger, live, monkeypatch):
    def refuse(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    # a row outside the alphabet is refused before any write
    assert me.emit_event(store, label="CORRECTION", evidence="vibes", thread_id="t1") is None
    monkeypatch.setattr(me, "app_write", refuse)
    assert me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1", chain=False) is None
    monkeypatch.setattr(lm, "app_write", refuse)
    with pytest.raises(sqlite3.OperationalError):
        LandmarkIndex(lmconn).activate("lm1")
    with pytest.raises(sqlite3.OperationalError):
        lm.add_landmark_evidence(lmconn, "lm1", "task_complete", "ep", "s1")
    # the ledger: a row the store refused (falsy) is not a decision
    monkeypatch.setattr(_ffi, "ffi_ingest_event", lambda **kw: False)
    _decide({"consumer_id": "tool_choice", "route": "enforced", "chosen": "x", "confidence": 0.9})
    assert memory_live.stats()["tapped"] == 0 and _tick(live) == []


def test_the_event_tap_fires_after_the_row_is_readable(store, live, monkeypatch):
    seen = {}
    real = memory_live.memory_event

    def spy(**kw):
        seen["row"] = store.execute("SELECT label FROM memory_events WHERE event_id = ?",
                                    (kw["event_id"],)).fetchone()
        return real(**kw)

    monkeypatch.setattr(memory_live, "memory_event", spy)
    me.emit_event(store, label="CORRECTION", evidence="user", thread_id="t1", chain=False)
    assert seen["row"] == ("CORRECTION",), "the tap fired before the row was written"
