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
