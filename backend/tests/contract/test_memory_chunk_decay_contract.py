"""REQ-5: chunks decay by the ONE Kyudo law, within a budget, never the protected.

The old ``cleanup_stale_chunks`` was a fixed 72-hour age rule with no production
caller. The law (``backend/memory/chunk_decay.py``):

    strength = 1 - rate x m_zone x m_outcome x active_days x a(retrieval_count)

- the zone's trust channel sets the rate (trusted 1.0, tool 1.5, reference 3.0);
- use slows the fade (a(n) over retrieval_count; >= CRYSTALLIZE_THRESHOLD never
  pruned), RECALL_HELPED slows it more (0.5), RECALL_MISLED speeds it (1.8);
- the same pass enforces the per-zone budget, oldest unused first (AC2), and
  types every prune MEMORY_PRUNED with its reason;
- a pinned chunk or one that backs a LIVE claim is never pruned (AC3).

These tests fail on the code before 2026-10-27 (no law, no budget, no events).
"""
from __future__ import annotations

import sqlite3
import time

import numpy as np
import pytest

from backend.memory import chunk_decay, vector_quant

DIM = 1024
DAY = 86400.0


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    con = sqlite3.connect(path)
    # the events table belongs to the wider store schema; create the columns
    # the outcome multipliers read when the fixture store lacks it
    con.execute(
        "CREATE TABLE IF NOT EXISTS memory_events ("
        "event_id TEXT, label TEXT, thread_id TEXT, payload TEXT, created_at REAL)")
    # the clock counts ACTIVE days: one episode per day for the last 120 days,
    # so a chunk seeded N days old has N active days behind it
    now = time.time()
    for i in range(120):
        day = now - i * DAY
        con.execute(
            "INSERT INTO episodes (id, session_id, task_summary, outcome_type, timestamp) "
            "VALUES (?, 'sess-clock', 'activity', 'success', ?)",
            (f"ep{i}", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(day))),
        )
    con.commit()
    con.close()
    yield path


def _chunk(con, cid, *, days=0.0, retrieved=0, session="sess-a", zone="trusted",
           now=None):
    rng = np.random.default_rng(abs(hash(cid)) % 10000)
    vec = (rng.standard_normal(DIM) / 32).astype("<f4")
    fp, code, scale = vector_quant.compress(vec)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime((now or time.time()) - days * DAY))
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "embedding, timestamp, embedding_backend, retrieval_count, vec_fp, vec_i8, vec_scale) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, session, "context_fragment", zone, f"content {cid}", vec.tobytes(), ts,
         "lfm25-emb-350m", retrieved, fp, code, scale),
    )


def _run(path, **kw):
    con = sqlite3.connect(path)
    box: dict = {}
    chunk_decay.decay_pass(box, con, **kw)
    con.commit()
    con.close()
    return box["result"]


def test_the_law_prunes_the_unused_and_keeps_the_used(store):
    path = store
    now = time.time()
    con = sqlite3.connect(path)
    _chunk(con, "old-unused", days=60, now=now)
    _chunk(con, "old-crystallized", days=60, retrieved=chunk_decay.CRYSTALLIZE_THRESHOLD, now=now)
    _chunk(con, "fresh", days=1, now=now)
    con.commit()
    con.close()

    res = _run(path, now=now)
    assert not res.get("error")
    assert res["pruned"] == 1, "only the old unused chunk crossed the floor"
    con = sqlite3.connect(path)
    left = {r[0] for r in con.execute("SELECT id FROM context_chunks")}
    con.close()
    assert left == {"old-crystallized", "fresh"}, (
        "use (crystallization) and youth both protect; age alone does not"
    )


def test_the_zone_sets_the_rate(store):
    path = store
    now = time.time()
    con = sqlite3.connect(path)
    _chunk(con, "ref-old", days=30, zone="reference", now=now)   # m=3.0 -> ~17 days
    _chunk(con, "trusted-old", days=30, zone="trusted", now=now)  # m=1.0 -> 50 days
    con.commit()
    con.close()

    res = _run(path, now=now)
    con = sqlite3.connect(path)
    left = {r[0] for r in con.execute("SELECT id FROM context_chunks")}
    con.close()
    assert left == {"trusted-old"}, (
        "an EXTERNAL-channel chunk fades 3x faster than a trusted one of the same age"
    )


