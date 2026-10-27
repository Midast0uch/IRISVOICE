"""REQ-4 AC3: a proven claim's agreeing chunks distil into the claim + references.

``memory_chain.distilled`` had no writer (0 of 58,428 rows). These tests pin the
distillation contract:

* ONE chain row per proven claim: the claim's own text (proven = trust-allowed)
  plus REFERENCES to the agreeing chunks (ids, never payloads), ``distilled = 1``;
* a claim that is not proven (candidate tier) is never distilled;
* the pass is idempotent - a claim with a distilled row is skipped;
* the row is a normal chain row: chain recall finds it by thread_id.

They fail on the code before 2026-10-27 (no writer for memory_chain.distilled).
"""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pytest

from backend.memory import distil_claims, fold_chunks, vector_quant

DIM = 1024


def _unit(v):
    return (v / np.linalg.norm(v)).astype("<f4")


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    # the mycelium tables belong to the wider store schema, not EpisodicStore's;
    # create the production-shaped columns the distil pass reads and writes
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS mycelium_landmarks ("
        "landmark_id TEXT PRIMARY KEY, micro_abstract_text TEXT, label TEXT, "
        "tier TEXT DEFAULT 'candidate', evidence TEXT DEFAULT '[]', absorbed INTEGER DEFAULT 0)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS memory_chain ("
        "entry_id TEXT, thread_id TEXT, session_id TEXT, sequence INTEGER, role TEXT, "
        "content TEXT, metadata TEXT, result TEXT, distilled INTEGER DEFAULT 0, "
        "created_at REAL, chain_id TEXT, landmark_id TEXT)")
    con.commit()
    con.close()
    yield path


def _claim(con, lid, text, *, tier="landmark", absorbed=0):
    con.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, micro_abstract_text, label, tier, "
        "evidence, absorbed) VALUES (?, ?, ?, ?, '[]', ?)",
        (lid, text, lid, tier, absorbed),
    )


def _chunk(con, cid, vec, content, *, session="sess-a", ctype="context_fragment",
           zone="trusted"):
    fp, code, scale = vector_quant.compress(vec)
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "embedding, timestamp, embedding_backend, vec_fp, vec_i8, vec_scale) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (cid, session, ctype, zone, content, vec.tobytes(), "2026-10-27 12:00:00",
         "lfm25-emb-350m", fp, code, scale),
    )


def test_a_proven_claim_distils_into_one_chain_row_with_references(store):
    path = store
    rng = np.random.default_rng(61)
    claim_vec = _unit(rng.standard_normal(DIM))
    # noise is scaled per component: 1024 dims of it would swamp the signal
    # (0.05 x sqrt(1024) = 1.6 > the vector's own norm)
    agree1 = _unit(claim_vec + (0.05 / 32) * rng.standard_normal(DIM))   # cosine ~ 0.998
    agree2 = _unit(claim_vec + (0.50 / 32) * rng.standard_normal(DIM))   # cosine ~ 0.89
    other = _unit(rng.standard_normal(DIM))                              # cosine ~ 0

    con = sqlite3.connect(path)
    _claim(con, "claim-1", "the retry ladder shrinks dense chunks")
    _chunk(con, "c-agree-1", agree1, "first agreeing text")
    _chunk(con, "c-agree-2", agree2, "second agreeing text")
    _chunk(con, "c-other", other, "unrelated text")
    con.commit()

    box: dict = {}
    distil_claims.distil_pass(box, con, embed=lambda t: claim_vec.tolist())
    res = box["result"]
    assert not res.get("error")
    assert res["distilled"] == 1

    rows = con.execute(
        "SELECT content, metadata, distilled, landmark_id, thread_id, role "
        "FROM memory_chain WHERE landmark_id = 'claim-1'").fetchall()
    assert len(rows) == 1, "one chain row per claim"
    content, meta, distilled, lid, thread, role = rows[0]
    assert content == "the retry ladder shrinks dense chunks", "the claim text is the payload"
    assert distilled == 1 and lid == "claim-1"
    assert thread == "claim-claim-1", "chain recall finds it by thread_id"
    assert role == "system"
    refs = json.loads(meta)["chunk_refs"]
    assert set(refs) == {"c-agree-1", "c-agree-2"}, "references, and only the agreeing chunks"
    assert "first agreeing text" not in meta, "the chain holds references, never payloads"
    con.close()


def test_the_pass_is_idempotent_and_skips_unproven_claims(store):
    path = store
    rng = np.random.default_rng(62)
    v = _unit(rng.standard_normal(DIM))
    con = sqlite3.connect(path)
    _claim(con, "claim-proven", "proven claim text")
    _claim(con, "claim-candidate", "candidate claim text", tier="candidate")
    _claim(con, "claim-absorbed", "absorbed claim text", absorbed=1)
    _chunk(con, "c-1", v, "agreeing text")
    con.commit()

    box: dict = {}
    distil_claims.distil_pass(box, con, embed=lambda t: v.tolist())
    assert box["result"]["distilled"] == 1, "only the proven, live claim distils"
    assert con.execute("SELECT count(*) FROM memory_chain WHERE distilled = 1").fetchone()[0] == 1

    box2: dict = {}
    distil_claims.distil_pass(box2, con, after_rowid=0, embed=lambda t: v.tolist())
    assert box2["result"]["distilled"] == 0
    assert box2["result"]["skipped_done"] == 1, "a claim with a distilled row is skipped"
    assert con.execute("SELECT count(*) FROM memory_chain WHERE distilled = 1").fetchone()[0] == 1
    assert distil_claims.counts(con) == {"claims": 1}
    con.close()


def test_folded_rows_are_never_referenced(store):
    path = store
    rng = np.random.default_rng(63)
    v = _unit(rng.standard_normal(DIM))
    con = sqlite3.connect(path)
    _claim(con, "claim-1", "claim text")
    _chunk(con, "c-keep", v, "kept text")
    _chunk(con, "c-folded", v, "folded text")
    con.commit()
    fold_chunks.fold_pass({}, con, scan_groups=10)
    assert fold_chunks.counts(con)["rows"] == 1

    box: dict = {}
    distil_claims.distil_pass(box, con, embed=lambda t: v.tolist())
    meta = con.execute("SELECT metadata FROM memory_chain WHERE landmark_id = 'claim-1'").fetchone()
    refs = json.loads(meta[0])["chunk_refs"]
    assert refs == ["c-keep"], "a folded row is not a reference; its canonical is"
    con.close()
