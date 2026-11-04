"""Contract: recall can filter on TIME and SOURCE (the two arguments it lacked).

CLM needs "what did we decide last week" (time) and "recall from this file"
(source). Both are mask conditions over columns the store already had.

NOTE for the next author: the rows MUST carry vectors. A row with no vec_i8 and
no float embedding is treated as unscorable and skipped silently, which looks
exactly like "the filter matched nothing" (found 2026-10-28: three attempts died
on fixtures without vectors).
"""
import numpy as np
import pytest

BACKEND = "lfm25-emb-350m"
RECENT = "2026-10-27 12:00:00"
OLD = "2026-01-05 09:00:00"


def _vec(text):
    v = np.zeros(1024, dtype=np.float32)
    for i, ch in enumerate(text[:64]):
        v[i % 1024] += (ord(ch) % 89) / 89.0
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).tolist()


@pytest.fixture()
def store(tmp_path):
    from backend.memory import memory_events, vector_quant
    from backend.memory.embedding import Embedding
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "m.db"), biometric_key=b"\0" * 32)
    memory_events.ensure_schema(st.db)

    class _Stub:
        @staticmethod
        def encode_with_meta(text):
            return Embedding(vector=_vec(text), backend=BACKEND,
                             chunk_count=1, truncated=False)

    st._embed = _Stub()
    for cid, text, ts, tool in (
        ("r-old", "old zebra note from january about the quokka", OLD, None),
        ("r-new", "recent quokka note from last week about leases", RECENT, None),
        ("r-file", "the lease document says hold one lease only", RECENT, "lease.md"),
    ):
        fp, i8, scale = vector_quant.compress(_vec(text))
        st.db.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content,"
            " embedding_backend, retrieval_count, timestamp, tool_name, vec_i8,"
            " vec_fp, vec_scale) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, "s", "context_fragment", "trusted", text, BACKEND, 0, ts, tool,
             i8, fp, scale))
    st.db.commit()
    yield st


def test_unbounded_sees_every_row(store):
    hits = store.retrieve_context_chunks(
        query="zebra quokka lease", session_id="s", limit=10, min_similarity=-1.0)
    assert len(hits) == 3, "the fixture must be scorable before any bound is tested"


def test_since_excludes_old_rows(store):
    hits = store.retrieve_context_chunks(
        query="zebra quokka lease", session_id="s", limit=10,
        min_similarity=-1.0, since=RECENT)
    assert len(hits) == 2
    assert not any("january" in h for h in hits)


def test_until_excludes_recent_rows(store):
    hits = store.retrieve_context_chunks(
        query="zebra quokka lease", session_id="s", limit=10,
        min_similarity=-1.0, until=OLD)
    assert len(hits) == 1 and "january" in hits[0]


def test_tool_name_scopes_to_one_source(store):
    hits = store.retrieve_context_chunks(
        query="zebra quokka lease", session_id="s", limit=10,
        min_similarity=-1.0, tool_name="lease.md")
    assert len(hits) == 1 and "lease document" in hits[0]


def test_epoch_seconds_are_accepted(store):
    import datetime as dt

    hits = store.retrieve_context_chunks(
        query="zebra quokka lease", session_id="s", limit=10,
        min_similarity=-1.0, since=dt.datetime(2026, 6, 1).timestamp())
    assert len(hits) == 2
    assert not any("january" in h for h in hits)

# ── WAVE 10 (2026-10-29): bounded filters must reach beyond the global top-M ──
# REQ-1 AC7 / T39. The old code filtered since/until/tool_name in PYTHON after
# fetching the unfiltered global top-1000 fingerprint candidates, and logged a
# WARNING per rejected row (up to 1,000 lines per query). A selective bound
# therefore lost every row outside the global top-M, and the log was flooded.
# These tests fail on the old code: the target is OLDER than the newest 50 of
# its own bound, and its vector is far from the query, so only a bound applied
# in SQL can find it.

def _wait_index(st, timeout=30.0):
    """Wait for the fingerprint index, so the REACH path runs (not the newest-200
    fallback). The fallback would hide a bound bug: it already applies where_sql."""
    import time as _time
    from backend.memory import recall_reach

    idx = recall_reach.index_for(st.db_path, lambda: st.db)
    t0 = _time.time()
    while not idx._ready and _time.time() - t0 < timeout:
        _time.sleep(0.05)
    assert idx._ready, "fingerprints never warmed"
    return idx


