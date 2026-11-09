"""REQ-7: recall ranks by what the memory knows - in shadow beside the live rank.

The memory-native rank (``backend/memory/memory_rank.py``) computes per scored
row: Kyudo trust (the zone's channel), claim evidence (backs a live claim),
helped/misled history of the strand, use with decay, and Sigma affinity. It
ranks by them IN SHADOW: the live ranking is untouched while ``LIVE`` is False,
and every recall records both rankings (``memory_rank_shadow``) as the evidence
for the Oracle bar. These tests fail on the code before 2026-10-27 (no features,
no shadow table, no switch).
"""
from __future__ import annotations

import json
import sqlite3
import time

import numpy as np
import pytest

from backend.memory import memory_rank, vector_quant

DIM = 1024


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    # Seed a PLAINTEXT file first: this fixture reads the store with plain
    # sqlite3, and open_encrypted_memory keeps an existing plaintext file
    # plaintext. Without the seed a NEW file is encrypted under the .venv
    # (sqlcipher3 importable) and the fixture failed with "file is not a
    # database" (2026-11-09, also on HEAD).
    _seed = sqlite3.connect(path)
    _seed.execute("PRAGMA journal_mode=WAL")
    _seed.execute("CREATE TABLE _plain_seed (x INTEGER)")
    _seed.commit()
    _seed.close()
    EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    con = sqlite3.connect(path)
    for ddl in (
        "CREATE TABLE IF NOT EXISTS mycelium_landmarks ("
        "landmark_id TEXT PRIMARY KEY, micro_abstract_text TEXT, label TEXT, "
        "tier TEXT DEFAULT 'candidate', evidence TEXT DEFAULT '[]', absorbed INTEGER DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS memory_chain ("
        "entry_id TEXT, thread_id TEXT, session_id TEXT, sequence INTEGER, role TEXT, "
        "content TEXT, metadata TEXT, result TEXT, distilled INTEGER DEFAULT 0, "
        "created_at REAL, chain_id TEXT, landmark_id TEXT, coords_to TEXT)",
        "CREATE TABLE IF NOT EXISTS memory_events ("
        "event_id TEXT, label TEXT, thread_id TEXT, payload TEXT, created_at REAL)",
    ):
        con.execute(ddl)
    con.commit()
    con.close()
    memory_rank._cache.clear()
    memory_rank.COUNTERS.update({k: 0 for k in memory_rank.COUNTERS})
    yield path
    memory_rank._cache.clear()


def _chunk(con, cid, vec, *, session, zone, ts, retrieved=0):
    fp, code, scale = vector_quant.compress(vec)
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "embedding, timestamp, embedding_backend, retrieval_count, vec_fp, vec_i8, vec_scale) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, session, "context_fragment", zone, f"content {cid}", vec.tobytes(), ts,
         "lfm25-emb-350m", retrieved, fp, code, scale),
    )


def _seed(path, vec):
    """Three chunks with the SAME cosine to the query, different memory features.

    live order (recency): A (newest), B, C (oldest)
    memory order:        C (backs a live claim), A (trusted), B (reference zone)
    """
    con = sqlite3.connect(path)
    _chunk(con, "chunkA", vec, session="sess-a", zone="trusted", ts="2026-10-27 12:00:00")
    _chunk(con, "chunkB", vec, session="sess-b", zone="reference", ts="2026-10-27 11:00:00")
    _chunk(con, "chunkC", vec, session="sess-c", zone="trusted", ts="2026-10-27 10:00:00")
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, tier, absorbed) "
                "VALUES ('claim-1', 'landmark', 0)")
    con.execute("INSERT INTO memory_chain (entry_id, thread_id, landmark_id, distilled, metadata) "
                "VALUES ('x', 'claim-claim-1', 'claim-1', 1, ?)",
                (json.dumps({"chunk_refs": ["chunkC"]}),))
    con.commit()
    con.close()


