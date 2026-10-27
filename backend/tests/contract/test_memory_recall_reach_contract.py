"""Recall reach: every stored chunk can be recalled, not only the newest 200
(specs/memory-recall-reach REQ-1).

Live 2026-10-27: retrieve_context_chunks scored the newest 200 rows of its
filter - research recall reached 200 of 1,777 summaries, a turn's session
recall ~1.5% of its biggest session. Driven on a temp store with the real
schema, real EpisodicStore, real fingerprints; only the query embedding is a
fixed vector (no model).
"""
from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

import numpy as np
import pytest

from backend.memory import recall_reach
from backend.memory.embedding import BACKEND_LFM

DIM = 1024
N = 600   # 3 x the old window


def _unit(v):
    return (v / np.linalg.norm(v)).astype("<f4")


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    st = EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    rng = np.random.default_rng(3)
    vecs = [_unit(rng.standard_normal(DIM)) for _ in range(N)]
    con = sqlite3.connect(path)
    for i, v in enumerate(vecs):   # row 0 is the OLDEST
        con.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, embedding, timestamp, "
            "embedding_backend) VALUES (?,?,?,?,?,?,?,?)",
            (f"c{i}", "sess-a" if i % 2 == 0 else "sess-b", "research_summary" if i < 300 else "context_fragment",
             "reference" if i < 300 else "trusted", f"chunk number {i}", v.tobytes(),
             f"2026-10-{1 + i // 100:02d} {i % 24:02d}:00:00", BACKEND_LFM))
    con.commit()
    con.close()
    recall_reach._INDEXES.pop(path, None)
    yield SimpleNamespace(store=st, path=path, vecs=vecs)
    recall_reach._INDEXES.pop(path, None)


def _near(v, rng_seed=5, noise=0.15):
    rng = np.random.default_rng(rng_seed)
    return _unit(v + noise * rng.standard_normal(DIM) / np.sqrt(DIM) * 10)


def _ready(path, conn_factory, timeout=20.0):
    idx = recall_reach.index_for(path, conn_factory)
    t0 = time.time()
    while not idx._ready and time.time() - t0 < timeout:
        time.sleep(0.05)
    assert idx._ready, "fingerprints never warmed"
    return idx


def test_the_oldest_matching_chunk_is_reachable(store):
    con = sqlite3.connect(store.path)
    idx = recall_reach.ChunkFingerprints(store.path)
    idx.build(con)
    q = _near(store.vecs[0])
    rows = idx.candidates(con, q, BACKEND_LFM)
    assert 1 in rows                                             # rowid of c0, the oldest of 600
    # the filter holds: c0 is a reference research summary of sess-a
    assert 1 in idx.candidates(con, q, BACKEND_LFM, chunk_types=["research_summary"], zones=["reference"])
    assert 1 not in idx.candidates(con, q, BACKEND_LFM, zones=["trusted"])
    assert 1 not in idx.candidates(con, q, BACKEND_LFM, session_id="sess-b")
    assert idx.candidates(con, q, "another-backend") == []      # never across embedding spaces
    con.close()


def test_new_chunks_are_added_once(store):
    con = sqlite3.connect(store.path)
    idx = recall_reach.ChunkFingerprints(store.path)
    idx.build(con)
    v = _unit(np.random.default_rng(9).standard_normal(DIM))
    con.execute("INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, embedding, timestamp, "
                "embedding_backend) VALUES ('new', 'sess-a', 'context_fragment', 'trusted', 'new one', ?, "
                "'2026-10-27 12:00:00', ?)", (v.tobytes(), BACKEND_LFM))
    con.commit()
    assert N + 1 in idx.candidates(con, _near(v), BACKEND_LFM)
    idx.refresh(con)
    assert idx._n == N + 1
    assert len(set(idx._rowids[:idx._n].tolist())) == N + 1      # each row once
    con.close()


def test_recall_returns_a_relevant_chunk_older_than_the_newest_200(store):
    """The store path end to end: c0 is the oldest row of 600; the newest-200 path can never return it."""
    st = store.store
    q = _near(store.vecs[0])
    st._embed = SimpleNamespace(encode_with_meta=lambda _t: SimpleNamespace(vector=q.tolist(), backend=BACKEND_LFM))
    _ready(store.path, lambda: st.db)
    out = st.retrieve_context_chunks("what was chunk zero", limit=5, min_similarity=0.2,
                                     chunk_types=["research_summary"], zones=["reference"])
    assert "chunk number 0" in out


def test_while_the_index_warms_recall_keeps_the_old_path(store, monkeypatch):
    st = store.store
    q = _near(store.vecs[N - 1])          # the newest row: the old path finds it
    st._embed = SimpleNamespace(encode_with_meta=lambda _t: SimpleNamespace(vector=q.tolist(), backend=BACKEND_LFM))
    monkeypatch.setattr(recall_reach.ChunkFingerprints, "build", lambda self, conn: None)   # never ready
    before = recall_reach.COUNTERS["fallback_warming"]
    out = st.retrieve_context_chunks("the newest", limit=3, min_similarity=0.2)
    assert f"chunk number {N - 1}" in out
    assert recall_reach.COUNTERS["fallback_warming"] == before + 1   # counted, never silent
