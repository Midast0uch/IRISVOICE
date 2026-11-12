"""CT (specs/clm-memory T1.2, CLM-1 AC2): every direct-path block carries a Ref.

Pins:
(a) ``retrieve_context_chunks(with_meta=True)`` returns the row id (``"id"``)
    beside the five keys it always had, and that id is ``context_chunks.id``;
    the default (text-only) return is unchanged.
(b) ``_assemble_direct_context`` admits each block with the ref kind the design
    names: ``ephemeral`` for system_prompt and current_user; ``chunk`` ids for
    the cross-session recalled chunks and ``chain`` ids for the turn-start
    prior memory, in section order, on the ONE merged recall block; a block
    whose source row is not identifiable today stays ephemeral and says why
    (``ref_reason``). No id is invented and nothing is looked up by text.
(c) refs live on blocks only: no message dict gains a key, and no id appears
    in the rendered text.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.agent import context_view as cv
from backend.agent.kernel import context as kctx
from backend.memory.embedding import BACKEND_LFM, Embedding


class _Stub:
    @staticmethod
    def encode_with_meta(text):
        v = np.zeros(1024, dtype=np.float32)
        for i, ch in enumerate(text[:200]):
            v[(ord(ch) + i) % 1024] += 1.0
        v /= np.linalg.norm(v)
        return Embedding(vector=v.tolist(), backend=BACKEND_LFM, chunk_count=1, truncated=False)


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "refs.db"), biometric_key=b"\0" * 32)
    st._embed = _Stub()
    return st


def test_with_meta_rows_carry_the_context_chunks_row_id(store):
    store.fragment_and_store("my favourite fruit is the quince", session_id="s",
                             chunk_type="context_fragment")
    store.fragment_and_store("the garage code is nine four four one", session_id="s",
                             chunk_type="context_fragment")
    rows = store.retrieve_context_chunks(
        "favourite fruit", session_id="s", limit=5, min_similarity=0.0, with_meta=True)
    assert rows, "the temp store must return rows for this query"
    stored = {r[0] for r in store.db.execute("SELECT id FROM context_chunks").fetchall()}
    for row in rows:
        assert set(row) == {"content", "chunk_type", "producer", "score", "timestamp", "id"}
        assert row["id"] in stored
        got = store.db.execute(
            "SELECT content FROM context_chunks WHERE id=?", (row["id"],)).fetchone()[0]
        assert got == row["content"]


def test_default_return_is_still_plain_text(store):
    store.fragment_and_store("my favourite fruit is the quince", session_id="s")
    rows = store.retrieve_context_chunks("favourite fruit", session_id="s", min_similarity=0.0)
    assert rows and all(isinstance(r, str) for r in rows)


# -- the direct path ------------------------------------------------------

class _Episodic:
    def __init__(self, xrows, chunks=()):
        self.xrows, self.chunks = xrows, list(chunks)
        self.db = None

    def assemble_episodic_context(self, text):
        return "past success: did X"

    def retrieve_context_chunks(self, **kw):
        if kw.get("with_meta"):
            return self.xrows
        if kw.get("zones") == ["reference"] or kw.get("chunk_types") == ["file"]:
            return []
        return self.chunks


class _MI:
    def __init__(self, ep):
        self.episodic = ep


@pytest.fixture()
def run(monkeypatch):
    seen = {}

    class Spy(cv.ContextView):
        def __init__(self):
            super().__init__()
            seen["view"] = self

    monkeypatch.setattr(kctx, "_ContextView", Spy)

    def go(xrows, pm_rows=(), chunks=()):
        import backend.agent.ontology_recall as orc

        monkeypatch.setattr(orc, "turn_start_prior_memory", lambda *a, **k: list(pm_rows))
        monkeypatch.setattr(orc, "resolve_mycelium_conn", lambda *a, **k: None)

        class K(kctx.ContextMixin):
            _CHARS_PER_TOKEN = 4
            _DIRECT_CTX_BUDGET = 24_000
            conversation_id = "c"
            session_id = "s"
            _mcm_orch = None

            def _build_system_prompt(self):
                return "You are IRIS."

            def _mycelium_profile_messages(self, text, sid):
                return [{"role": "user", "content": "<mycelium_profile>tea</mycelium_profile>"},
                        {"role": "assistant", "content": "Understood — I have that profile."}]

            def resolve_context_window(self, role="reasoning"):
                return 32000

        k = K()
        k._memory_interface = _MI(_Episodic(xrows, chunks))
        history = [{"role": "user", "content": "hi there"}, {"role": "assistant", "content": "hello"}]
        msgs = k._assemble_direct_context("what colour do I like?", history, "s")
        return msgs, {b.kind: b for b in seen["view"].blocks}

    return go


def test_each_block_carries_the_ref_the_design_names(run):
    xrows = [{"content": "the user said the sky colour is cerulean", "timestamp": "2026-11-01", "id": "chunk-aaa"},
             {"content": "the garage code is nine four four one", "timestamp": "2026-10-01", "id": "chunk-bbb"}]
    pm = [{"chain_id": "chain-111", "insight": "my preferred tea is sencha"}]
    msgs, blocks = run(xrows, pm_rows=pm, chunks=["a recalled fragment about gardens"])

    assert blocks[cv.SYSTEM_PROMPT].ref == cv.EPHEMERAL and blocks[cv.SYSTEM_PROMPT].ref_reason
    assert blocks[cv.CURRENT_USER].ref == cv.EPHEMERAL and blocks[cv.CURRENT_USER].ref_reason
    rc = blocks[cv.RECALL_CHUNKS]
    # prior_memory (chain) first, then cross-session chunks, in section order
    assert rc.refs == (cv.Ref("chain", "chain-111"), cv.Ref("chunk", "chunk-aaa"), cv.Ref("chunk", "chunk-bbb"))
    assert rc.ref == rc.refs[0]
    # the legs that arrive as text only are named, not invented
    assert "chunks (retrieve_context_chunks returns text" in rc.ref_reason
    for kind in (cv.RECALL_EPISODIC, cv.RECALL_PROFILE, cv.HISTORY):
        assert blocks[kind].ref == cv.EPHEMERAL and blocks[kind].refs == ()
        assert blocks[kind].ref_reason, f"{kind} must say why it has no row"
    # the merged recall message is ONE message pair, not split per chunk
    assert sum(1 for m in msgs if "<context_memory>" in (m.get("content") or "")) == 1


def test_a_cross_session_row_without_an_id_is_named_not_invented(run):
    xrows = [{"content": "the user said the sky colour is cerulean", "timestamp": "2026-11-01"}]
    _, blocks = run(xrows)
    rc = blocks[cv.RECALL_CHUNKS]
    assert rc.refs == () and rc.ref == cv.EPHEMERAL
    assert "cross_session chunk without id" in rc.ref_reason


def test_refs_never_reach_the_rendered_messages(run):
    xrows = [{"content": "the user said the sky colour is cerulean", "timestamp": "2026-11-01", "id": "chunk-aaa"}]
    msgs, blocks = run(xrows, pm_rows=[{"chain_id": "chain-111", "insight": "my preferred tea is sencha"}])
    assert blocks[cv.RECALL_CHUNKS].refs
    for m in msgs:
        assert set(m) <= {"role", "content"}
        assert "chunk-aaa" not in m["content"] and "chain-111" not in m["content"]


# -- ids_out (T1.2 follow-up): every row that comes from a table row carries its id ----

def _seed(store):
    for t in ("my favourite fruit is the quince", "the garage code is nine four four one",
              "the ferry leaves at dawn from pier six", "my cat is called Tobias"):
        store.fragment_and_store(t, session_id="s", chunk_type="context_fragment")


def _counts(store):
    return dict(store.db.execute("SELECT content, retrieval_count FROM context_chunks").fetchall())


def _call(store, **kw):
    return store.retrieve_context_chunks(
        query="favourite fruit garage ferry cat", session_id="s", limit=3, min_similarity=0.0, **kw)


def test_ids_out_matches_the_returned_order_in_both_shapes(store):
    _seed(store)
    ids: list = []
    plain = _call(store, ids_out=ids)
    assert plain and len(ids) == len(plain)
    for text, cid in zip(plain, ids):
        assert store.db.execute("SELECT content FROM context_chunks WHERE id=?", (cid,)).fetchone()[0] == text
    ids_m: list = ["stale"]  # a non-empty list is replaced, not appended to
    meta = _call(store, with_meta=True, ids_out=ids_m)
    assert [r["content"] for r in meta] == plain
    assert ids_m == ids == [r["id"] for r in meta]


def test_the_default_path_is_unchanged_by_ids_out(store):
    _seed(store)
    base = _call(store)
    after_one = _counts(store)
    with_ids = _call(store, ids_out=[])
    assert with_ids == base                      # same return, same order
    after_two = _counts(store)
    # the plain path updates retrieval_count for the same rows with or without ids_out
    bumped_default = {k for k in after_one if after_one[k] == 1}
    bumped_with_ids = {k for k in after_two if after_two[k] == 2}
    assert bumped_default == bumped_with_ids == set(base)
    meta_before = _counts(store)
    _call(store, with_meta=True, ids_out=[])
    assert _counts(store) == meta_before         # with_meta still skips the update


def test_ids_out_is_empty_when_nothing_is_returned(store):
    ids = ["x"]
    assert store.retrieve_context_chunks(query="", ids_out=ids) == [] and ids == []
    assert store.retrieve_context_chunks(query="anything", session_id="none-such", ids_out=ids) == [] and ids == []


def test_the_reindex_branch_hands_ids_out_on_and_only_when_asked(store, monkeypatch):
    import backend.memory.episodic as epmod

    calls = []

    class _RM:
        def progress(self):
            return {"state": "running"}

        def search_chunks(self, **kw):
            calls.append(set(kw))
            if "ids_out" in kw:
                kw["ids_out"].extend(["r1", "r2"])
            return ["a", "b"]

    monkeypatch.setattr(epmod, "get_reindex_manager", lambda: _RM())
    ids: list = []
    assert store.retrieve_context_chunks(query="q", ids_out=ids) == ["a", "b"] and ids == ["r1", "r2"]
    assert store.retrieve_context_chunks(query="q") == ["a", "b"]
    assert "ids_out" in calls[0] and "ids_out" not in calls[1]


def _chain_db(with_chain_id=True):
    import sqlite3
    db = sqlite3.connect(":memory:")
    cols = "entry_id INTEGER PRIMARY KEY, insight TEXT, content TEXT, node_type TEXT, stale INTEGER DEFAULT 0"
    db.execute(f"CREATE TABLE memory_chain ({cols}{', chain_id TEXT' if with_chain_id else ''})")
    return db


def test_recent_user_turn_ids_are_parallel_and_the_return_is_unchanged():
    db = _chain_db()
    for i, (txt, nt) in enumerate([("my card is alpha", "user_turn"), ("an answer", "response"),
                                   ("my card is bravo", "user_turn"), ("What is my card?", "user_turn")]):
        db.execute("INSERT INTO memory_chain (insight, content, node_type, chain_id) VALUES (?,?,?,?)",
                   (txt, "", nt, f"chain-{i}"))
    ids: list = []
    with_ids = kctx._recent_user_turn_texts(db, "What is my card?", ids_out=ids)
    assert with_ids == kctx._recent_user_turn_texts(db, "What is my card?")
    assert with_ids == ["my card is bravo", "my card is alpha"] and ids == ["chain-2", "chain-0"]


def test_recent_user_turn_ids_fall_back_when_the_table_has_no_chain_id():
    db = _chain_db(with_chain_id=False)
    db.execute("INSERT INTO memory_chain (insight, content, node_type) VALUES ('my spot is A1','','user_turn')")
    ids: list = ["x"]
    assert kctx._recent_user_turn_texts(db, "", ids_out=ids) == ["my spot is A1"] and ids == []


def test_the_direct_path_addresses_every_leg_that_has_a_row(monkeypatch):
    import backend.agent.ontology_recall as orc
    import sqlite3

    class Ep(_Episodic):
        def retrieve_context_chunks(self, **kw):
            out = super().retrieve_context_chunks(**kw)
            if "ids_out" in kw and not kw.get("with_meta"):
                kw["ids_out"].extend(f"id-{i}" for i in range(len(out)))
                if kw.get("zones") == ["reference"]:
                    kw["ids_out"][:] = [f"ref-{i}" for i in range(len(out))]
            return out

    db = _chain_db()
    db.execute("INSERT INTO memory_chain (insight, content, node_type, chain_id) VALUES ('my parking spot is B7','','user_turn','chain-rf')")
    seen = {}

    class Spy(cv.ContextView):
        def __init__(self):
            super().__init__()
            seen["v"] = self

    monkeypatch.setattr(kctx, "_ContextView", Spy)
    monkeypatch.setattr(orc, "turn_start_prior_memory", lambda *a, **k: [{"chain_id": "chain-pm", "insight": "my tea is sencha"}])
    monkeypatch.setattr(orc, "resolve_mycelium_conn", lambda *a, **k: None)

    class K(kctx.ContextMixin):
        _CHARS_PER_TOKEN = 4
        _DIRECT_CTX_BUDGET = 24_000
        conversation_id = "c"
        session_id = "s"
        _mcm_orch = None
        def _build_system_prompt(self): return "You are IRIS."
        def _mycelium_profile_messages(self, text, sid): return []
        def resolve_context_window(self, role="reasoning"): return 32000

    ep = Ep([{"content": "the sky is cerulean", "timestamp": "2026-11-01", "id": "chunk-x"}],
            chunks=["fragment one about gardens", "fragment two about boats"])
    ep.db = db
    k = K()
    k._memory_interface = _MI(ep)
    k._assemble_direct_context("what colour do I like?", [], "s")
    rc = {b.kind: b for b in seen["v"].blocks}[cv.RECALL_CHUNKS]
    # section order: recent_facts, prior_memory, chunks, cross_session
    assert rc.refs == (cv.Ref("chain", "chain-rf"), cv.Ref("chain", "chain-pm"),
                       cv.Ref("chunk", "id-0"), cv.Ref("chunk", "id-1"), cv.Ref("chunk", "chunk-x"))
    assert rc.ref_reason == ""