def _w10_store(tmp_path):
    """1,200 rows near the query (no source) + 61 bound rows far from it.

    The bound rows are the OLDEST in the store, so the newest-50 floor of the
    bounded filter cannot see the oldest 11 - the target is one of them.
    """
    import numpy as _np
    from backend.memory import vector_quant
    from backend.memory.embedding import Embedding
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "w10.db"), biometric_key=b"\0" * 32)
    q = _np.zeros(1024, dtype=_np.float32)
    q[0] = 1.0
    # orthogonal to q -> cosine 0, worst fingerprint, never in the global top-M
    far = _np.zeros(1024, dtype=_np.float32)
    far[1] = 1.0

    class _Stub:
        @staticmethod
        def encode_with_meta(text):
            return Embedding(vector=q.tolist(), backend=BACKEND,
                             chunk_count=1, truncated=False)

    st._embed = _Stub()
    rng = _np.random.default_rng(11)

    def _add(cid, content, ts, tool, vec):
        fp, i8, scale = vector_quant.compress(vec)
        st.db.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content,"
            " embedding_backend, retrieval_count, timestamp, tool_name, vec_i8,"
            " vec_fp, vec_scale) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, "s", "context_fragment", "trusted", content, BACKEND, 0, ts, tool,
             i8, fp, scale))

    for i in range(1200):
        v = q + 0.01 * rng.standard_normal(1024).astype(_np.float32)
        _add(f"noise{i}", f"noise row {i}", "2026-10-27 12:00:00", None, v)
    for i in range(61):
        _add(f"bound{i}", f"lease clause {i}", f"2026-01-{1 + i % 28:02d} 0{i % 9}:00:00",
             "lease.md", far)
    # the target: the OLDEST bound row (not in the newest 50 of the bound)
    _add("target", "the lease document says hold one lease only",
         "2025-12-31 00:00:00", "lease.md", far)
    st.db.commit()
    _wait_index(st)
    return st


def test_bounded_source_reaches_beyond_the_global_top_m(tmp_path, caplog):
    import logging as _logging
    st = _w10_store(tmp_path)
    with caplog.at_level(_logging.WARNING, logger="backend.memory.episodic"):
        hits = st.retrieve_context_chunks(
            query="lease clause", limit=100, min_similarity=-1.1,
            tool_name="lease.md")
    assert "the lease document says hold one lease only" in hits, (
        "a selective tool_name must reach its own rows beyond the global top-M")
    assert len(hits) == 62
    assert not any("row skipped by bounds" in r.getMessage() for r in caplog.records), (
        "bounds are applied in SQL; the per-row warning must be gone")


def test_bounded_time_window_reaches_beyond_the_global_top_m(tmp_path, caplog):
    import logging as _logging
    st = _w10_store(tmp_path)
    with caplog.at_level(_logging.WARNING, logger="backend.memory.episodic"):
        hits = st.retrieve_context_chunks(
            query="lease clause", limit=100, min_similarity=-1.1,
            until="2026-01-31 00:00:00")
    assert "the lease document says hold one lease only" in hits, (
        "a time window must reach its own rows beyond the global top-M")
    assert not any("row skipped by bounds" in r.getMessage() for r in caplog.records)


# ── WAVE 10 (2026-10-29): two-phase vectorized rescore ───────────────────────
# REQ-12 AC6 / T40. The delivered ranking must be IDENTICAL to the old
# per-row cosine, while `content` is read only for the winning rows.

def test_two_phase_rescore_keeps_the_exact_ranking(tmp_path):
    import datetime as _dt
    import math as _math
    import numpy as _np
    from backend.memory import vector_quant
    from backend.memory.embedding import Embedding
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "rank.db"), biometric_key=b"\0" * 32)
    rng = _np.random.default_rng(21)
    q = rng.standard_normal(1024).astype(_np.float32)
    q /= _np.linalg.norm(q)

    class _Stub:
        @staticmethod
        def encode_with_meta(text):
            return Embedding(vector=q.tolist(), backend=BACKEND,
                             chunk_count=1, truncated=False)

    st._embed = _Stub()
    expected = {}   # id -> (cosine of the STORED form, timestamp)
    rows = []
    for i in range(200):                       # int8-only rows
        v = rng.standard_normal(1024).astype(_np.float32)
        v /= _np.linalg.norm(v)
        fp, i8, scale = vector_quant.compress(v)
        ts = f"2026-10-{1 + i % 27:02d} {i % 24:02d}:00:00"
        rows.append(("i8_%d" % i, f"int8 row {i}", ts, None, i8, fp, scale))
        # the store scores the RESTORED int8 vector, not the float it came from
        back = _np.asarray(vector_quant.decompress(i8, scale), dtype=_np.float64)
        expected["i8_%d" % i] = (float(_np.dot(back, q) / _np.linalg.norm(back)), ts)
    for i in range(50):                        # float-only rows
        v = rng.standard_normal(1024).astype(_np.float32)
        v /= _np.linalg.norm(v)
        ts = f"2026-09-{1 + i % 27:02d} {i % 24:02d}:00:00"
        rows.append(("f_%d" % i, f"float row {i}", ts, v.tobytes(), None, None, None))
        expected["f_%d" % i] = (float(_np.dot(v, q)), ts)
    for cid, text, ts, emb, i8, fp, scale in rows:
        st.db.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content,"
            " embedding, embedding_backend, retrieval_count, timestamp, vec_i8,"
            " vec_fp, vec_scale) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, "s", "context_fragment", "trusted", text, emb, BACKEND, 0, ts,
             i8, fp, scale))
    for i in range(10):                        # another embedding space: never compared
        v = rng.standard_normal(1024).astype(_np.float32)
        st.db.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content,"
            " embedding, embedding_backend, retrieval_count, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (f"other_{i}", "s", "context_fragment", "trusted", f"other space {i}",
             v.tobytes(), "bge-m3", 0, "2026-10-27 00:00:00"))
    st.db.commit()
    _wait_index(st)

    limit = 10
    sqls = []
    try:
        st.db.set_trace_callback(sqls.append)
    except Exception:
        pass

    hits = st.retrieve_context_chunks(query="anything", limit=limit,
                                      min_similarity=-1.1)

    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    ranked = []
    for cid, (cos, ts) in expected.items():
        t = _dt.datetime.fromisoformat(ts)
        age_h = max(0.0, (now - t).total_seconds() / 3600.0)
        recency = 1.0 / (1.0 + age_h / 168.0)
        ranked.append((_math.floor(cos / 0.0005) * 10.0 + recency, cid))
    ranked.sort(key=lambda x: x[0], reverse=True)
    want = [f"{'int8' if c.startswith('i8_') else 'float'} row {c.split('_')[1]}"
            for _s, c in ranked[:limit]]

    assert hits == want, "the vectorized rescore must deliver the exact ranking"
    assert not any(h.startswith("other space") for h in hits), (
        "vectors of another embedding backend are never compared")

    # T40's structural half: `content` is selected for the winning rows only.
    content_reads = [s for s in sqls
                     if "content" in s.lower() and "from context_chunks" in s.lower()]
    assert content_reads, "Phase 2 must fetch content"
    for sql in content_reads:
        assert sql.count("?") <= limit, (
            "content must be fetched for <= limit rows, not every candidate")