def test_the_rank_follows_the_features_not_the_cosine(store):
    path = store
    rng = np.random.default_rng(71)
    vec = (rng.standard_normal(DIM) / 32).astype("<f4")
    _seed(path, vec)
    con = sqlite3.connect(path)
    scored = [(1.0, "content chunkA", "chunkA"),
              (1.0, "content chunkB", "chunkB"),
              (1.0, "content chunkC", "chunkC")]
    info = {
        "chunkA": {"zone": "trusted", "session": "sess-a", "retrieval_count": 0,
                   "timestamp": "2026-10-27 12:00:00"},
        "chunkB": {"zone": "reference", "session": "sess-b", "retrieval_count": 0,
                   "timestamp": "2026-10-27 11:00:00"},
        "chunkC": {"zone": "trusted", "session": "sess-c", "retrieval_count": 0,
                   "timestamp": "2026-10-27 10:00:00"},
    }
    ranked, features = memory_rank.rank_rows(con, scored, info)
    order = [r[2] for r in ranked]
    assert order == ["chunkC", "chunkA", "chunkB"], (
        "same cosine: claim evidence first, then trust, then the external zone"
    )
    feats = {scored[i][2]: features[i] for i in range(3)}
    assert feats["chunkC"]["evidence"] == 1.0 and feats["chunkA"]["evidence"] == 0.0
    assert feats["chunkB"]["trust"] < feats["chunkA"]["trust"], (
        "the reference zone is the EXTERNAL channel: lower trust weight"
    )
    assert all(f["sigma"] is None for f in features), "no chain coords: absent, not zero"
    con.close()


def test_shadow_records_both_and_never_changes_the_live_result(store, monkeypatch):
    path = store
    from backend.memory.episodic import EpisodicStore
    from backend.memory import recall_reach

    recall_reach._INDEXES.pop(path, None)
    rng = np.random.default_rng(71)
    vec = (rng.standard_normal(DIM) / 32).astype("<f4")
    _seed(path, vec)

    class _Meta:
        def __init__(self, v):
            self.vector = v.tolist()
            self.backend = "lfm25-emb-350m"

    class _Embed:
        @staticmethod
        def encode_with_meta(_text):
            return _Meta(vec)

    st = EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    st._embed = _Embed()
    monkeypatch.setattr(memory_rank, "LIVE", False)

    live = st.retrieve_context_chunks("anything", session_id=None, limit=3, min_similarity=-1.0)
    assert live == ["content chunkA", "content chunkB", "content chunkC"], (
        "while LIVE is False the cosine+recency order is untouched"
    )
    con = sqlite3.connect(path)
    rows = con.execute("SELECT same, live_topk, shadow_topk FROM memory_rank_shadow").fetchall()
    con.close()
    assert rows, "every recall records both rankings (the Oracle bar's evidence)"
    same, live_topk, shadow_topk = rows[-1]
    assert json.loads(live_topk)[:3] == ["chunkA", "chunkB", "chunkC"]
    assert json.loads(shadow_topk)[:3] == ["chunkC", "chunkA", "chunkB"]
    assert not same, "the shadow disagrees with cosine here - that is the point of recording"


def test_the_live_switch_ranks_by_memory(store, monkeypatch):
    path = store
    from backend.memory.episodic import EpisodicStore
    from backend.memory import recall_reach

    recall_reach._INDEXES.pop(path, None)
    rng = np.random.default_rng(71)
    vec = (rng.standard_normal(DIM) / 32).astype("<f4")
    _seed(path, vec)

    class _Meta:
        def __init__(self, v):
            self.vector = v.tolist()
            self.backend = "lfm25-emb-350m"

    class _Embed:
        @staticmethod
        def encode_with_meta(_text):
            return _Meta(vec)

    st = EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    st._embed = _Embed()
    monkeypatch.setattr(memory_rank, "LIVE", True)
    ranked = st.retrieve_context_chunks("anything", session_id=None, limit=3, min_similarity=-1.0)
    assert ranked == ["content chunkC", "content chunkA", "content chunkB"], (
        "LIVE=True ranks by the memory features (the off switch is the same flag)"
    )


def test_zero_variance_is_counted_never_silent(store):
    path = store
    con = sqlite3.connect(path)
    scored = [(1.0, "a", "a"), (1.0, "b", "b")]
    info = {"a": {"zone": "trusted", "session": "s", "retrieval_count": 0, "timestamp": ""},
            "b": {"zone": "trusted", "session": "s", "retrieval_count": 0, "timestamp": ""}}
    before = memory_rank.COUNTERS["zero_variance"]
    memory_rank.rank_rows(con, scored, info)
    assert memory_rank.COUNTERS["zero_variance"] == before + 1, (
        "a feature with zero variance is a FAILURE (HIDDEN FAILURES), counted"
    )
    con.close()
