"""REQ-9 contract: a file is a node plus chunks, folds on change, never stores a float.

The pins:
  CT-F1  text becomes `chunk_type=file` rows with int8 + fingerprint and NO float
  CT-F2  the same bytes twice is a no-op (counted, not re-written)
  CT-F3  changed bytes add new chunks and FOLD the old ones (rows survive)
  CT-F4  an unextractable file still gets its node, is counted, and stores no chunk
  CT-F5  a file over the cap is truncated and says so
  CT-F6  the FTS trigger indexed the file text (no separate hook exists)
"""
import sqlite3

import numpy as np
import pytest

DIM = 1024
BACKEND = "lfm25-emb-350m"
TEXT = (
    "The zebraquux protocol governs how the quokka scheduler hands a turn to the "
    "worker pool. It states that a worker may hold one lease at a time and that a "
    "lease expires after the heartbeat misses three consecutive intervals."
)


@pytest.fixture()
def store(tmp_path):
    from backend.memory.embedding import Embedding
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    st = EpisodicStore(db_path=path, biometric_key=b"\0" * 32)

    class _Stub:
        """Deterministic, text-dependent vector. Replace the STORE's service, never
        the process-wide singleton (see test_memory_chunk_fts_contract)."""

        @staticmethod
        def encode_with_meta(text):
            v = np.zeros(DIM, dtype=np.float32)
            for i, ch in enumerate(text[:128]):
                v[i % DIM] += (ord(ch) % 89) / 89.0
            n = float(np.linalg.norm(v)) or 1.0
            return Embedding(vector=(v / n).tolist(), backend=BACKEND,
                             chunk_count=1, truncated=False)

    st._embed = _Stub()
    st._path = path
    yield st


def _rows(store, path):
    return store.db.execute(
        """SELECT id, content, embedding, vec_i8, vec_fp, folded_into, zone, tool_name
           FROM context_chunks WHERE chunk_type = 'file' AND tool_name = ?""",
        (path,),
    ).fetchall()


def test_ct_f1_text_becomes_compressed_file_chunks(store, tmp_path):
    from backend.memory import file_ingest

    f = tmp_path / "notes.md"
    f.write_text(TEXT, encoding="utf-8")
    rep = file_ingest.ingest(store, str(f))

    assert rep["status"] == "ok" and rep["chunks"] >= 1
    rows = _rows(store, str(f.resolve()))
    assert len(rows) == rep["chunks"]
    for _id, _content, emb, i8, fp, _folded, zone, tool in rows:
        assert emb is None, "REQ-9 AC6: file rows must not carry the float"
        assert i8 is not None and fp is not None
        assert zone == "trusted"
        assert tool == str(f.resolve())


def test_ct_f2_same_bytes_is_a_noop(store, tmp_path):
    from backend.memory import file_ingest

    f = tmp_path / "same.txt"
    f.write_text(TEXT, encoding="utf-8")
    first = file_ingest.ingest(store, str(f))
    n = len(_rows(store, str(f.resolve())))
    second = file_ingest.ingest(store, str(f))

    assert first["status"] == "ok"
    assert second["status"] == "unchanged"
    assert len(_rows(store, str(f.resolve()))) == n


def test_ct_f3_changed_bytes_fold_the_old_chunks(store, tmp_path):
    from backend.memory import file_ingest

    f = tmp_path / "changing.txt"
    f.write_text(TEXT, encoding="utf-8")
    file_ingest.ingest(store, str(f))
    old = {r[0] for r in _rows(store, str(f.resolve()))}

    f.write_text(TEXT + "\n\nA new paragraph adds a second version of the file text "
                         "with enough characters to produce its own chunk row.", encoding="utf-8")
    rep = file_ingest.ingest(store, str(f))

    assert rep["status"] == "ok" and rep["chunks"] >= 1
    rows = {r[0]: r for r in _rows(store, str(f.resolve()))}
    assert old <= set(rows), "REQ-9 AC3: the old rows survive the fold"
    for rid in old:
        assert rows[rid][5] is not None, "old chunk must be folded into the new head"
    assert rep["folded"] >= len(old)


def test_ct_f4_unextractable_file_keeps_its_node(store, tmp_path):
    from backend.memory import file_ingest

    f = tmp_path / "photo.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    before = file_ingest.COUNTERS["failed"]
    rep = file_ingest.ingest(store, str(f))

    assert rep["status"] == "failed" and rep["chunks"] == 0
    assert file_ingest.COUNTERS["failed"] == before + 1
    node = store.db.execute(
        "SELECT content_hash, file_size FROM file_nodes WHERE file_path = ?",
        (str(f.resolve()),),
    ).fetchone()
    assert node is not None and node[0] and node[1] > 0, "reference-only node must exist"
    assert _rows(store, str(f.resolve())) == []


def test_ct_f5_over_cap_is_truncated_and_says_so(store, tmp_path, monkeypatch):
    from backend.memory import file_ingest

    monkeypatch.setattr(file_ingest, "PER_FILE_CAP", 200)
    f = tmp_path / "big.log"
    f.write_text(TEXT * 5, encoding="utf-8")
    rep = file_ingest.ingest(store, str(f))

    assert rep["truncated"] is True
    assert rep["bytes"] <= 200


def test_ct_f6_fts_trigger_indexed_the_file_text(store, tmp_path):
    from backend.memory import file_ingest

    f = tmp_path / "fts.md"
    f.write_text(TEXT, encoding="utf-8")
    file_ingest.ingest(store, str(f))

    hits = store.db.execute(
        "SELECT COUNT(*) FROM context_chunks_fts WHERE context_chunks_fts MATCH 'zebraquux'"
    ).fetchone()[0]
    assert hits >= 1, "the trigger on context_chunks must index a file row"


def test_ct_f7_budget_read_reports_live_text(store, tmp_path):
    from backend.memory import file_ingest

    f = tmp_path / "budget.txt"
    f.write_text(TEXT, encoding="utf-8")
    file_ingest.ingest(store, str(f))

    rep = file_ingest.report(store.db)
    assert rep["text_bytes"] >= len(TEXT)
    assert rep["chunks_live"] >= 1
    assert rep["budget_bytes"] == file_ingest.TOTAL_BUDGET
