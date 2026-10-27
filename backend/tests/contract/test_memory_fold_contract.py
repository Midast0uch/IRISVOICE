"""REQ-4 AC2: near-duplicates of one strand fold into one canonical row.

A fold is a REFERENCE, not a delete: the folded row keeps its text and points
at the canonical (``folded_into``), recall reads ``folded_into IS NULL`` only,
and ``unfold`` puts the copies back. The fold never crosses a Kyudo zone and
never touches a pinned chunk. These tests fail on the code before 2026-10-27
(no folded_into column, no fold pass, recall shipped every copy).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from backend.memory import chunk_fts, fold_chunks, recall_reach, vector_quant
from backend.memory.embedding import BACKEND_LFM

DIM = 1024


def _unit(v):
    return (v / np.linalg.norm(v)).astype("<f4")


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    recall_reach._INDEXES.pop(path, None)
    yield path
    recall_reach._INDEXES.pop(path, None)


def _insert(con, cid, vec, content, *, session="sess-a", ctype="context_fragment",
            zone="trusted", retrieved=0):
    fp, code, scale = vector_quant.compress(vec)
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "embedding, timestamp, embedding_backend, retrieval_count, vec_fp, vec_i8, vec_scale) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, session, ctype, zone, content, vec.tobytes(), "2026-10-27 11:00:00",
         BACKEND_LFM, retrieved, fp, code, scale),
    )


def _seed_duplicates(path):
    """A (canonical, retrieved most), B and C near-copies of A, D unrelated."""
    rng = np.random.default_rng(41)
    a = _unit(rng.standard_normal(DIM))
    b = _unit(a + 0.01 * rng.standard_normal(DIM))     # cosine ~ 0.9999
    c = a                                              # cosine 1.0
    d = _unit(rng.standard_normal(DIM))                # cosine ~ 0
    con = sqlite3.connect(path)
    _insert(con, "chunkA", a, "alpha content zebra", retrieved=5)
    _insert(con, "chunkB", b, "beta content zebra")
    _insert(con, "chunkC", c, "gamma content zebra")
    _insert(con, "chunkD", d, "delta content")
    con.commit()
    con.close()
    return a


def test_near_duplicates_fold_into_the_most_retrieved_row(store):
    path = store
    _seed_duplicates(path)
    con = sqlite3.connect(path)
    box: dict = {}
    fold_chunks.fold_pass(box, con, scan_groups=10)
    res = box["result"]
    assert not res.get("error")
    assert res["rows_folded"] == 2, "B and C fold; D is not a near-duplicate"

    rows = dict(con.execute("SELECT id, folded_into FROM context_chunks").fetchall())
    assert rows["chunkA"] is None, "the canonical row stays recallable"
    assert rows["chunkB"] == "chunkA" and rows["chunkC"] == "chunkA"
    assert rows["chunkD"] is None
    # a fold is a reference, not a delete: every row keeps its text
    kept = con.execute("SELECT count(*) FROM context_chunks").fetchone()[0]
    assert kept == 4
    assert fold_chunks.counts(con) == {"rows": 2, "groups": 1}
    con.close()


def test_a_fold_never_crosses_zones_or_types(store):
    path = store
    rng = np.random.default_rng(41)
    a = _unit(rng.standard_normal(DIM))
    con = sqlite3.connect(path)
    _insert(con, "same", a, "same vector")
    _insert(con, "other-zone", a, "same vector", zone="reference")
    _insert(con, "other-type", a, "same vector", ctype="der_output")
    _insert(con, "other-strand", a, "same vector", session="sess-b")
    con.commit()
    box: dict = {}
    fold_chunks.fold_pass(box, con, scan_groups=10)
    assert box["result"]["rows_folded"] == 0, (
        "an identical vector in another zone, type or strand is NOT a fold candidate"
    )
    con.close()


def test_a_pinned_chunk_is_never_folded(store):
    path = store
    _seed_duplicates(path)
    con = sqlite3.connect(path)
    # the pin-links table belongs to the wider store schema, not EpisodicStore's;
    # create it with the production columns when the fixture store lacks it
    con.execute(
        "CREATE TABLE IF NOT EXISTS mycelium_pin_links ("
        "link_id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, "
        "source_id TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, "
        "relationship TEXT NOT NULL, weight REAL DEFAULT 1.0, created_at REAL NOT NULL)")
    con.execute(
        "INSERT INTO mycelium_pin_links (source_type, source_id, target_type, target_id, "
        "relationship, created_at) VALUES ('pin', 'pin-1', 'chunk', 'chunkB', 'references', 0)")
    con.commit()
    box: dict = {}
    fold_chunks.fold_pass(box, con, scan_groups=10)
    rows = dict(con.execute("SELECT id, folded_into FROM context_chunks").fetchall())
    assert rows["chunkB"] is None, "a pinned chunk is never folded"
    assert rows["chunkC"] == "chunkA", "the unpinned copy still folds"
    con.close()


def test_recall_and_words_skip_folded_rows(store):
    path = store
    a = _seed_duplicates(path)
    con = sqlite3.connect(path)

    # before the fold: the fingerprint index holds all four rows
    idx = recall_reach.ChunkFingerprints(path)
    idx.build(con)
    q = a
    assert len(idx.candidates(con, q, BACKEND_LFM, m=10)) == 4

    box: dict = {}
    fold_chunks.fold_pass(box, con, scan_groups=10)
    idx2 = recall_reach.ChunkFingerprints(path)
    idx2.build(con)
    got = idx2.candidates(con, q, BACKEND_LFM, m=10)
    assert len(got) == 2, "the index must not hold the folded copies"

    # exact words: a token only the folded row carries is gone from candidates
    con.execute("INSERT INTO context_chunks_fts(context_chunks_fts) VALUES('rebuild')")
    con.commit()
    assert set(chunk_fts.search(con, "gamma")) == set(), "a folded row is not a keyword candidate"
    assert con.execute("SELECT rowid FROM context_chunks WHERE id = 'chunkA'").fetchone()[0] \
        in chunk_fts.search(con, "alpha")
    con.close()


def test_unfold_puts_the_copies_back(store):
    path = store
    _seed_duplicates(path)
    con = sqlite3.connect(path)
    fold_chunks.fold_pass({}, con, scan_groups=10)
    assert fold_chunks.counts(con)["rows"] == 2
    assert fold_chunks.unfold(con, "chunkA") == 2
    assert fold_chunks.counts(con) == {"rows": 0, "groups": 0}
    rows = dict(con.execute("SELECT id, folded_into FROM context_chunks").fetchall())
    assert all(v is None for v in rows.values()), "undo restores every copy"
    con.close()
