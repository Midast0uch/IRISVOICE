"""REQ-2 AC3: a repaired row must change what recall sees.

The repair lane rewrites a row's vector in place. ``recall_reach.refresh`` only
appends rows ABOVE the highest rowid it has read, so without an explicit
updated-rowids hook the RAM fingerprint would keep the old (wrong) vector for
the life of the process. These tests fail on the code before 2026-10-27.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from backend.memory import recall_reach
from backend.memory.embedding import BACKEND_LFM, _hash_embed
from backend.memory.repair_vectors import is_suspect

DIM = 1024


def _unit(v):
    return (v / np.linalg.norm(v)).astype("<f4")


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
    rng = np.random.default_rng(11)
    con = sqlite3.connect(path)
    for i in range(20):
        v = _unit(rng.standard_normal(DIM))
        con.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
            "embedding, timestamp, embedding_backend) VALUES (?,?,?,?,?,?,?,?)",
            (f"c{i}", "sess-a", "context_fragment", "trusted", f"chunk {i}",
             v.tobytes(), f"2026-10-27 {i:02d}:00:00", BACKEND_LFM),
        )
    con.commit()
    con.close()
    recall_reach._INDEXES.pop(path, None)
    yield path
    recall_reach._INDEXES.pop(path, None)


def test_update_rows_replaces_the_fingerprint(store):
    con = sqlite3.connect(store)
    query = _unit(np.random.default_rng(99).standard_normal(DIM))
    # Rowid 1 starts at the antipode of the query: the maximum Hamming distance,
    # so it cannot be among the nearest 5 by chance.
    con.execute(
        "UPDATE context_chunks SET embedding = ? WHERE rowid = 1", ((-query).tobytes(),)
    )
    con.commit()

    idx = recall_reach.ChunkFingerprints(store)
    idx.build(con)
    assert 1 not in idx.candidates(con, query, BACKEND_LFM, m=5)

    con.execute(
        "UPDATE context_chunks SET embedding = ? WHERE rowid = 1", (query.tobytes(),)
    )
    con.commit()
    assert 1 not in idx.candidates(con, query, BACKEND_LFM, m=5), (
        "refresh must not pick up an edited row (that is what update_rows is for)"
    )

    assert idx.update_rows(con, [1]) == 1
    assert 1 in idx.candidates(con, query, BACKEND_LFM, m=5), (
        "after update_rows the index must score the new vector"
    )
    con.close()


def test_update_if_indexed_never_starts_a_build(store):
    con = sqlite3.connect(store)
    recall_reach._INDEXES.pop(store, None)
    assert recall_reach.update_if_indexed(store, con, [1]) == 0
    assert store not in recall_reach._INDEXES, "a repair script must not pay for a warm-up"
    con.close()


def test_the_hash_fallback_carries_the_suspect_signature():
    vec = _hash_embed("insert into context_chunks values", DIM)
    blob = np.asarray(vec, dtype="<f4").tobytes()
    assert is_suspect(blob, DIM), "a hash vector is sparse; that is the repair signal"

    dense = _unit(np.random.default_rng(7).standard_normal(DIM))
    assert not is_suspect(dense.tobytes(), DIM)
    assert not is_suspect(b"", DIM)
    assert not is_suspect(dense[: 4 * (DIM - 1)].tobytes(), DIM)