# ── WAVE 10: the recall_memory tool returns all three memory layers (T45) ──
# REQ-13 AC1 / CT-W10-7. Before T45 the tool called retrieve_similar ONLY, so a
# chunk or chain fact answered "nothing found" and the since/until/tool_name
# filters had no production caller.
def test_recall_memory_tool_returns_chunks_chain_and_episodes(tmp_path, monkeypatch):
    import sqlite3

    from backend.agent import ontology_recall, tool_bridge

    monkeypatch.setattr(ontology_recall, "TURN_START_RECALL", True)

    con = sqlite3.connect(str(tmp_path / "memory.db"))
    con.execute(
        "CREATE TABLE memory_chain ("
        "entry_id TEXT, thread_id TEXT, session_id TEXT, sequence INTEGER, role TEXT, "
        "content TEXT, metadata TEXT, result TEXT, distilled INTEGER DEFAULT 0, "
        "created_at REAL, chain_id TEXT, insight TEXT, topic_domain TEXT, "
        "node_type TEXT, coords_from TEXT)")
    con.execute(
        "INSERT INTO memory_chain (thread_id, insight, result, created_at) VALUES "
        "('seed-thread', 'Store the fact that the staging deployment is named "
        "kestrel-blue for later recall.', 'success', 1000.0)")
    con.commit()

    seen = {}

    class _Episodic:
        db = con

        def retrieve_context_chunks(self, query, **kw):
            seen["chunks"] = dict(query=query, **kw)
            return ["chunk one"]

        def retrieve_similar(self, **kw):
            seen["episodes"] = dict(kw)
            return [{"task": "earlier task"}]

    out = tool_bridge._recall_memory_payload(
        _Episodic(), "What is the name of my staging deployment?",
        since="2026-10-01", until="2026-10-30", tool_name="lease.md", limit=4)

    assert out["success"] is True
    assert out["chunks"] == ["chunk one"]
    assert out["episodes"] == [{"task": "earlier task"}]
    assert out["results"] is out["episodes"], "results must stay the episodes list"
    assert out["chain"] and "kestrel-blue" in str(out["chain"]), (
        "the chain layer (taught facts) must be in the tool result")
    assert seen["chunks"]["since"] == "2026-10-01"
    assert seen["chunks"]["until"] == "2026-10-30"
    assert seen["chunks"]["tool_name"] == "lease.md"
    assert seen["chunks"]["session_id"] is None
    assert seen["chunks"]["limit"] == 4
    con.close()


def test_recall_memory_tool_survives_a_broken_chain_leg():
    """One broken layer must not turn the whole tool call into an error."""
    from backend.agent import tool_bridge

    class _Broken:
        db = object()

        def retrieve_context_chunks(self, query, **kw):
            return []

        def retrieve_similar(self, **kw):
            return []

    out = tool_bridge._recall_memory_payload(_Broken(), "anything")
    # `pins` joined the payload after this test was written (recall_memory
    # reads the pin index; see test_recall_memory_pins_contract.py). The
    # assertion stays EXACT so another key cannot appear unnoticed.
    assert out == {"success": True, "chunks": [], "chain": [],
                   "episodes": [], "pins": [], "results": []}
