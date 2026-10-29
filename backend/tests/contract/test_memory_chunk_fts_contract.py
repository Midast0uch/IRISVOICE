"""REQ-3 contract: exact words are a first-class recall path.

Wave 3 of specs/memory-recall-reach. Measured 2026-10-27: the store had no FTS
object at all, so a path, an error string or a name was found only when the
embedding happened to place it near the query. These tests drive the real index,
the real triggers and the real ``retrieve_context_chunks`` wiring.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from backend.memory import chunk_fts
from backend.memory.embedding import BACKEND_LFM, Embedding

DIM = 1024


def _db(tmp_path, name="fts.db"):
    con = sqlite3.connect(str(tmp_path / name))
    con.execute(
        "CREATE TABLE context_chunks ("
        "id TEXT PRIMARY KEY, session_id TEXT, chunk_type TEXT, zone TEXT, "
        "content TEXT NOT NULL, embedding BLOB, embedding_backend TEXT, timestamp TEXT)"
    )
    con.commit()
    return con


def _insert(con, rid_id, content, *, session="s1", ctype="context_fragment", zone="trusted"):
    con.execute(
        "INSERT INTO context_chunks "
        "(id, session_id, chunk_type, zone, content, embedding, embedding_backend, timestamp) "
        "VALUES (?,?,?,?,?,NULL,?,?)",
        (rid_id, session, ctype, zone, content, BACKEND_LFM, "2026-10-27 10:00:00"),
    )
    con.commit()


def test_index_and_triggers_keep_the_index_in_step(tmp_path):
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con) is True
    _insert(con, "a", "the frobnicator plugin crashes")
    assert chunk_fts.search(con, "frobnicator") == [con.execute(
        "SELECT rowid FROM context_chunks WHERE id='a'").fetchone()[0]]

    # an UPDATE of content re-indexes (old term must stop matching)
    con.execute("UPDATE context_chunks SET content='the wobble widget works' WHERE id='a'")
    con.commit()
    assert chunk_fts.search(con, "frobnicator") == []
    assert chunk_fts.search(con, "wobble")

    # a DELETE removes its FTS row in the same write
    con.execute("DELETE FROM context_chunks WHERE id='a'")
    con.commit()
    assert chunk_fts.search(con, "wobble") == []
    assert chunk_fts.counts(con) == (0, 0)
    con.close()


def test_keyword_ranking_honours_the_recall_filter(tmp_path):
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con)
    _insert(con, "mine", "session one talks about kestrel", session="s1")
    _insert(con, "other", "session two talks about kestrel", session="s2")
    _insert(con, "typed", "a kestrel in the research zone", session="s1", ctype="research_summary", zone="reference")
    con.commit()

    got = chunk_fts.search(con, "kestrel", session_id="s1")
    ids = {con.execute("SELECT id FROM context_chunks WHERE rowid=?", (r,)).fetchone()[0] for r in got}
    assert ids == {"mine", "typed"}

    got = chunk_fts.search(con, "kestrel", session_id="s1", chunk_types=["research_summary"])
    assert len(got) == 1
    got = chunk_fts.search(con, "kestrel", zones=["reference"])
    assert len(got) == 1
    con.close()


def test_a_missing_index_is_counted_and_recall_continues(tmp_path):
    con = _db(tmp_path)                      # no ensure_schema on purpose
    before = dict(chunk_fts.COUNTERS)
    assert chunk_fts.search(con, "kestrel") == []
    assert chunk_fts.COUNTERS["missing"] == before["missing"] + 1
    con.close()


def test_fusion_is_by_rank_and_keeps_either_list(tmp_path):
    fused = chunk_fts.fuse_by_rank([1, 2, 3], [9, 3])
    assert set(fused) == {1, 2, 3, 9}          # the union, not the intersection
    assert fused[0] in (1, 3, 9)               # rank 1 in either list ranks high
    assert chunk_fts.fuse_by_rank([1, 2], []) == [1, 2]
    assert chunk_fts.fuse_by_rank([], [7]) == [7]


@pytest.fixture()
def kwstore(tmp_path):
    """600 chunks + one exact-word row the fingerprint can never offer.

    The zebra row's vector is the OPPOSITE of the query (Hamming 1024, the
    maximum) and its timestamp is the oldest, so neither the 200 nearest nor
    the newest 50 can contain it. Only the word index can.
    """
    from backend.memory.episodic import EpisodicStore

    path = str(tmp_path / "memory.db")
    st = EpisodicStore(db_path=path, biometric_key=b"\0" * 32)
    rng = np.random.default_rng(7)
    q = np.zeros(DIM, dtype="<f4")
    q[0] = 1.0
    con = sqlite3.connect(path)
    for i in range(600):
        v = rng.standard_normal(DIM).astype("<f4")
        v /= np.linalg.norm(v)
        con.execute(
            "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
            "embedding, embedding_backend, timestamp) VALUES (?,?,?,?,?,?,?,?)",
            (f"n{i}", "sess-k", "context_fragment", "trusted", f"noise row {i}",
             v.tobytes(), BACKEND_LFM, "2026-10-10 00:00:00"),
        )
    con.execute(
        "INSERT INTO context_chunks (id, session_id, chunk_type, zone, content, "
        "embedding, embedding_backend, timestamp) VALUES (?,?,?,?,?,?,?,?)",
        ("zebra", "sess-k", "context_fragment", "trusted", "zebra protocol alpha",
         (-q).tobytes(), BACKEND_LFM, "2020-01-01 00:00:00"),
    )
    con.commit()
    class _Stub:
        """A fixed query vector. Replace the STORE's service, not the singleton's
        method: EmbeddingService is a process-wide singleton, so patching
        ``st._embed.encode_with_meta`` leaked a canned vector into every later
        test in the same process (found 2026-10-27: the honest-label contract
        tests saw a model label on a call that never reached a model)."""

        @staticmethod
        def encode_with_meta(text):
            return Embedding(vector=q.tolist(), backend=BACKEND_LFM, chunk_count=1, truncated=False)

    st._embed = _Stub()
    yield st, con
    con.close()
    from backend.memory import recall_reach

    recall_reach._INDEXES.pop(path, None)


def test_exact_words_reach_a_row_the_fingerprint_cannot(kwstore):
    st, con = kwstore
    query = "zebra protocol alpha"

    # 1. Meaning only: the row cannot be a candidate (opposite fingerprint,
    #    oldest timestamp) - the dead end this requirement removes.
    con.execute("INSERT INTO context_chunks_fts(context_chunks_fts) VALUES('delete-all')")
    con.commit()
    without = st.retrieve_context_chunks(
            query, session_id="sess-k", limit=10, min_similarity=-1.1
    )
    assert "zebra protocol alpha" not in without

    # 2. With the index: the exact words bring it into the scored set.
    con.execute("INSERT INTO context_chunks_fts(context_chunks_fts) VALUES('rebuild')")
    con.commit()
    with_words = st.retrieve_context_chunks(
            query, session_id="sess-k", limit=10, min_similarity=-1.1
    )
    assert "zebra protocol alpha" in with_words


# ── FETCH POLICY (2026-10-28) ────────────────────────────────────────────────
# Measured on the live store: bm25 cannot rank the chunk that carries a term
# ONCE above the thousands that carry it many times, and per-term budgets made
# it worse (0.475 -> 0.400/0.500). The fix is what gets FETCHED: a literal is
# matched as a phrase, which cuts the carrier set from "py" (31,000) to
# "main.py" (2,494) and runs 10x faster.

def test_plan_treats_a_path_or_flag_as_one_literal():
    phrases, atoms = chunk_fts._plan("what does main.py do")
    assert phrases == ['"main py"']              # phrase, not "main" OR "py"
    # the broad pass keeps only CONTENT atoms: "what/does/do" are function words
    assert atoms == ["main", "py"]

    # a plain word ending in a full stop leaves ONE atom: not a literal
    assert chunk_fts._plan("model.") == ([], ["model"])
    # a flag keeps its underscore: the index tokenizer splits it into a phrase,
    # and the trailing "=0" is a token of its own, so the phrase carries it
    assert chunk_fts._plan("IRIS_TURN_START_RECALL=0")[0] == [
        '"iris_turn_start_recall 0"']
    # punctuation with no word run is not a literal and yields no atoms
    assert chunk_fts._plan("!!! ---") == ([], [])


def test_unicode_terms_keep_their_letters(tmp_path):
    """The old ASCII pattern cut "café" to "caf" and "naïve" to "na"+"ve"."""
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con)
    _insert(con, "fr", "le café est ouvert aujourd'hui")

    assert chunk_fts._terms("café naïve") == ["café", "naïve"]
    assert chunk_fts.search(con, "café")
    # the fragment the old splitter produced was a dead term - it must stay dead
    assert chunk_fts.search(con, "caf") == []
    con.close()


def test_a_literal_fills_the_budget_before_a_common_word(tmp_path):
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con)
    for i in range(60):
        _insert(con, f"py{i}", f"python helper number {i} for py work")
    for i in range(3):
        _insert(con, f"main{i}", f"entry point of main.py, branch {i}")

    main_rows = {con.execute("SELECT rowid FROM context_chunks WHERE id=?", (f"main{i}",)).fetchone()[0]
                 for i in range(3)}
    before = chunk_fts.COUNTERS.get("literal_queries", 0)
    got = chunk_fts.search(con, "main.py", limit=50)
    assert set(got[:3]) == main_rows            # the literal leads the budget
    assert len(got) == 50                       # the plain word tops it up
    assert chunk_fts.COUNTERS.get("literal_queries", 0) == before + 1
    con.close()


def test_a_literal_memory_never_saw_still_recalls_by_its_words(tmp_path):
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con)
    _insert(con, "a", "the importer reads main once")

    got = chunk_fts.search(con, "main.py")
    assert got == [con.execute("SELECT rowid FROM context_chunks WHERE id='a'").fetchone()[0]]
    con.close()


def test_stopwords_never_lead_the_broad_pass():
    """'the' is in 86% of the store: it must not be a query term (measured
    179 -> 6.7 ms on a prose query when it went)."""
    assert chunk_fts._plan("what did we learn about the vector compression")[1] == [
        "learn", "vector", "compression"]
    # a query made ONLY of function words keeps them: no silent empty recall
    assert chunk_fts._plan("what is it")[1] == ["what", "is", "it"]


def test_a_literal_keeps_every_atom_of_its_span(tmp_path):
    """A stopword inside a literal must not be dropped from its PHRASE."""
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con)
    phrases, _ = chunk_fts._plan("to.do list")
    assert phrases == ['"to do"']
    _insert(con, "a", "open the to.do list now")
    assert chunk_fts.search(con, "to.do list")
    con.close()


def test_operator_words_stay_terms(tmp_path):
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con)
    _insert(con, "or", "alpha or beta")
    _insert(con, "gamma", "gamma delta")

    got = chunk_fts.search(con, "OR")
    assert got == [con.execute("SELECT rowid FROM context_chunks WHERE id='or'").fetchone()[0]]
    con.close()


@pytest.mark.parametrize("query", [
    '"', "*", "NEAR(a b)", "OR", "AND NOT", "^main", "foo:bar", "col:value",
    "'; DROP TABLE context_chunks;--", "\x00bad", "a" * 10_000,
    " ".join(["term"] * 100), "", "   ", "!!!", "café naïve", "日本語のテキスト",
    "main.py" * 500,
])
def test_adversarial_queries_return_a_list_and_never_raise(tmp_path, query):
    """Quotes, operators, injection, nulls, 10k length: none may reach the parser."""
    con = _db(tmp_path)
    assert chunk_fts.ensure_schema(con)
    _insert(con, "a", "a safe row")

    errors = chunk_fts.COUNTERS["error"]
    got = chunk_fts.search(con, query)
    assert isinstance(got, list)
    assert chunk_fts.COUNTERS["error"] == errors        # nothing had to be caught
    assert con.execute("SELECT count(*) FROM context_chunks").fetchone()[0] == 1
    con.close()

