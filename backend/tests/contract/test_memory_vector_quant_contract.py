"""REQ-4 AC1: the int8 code and the fingerprint ARE the recall forms.

The store kept a 4,096-byte float per chunk. These tests pin the three things
that make dropping it safe:

* the int8 code restores the same direction (cosine when scored as int8);
* a new chunk carries both forms at insert, so a drop never loses a vector;
* after the float is NULL, recall still scores the row - from the code.

They fail on the code before 2026-10-27 (no vec_i8 column, no drop path).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from backend.memory import recall_reach, vector_quant
from backend.memory.embedding import BACKEND_LFM

DIM = 1024


def _unit(v):
    return (v / np.linalg.norm(v)).astype("<f4")


def _cos(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


# ── the form itself ─────────────────────────────────────────────────────

def test_int8_keeps_the_direction_to_three_decimals():
    rng = np.random.default_rng(3)
    for _ in range(20):
        v = _unit(rng.standard_normal(DIM))
        fp, code, scale = vector_quant.compress(v)
        assert len(fp) == vector_quant.FP_BYTES and len(code) == vector_quant.I8_BYTES
        back = vector_quant.decompress(code, scale)
        assert _cos(v, back) >= 0.999, "symmetric int8 must keep the cosine"


def test_fingerprint_is_the_sign_pattern():
    v = _unit(np.random.default_rng(5).standard_normal(DIM))
    fp = vector_quant.fingerprint(v)
    assert fp == np.packbits(v > 0).tobytes()
    fp2, code, scale = vector_quant.compress(v)
    assert fp2 == fp, "the stored fingerprint is the float's own signs"
    # A component that rounds to zero in int8 loses its sign, so the stored
    # fingerprint is NOT re-derived from the code - that is why it is persisted.
    back = vector_quant.decompress(code, scale)
    moved = int(np.unpackbits(np.packbits(back > 0) ^ np.frombuffer(fp, dtype=np.uint8)).sum())
    assert moved < 0.02 * DIM, f"{moved} signs moved; the code must not rewrite the index"


def test_a_bad_vector_yields_no_forms():
    assert vector_quant.compress([0.1, 0.2]) == (None, None, None)
    assert vector_quant.fingerprint([np.nan] * DIM) is None
    assert vector_quant.decompress(b"\x00" * 8, 1.0) is None


def test_vector_of_prefers_the_float_and_falls_back_to_the_code():
    v = _unit(np.random.default_rng(9).standard_normal(DIM))
    _fp, code, scale = vector_quant.compress(v)
    float_blob = v.tobytes()

    got = vector_quant.vector_of(float_blob, code, scale)
    assert np.allclose(got, v), "the float is the truth while it exists"
    got = vector_quant.vector_of(None, code, scale)
    assert _cos(got, v) >= 0.999, "after the drop the code stands in for the float"
    assert vector_quant.vector_of(None, None, None) is None
    # an older backend's 768-dim float is still readable
    assert len(vector_quant.vector_of(np.zeros(768, dtype="<f4").tobytes())) == 768


# ── the store ───────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    # Seed a PLAINTEXT file first: _seed and the tests read the store with plain sqlite3, and
    # open_encrypted_memory keeps an existing plaintext file plaintext. Without the seed a new file is
    # encrypted under the .venv and every test failed with "file is not a database" (2026-11-09, also on HEAD).
    _plain = sqlite3.connect(path)
    _plain.execute("PRAGMA journal_mode=WAL")
    _plain.execute("CREATE TABLE _plain_seed (x INTEGER)")
    _plain.commit()
    _plain.close()
    st = EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    recall_reach._INDEXES.pop(path, None)
    yield path, st
    recall_reach._INDEXES.pop(path, None)


def _seed(path, n=12, with_compact=True, session="sess-a", ctype="context_fragment"):
    rng = np.random.default_rng(21)
    con = sqlite3.connect(path)
    for i in range(n):
        v = _unit(rng.standard_normal(DIM))
        fp, code, scale = vector_quant.compress(v) if with_compact else (None, None, None)
        con.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
            "embedding, timestamp, embedding_backend, vec_fp, vec_i8, vec_scale) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"c{i}", session, ctype, "trusted", f"chunk {i}", v.tobytes(),
             f"2026-10-27 10:{i:02d}:00", BACKEND_LFM, fp, code, scale),
        )
    con.commit()
    con.close()


def test_a_new_chunk_is_written_with_both_forms(store):
    path, st = store

    class _Meta:
        def __init__(self, v):
            self.vector = v
            self.backend = BACKEND_LFM

    class _Embed:
        def __init__(self):
            self.rng = np.random.default_rng(31)

        def encode_with_meta(self, _text):
            return _Meta(list(_unit(self.rng.standard_normal(DIM))))

    st._embed = _Embed()
    ids = st.fragment_and_store("the retry ladder shrinks the clip to 320 chars for a dense chunk",
                                "sess-w", chunk_type="context_fragment")
    assert ids
    con = sqlite3.connect(path)
    fp, code, scale = con.execute(
        "SELECT vec_fp, vec_i8, vec_scale FROM context_chunks WHERE id = ?", (ids[0],)).fetchone()
    con.close()
    assert fp is not None and len(fp) == vector_quant.FP_BYTES
    assert code is not None and len(code) == vector_quant.I8_BYTES
    assert scale and scale > 0, "a model vector has a positive scale"


def test_compress_backfills_an_old_row_and_drop_keeps_recall(store):
    from backend.memory.vector_compress import compress_into

    path, st = store
    _seed(path, with_compact=False)
    con = sqlite3.connect(path)
    box: dict = {}
    compress_into(box, con, 0, scan_rows=100, dim=DIM, drop=None, dry_run=False)
    res = box["result"]
    assert res["compressed"] == 12 and not res.get("error")
    filled = con.execute(
        "SELECT count(*) FROM context_chunks WHERE vec_i8 IS NOT NULL AND vec_fp IS NOT NULL"
    ).fetchone()[0]
    assert filled == 12

    # AC1: drop the float for this type; recall must still score from the code.
    # The query stub returns c3's own vector, so the ranking is deterministic
    # (a random unit vector is ~0 cosine from every seeded row).
    rng = np.random.default_rng(21)
    target = None
    for i in range(12):
        v = _unit(rng.standard_normal(DIM))
        if i == 3:
            target = v

    class _Meta:
        vector = target.tolist()   # compare_embeddings takes a list, as the service returns
        backend = BACKEND_LFM

    class _Embed:
        @staticmethod
        def encode_with_meta(_text):
            return _Meta()

    st._embed = _Embed()
    before = st.retrieve_context_chunks("chunk 3", session_id="sess-a", limit=3)
    assert before and "chunk 3" in before[0], "the seeded row must be scoreable while the float exists"
    compress_into({}, con, 0, scan_rows=1, dim=DIM, drop=["context_fragment"], dry_run=False)
    floats = con.execute(
        "SELECT count(*) FROM context_chunks WHERE embedding IS NOT NULL").fetchone()[0]
    assert floats == 0, "the drop must remove the float for the named type"
    after = st.retrieve_context_chunks("chunk 3", session_id="sess-a", limit=3)
    assert after and "chunk 3" in after[0], "a row scored from int8 is still recallable (AC1)"
    con.close()


def test_fingerprint_only_rows_still_reach_the_index(store):
    """The warm-up reads vec_fp when the float is NULL (1,152 B/row, not 4,096)."""
    path, _st = store
    _seed(path, n=8, with_compact=False)
    con = sqlite3.connect(path)
    from backend.memory.vector_compress import compress_into

    compress_into({}, con, 0, scan_rows=100, dim=DIM, drop=["context_fragment"], dry_run=False)
    con.execute("UPDATE context_chunks SET embedding = NULL")
    con.commit()

    idx = recall_reach.ChunkFingerprints(path)
    idx.build(con)
    assert idx._n == 8, "every row with a fingerprint must be in RAM"
    got = idx.candidates(con, _unit(np.random.default_rng(21).standard_normal(DIM)),
                         BACKEND_LFM, m=8)
    assert got and len(got) == 8
    con.close()