def test_helped_slows_the_fade_and_misled_speeds_it(store):
    path = store
    now = time.time()
    con = sqlite3.connect(path)
    _chunk(con, "helped", days=40, session="sess-helped", now=now)
    _chunk(con, "plain", days=40, session="sess-plain", now=now)
    _chunk(con, "misled", days=40, session="sess-misled", now=now)
    for i in range(3):
        con.execute("INSERT INTO memory_events (event_id, label, thread_id, payload, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (f"e{i}", "RECALL_HELPED", "sess-helped", "{}", now))
        con.execute("INSERT INTO memory_events (event_id, label, thread_id, payload, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (f"m{i}", "RECALL_MISLED", "sess-misled", "{}", now))
    con.commit()
    con.close()

    _run(path, now=now)
    con = sqlite3.connect(path)
    left = {r[0] for r in con.execute("SELECT id FROM context_chunks")}
    con.close()
    assert "helped" in left, "a strand whose recalls helped decays at half speed (40 < 100 days)"
    assert "plain" in left, "an untouched trusted chunk survives 40 of its 50 days"
    assert "misled" not in left, "a strand whose recalls misled decays 1.8x faster (40 > 28 days)"


def test_pinned_and_claim_backed_chunks_are_never_pruned(store):
    path = store
    now = time.time()
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS mycelium_pin_links ("
        "link_id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, "
        "source_id TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, "
        "relationship TEXT NOT NULL, weight REAL DEFAULT 1.0, created_at REAL NOT NULL)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS mycelium_landmarks ("
        "landmark_id TEXT PRIMARY KEY, micro_abstract_text TEXT, label TEXT, "
        "tier TEXT DEFAULT 'candidate', evidence TEXT DEFAULT '[]', absorbed INTEGER DEFAULT 0)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS memory_chain ("
        "entry_id TEXT, thread_id TEXT, session_id TEXT, sequence INTEGER, role TEXT, "
        "content TEXT, metadata TEXT, result TEXT, distilled INTEGER DEFAULT 0, "
        "created_at REAL, chain_id TEXT, landmark_id TEXT)")
    _chunk(con, "pinned", days=60, now=now)
    _chunk(con, "claim-backed", days=60, now=now)
    _chunk(con, "dead-claim", days=60, now=now)
    _chunk(con, "plain-old", days=60, now=now)
    con.execute("INSERT INTO mycelium_pin_links (source_type, source_id, target_type, "
                "target_id, relationship, created_at) "
                "VALUES ('pin', 'p1', 'chunk', 'pinned', 'references', 0)")
    import json as _json

    con.execute("INSERT INTO mycelium_landmarks (landmark_id, tier, absorbed) VALUES ('c-live', 'landmark', 0)")
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, tier, absorbed) VALUES ('c-dead', 'landmark', 1)")
    con.execute("INSERT INTO memory_chain (entry_id, thread_id, landmark_id, distilled, metadata) "
                "VALUES ('x', 'claim-c-live', 'c-live', 1, ?)",
                (_json.dumps({"chunk_refs": ["claim-backed"]}),))
    con.execute("INSERT INTO memory_chain (entry_id, thread_id, landmark_id, distilled, metadata) "
                "VALUES ('y', 'claim-c-dead', 'c-dead', 1, ?)",
                (_json.dumps({"chunk_refs": ["dead-claim"]}),))
    con.commit()
    con.close()

    _run(path, now=now)
    con = sqlite3.connect(path)
    left = {r[0] for r in con.execute("SELECT id FROM context_chunks")}
    con.close()
    assert "pinned" in left and "claim-backed" in left, "AC3: pinned and live-claim chunks stay"
    assert "dead-claim" not in left, "an ABSORBED claim no longer protects its chunks"
    assert "plain-old" not in left


def test_the_budget_prunes_oldest_unused_first_and_types_the_reason(store, monkeypatch):
    path = store
    now = time.time()
    con = sqlite3.connect(path)
    # fresh rows: the LAW prunes nothing (all far under the 50-day floor);
    # only the BUDGET can remove them
    _chunk(con, "young-used", days=1, retrieved=9, now=now)
    _chunk(con, "young-a", days=2, now=now)
    _chunk(con, "young-b", days=3, now=now)
    _chunk(con, "young-c", days=4, now=now)
    con.commit()
    con.close()

    monkeypatch.setattr(chunk_decay, "ZONE_BUDGET", {"trusted": (2, 10 ** 12)})
    events: list = []
    monkeypatch.setattr(
        chunk_decay, "_emit_landmark_event",
        lambda conn, label, ids, **kw: events.append((label, kw.get("payload"))),
    )
    res = _run(path, now=now)
    con = sqlite3.connect(path)
    left = {r[0] for r in con.execute("SELECT id FROM context_chunks")}
    con.close()
    assert left == {"young-used", "young-a"}, (
        "the budget keeps the newest rows and the used row, oldest unused first"
    )
    assert res["pruned"] == 2
    assert any(label == "MEMORY_PRUNED" and (p or {}).get("reason") == "zone_budget"
               for label, p in events), "every prune is typed MEMORY_PRUNED with its reason"
