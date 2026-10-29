"""Wave 10 contracts for the USER's own statements in memory.

CT-W10-5 (REQ-12 AC2): a short user fact is stored (10-char floor), an identical
repeat is skipped, and a re-taught CHANGED fact supersedes the older row by
folding it. Before 2026-10-29 the 50-char sliver floor dropped every name and
colour, and a near-duplicate was silently skipped, so the OLD value kept winning.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.memory.embedding import BACKEND_LFM, Embedding


class _Stub:
    """Deterministic vectors: the changed value is a near-duplicate (0.9999)."""

    @staticmethod
    def encode_with_meta(text):
        v = np.zeros(1024, dtype=np.float32)
        if "teal" in text:
            v[0] = 1.0
        elif "green" in text:
            v[1], v[2] = 1.0, 0.01
        elif "blue" in text:
            v[1], v[2] = 1.0, -0.01
        elif "kestrel" in text:
            v[3] = 1.0
        else:
            # A bag of characters, not one shared slot: two unrelated texts must
            # not look like a cosine duplicate, or the fold eats a real row.
            for i, ch in enumerate(text[:200]):
                v[(ord(ch) + i) % 1024] += 1.0
        v /= np.linalg.norm(v)
        return Embedding(vector=v.tolist(), backend=BACKEND_LFM,
                         chunk_count=1, truncated=False)


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "user.db"), biometric_key=b"\0" * 32)
    st._embed = _Stub()
    return st


def _count(st):
    return st.db.execute("SELECT COUNT(*) FROM context_chunks").fetchone()[0]


def _live(st):
    return st.db.execute(
        "SELECT COUNT(*) FROM context_chunks WHERE folded_into IS NULL"
    ).fetchone()[0]


def test_short_user_fact_is_stored(store):
    store.fragment_and_store("my colour teal", session_id="s",
                             chunk_type="context_fragment")
    assert _count(store) == 1, "a 14-char user fact must pass the 10-char floor"
    assert store.db.execute(
        "SELECT content FROM context_chunks").fetchone()[0] == "my colour teal"


def test_identical_repeat_is_not_stored_twice(store):
    store.fragment_and_store("my colour teal", session_id="s")
    store.fragment_and_store("my colour teal", session_id="s")
    assert _count(store) == 1, "an identical repeat has nothing new to remember"


def test_changed_fact_supersedes_the_older_row(store):
    store.fragment_and_store("my colour teal", session_id="s")
    store.fragment_and_store(
        "the user's favourite colour is green for status chips", session_id="s")
    store.fragment_and_store(
        "the user's favourite colour is blue for status chips", session_id="s")

    rows = store.db.execute(
        "SELECT id, content, folded_into FROM context_chunks "
        "WHERE content LIKE '%status chips%' ORDER BY timestamp").fetchall()
    assert len(rows) == 2
    old_id, old_txt, old_folded = rows[0]
    new_id, new_txt, new_folded = rows[1]
    assert "green" in old_txt and "blue" in new_txt
    assert new_folded is None, "the newest statement stays live"
    assert old_folded == new_id, "the superseded value folds into the new row"
    assert _live(store) == 2      # teal + blue; green no longer competes


def test_unrelated_fact_stays_separate(store):
    store.fragment_and_store("my colour teal", session_id="s")
    store.fragment_and_store(
        "the user's staging deployment is kestrel", session_id="s")
    assert _live(store) == 2


def test_a_fact_retaught_in_a_new_conversation_supersedes_the_old(store):
    """REQ-12 AC2 (T48): the memory eval teaches in one turn and asks in a later
    conversation. Before this, the near-duplicate window was scoped to ONE
    session, so a re-taught colour never folded the previous run's row: five
    near-identical "fern-green-XXXX" chunks competed and m03 answered "Green -
    though one tool result reported blue" instead of the newest value."""
    store.fragment_and_store(
        "User: I prefer the color fern-green-AAAA for status indicators.",
        session_id="conv-old", chunk_type="context_fragment")
    store.fragment_and_store(
        "User: I prefer the color fern-green-BBBB for status indicators.",
        session_id="conv-new", chunk_type="context_fragment")

    rows = store.db.execute(
        "SELECT id, content, folded_into FROM context_chunks "
        "ORDER BY timestamp").fetchall()
    assert len(rows) == 2
    old_id, old_txt, old_folded = rows[0]
    new_id, new_txt, new_folded = rows[1]
    assert "AAAA" in old_txt and "BBBB" in new_txt
    assert new_folded is None, "the newest statement stays live"
    assert old_folded == new_id, (
        "a fact from an earlier conversation must be superseded")
    assert _live(store) == 1, "only the newest colour competes in recall"


# ── CT-W10-4a/b (REQ-12 AC1, AC3): both paths persist the user's own words ───

def test_turn_pair_is_stored_on_the_fragment_lane(tmp_path):
    """The direct and DER completion paths both call this; a normal conversation
    turn must reach `context_chunks` (it never did: _is_fragment_candidate
    requires DER-shaped output)."""
    from types import SimpleNamespace

    from backend.agent.mcm_protocol.actions import pacman_fragment as pf
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "pair.db"), biometric_key=b"\0" * 32)
    mi = SimpleNamespace(episodic=st)

    assert pf.submit_turn_pair(
        mi, "s1", "my staging deployment is kestrel-blue", "Noted.", zone="trusted",
    ) is True
    pf._FRAGMENT_QUEUE.join()

    rows = st.db.execute(
        "SELECT content, embedding, vec_i8, chunk_type, zone FROM context_chunks"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "User: my staging deployment is kestrel-blue\nAssistant: Noted."
    assert rows[0][1] is None, "keep_float=False: the int8 code is the recall form"
    assert rows[0][2] is not None, "the compact vector must be written with the row"
    assert rows[0][3] == "context_fragment"
    assert rows[0][4] == "trusted"


def test_user_turn_entry_writes_a_role_user_chain_row(monkeypatch):
    """REQ-12 AC1: the statement is on the Immortus chain, typed user_turn,
    with the text in `content` and `insight` and `result` left empty (S12)."""
    from backend.agent.mcm_protocol.actions import pacman_fragment as pf

    rows: list = []
    monkeypatch.setattr(
        "backend.gateway.iris_ffi.ffi_immortus_chain_append",
        lambda **kw: (rows.append(kw) or 0),
    )

    assert pf.submit_user_turn_entry(object(), "s1", "my name is Ada") is True
    pf._FRAGMENT_QUEUE.join()

    assert len(rows) == 1
    row = rows[0]
    assert row["thread_id"] == "s1"
    assert row["role"] == "user"
    assert row["node_type"] == "user_turn"
    assert row["content"] == "my name is Ada"
    assert row["insight"] == "my name is Ada"
    assert row["result"] == "", "S12: the payload is stored once, not twice"
    assert row["nbl_outcome"] == "event:USER_TURN"


def test_turn_entry_and_pair_are_noops_without_memory():
    from backend.agent.mcm_protocol.actions import pacman_fragment as pf

    assert pf.submit_user_turn_entry(None, "s1", "hello there") is False
    assert pf.submit_turn_pair(None, "s1", "hello there", "hi") is False
    assert pf.submit_turn_pair(object(), "s1", "", "hi") is False


# ── CT-W10-11 (T48): fact identity, not cosine similarity ───────────────────

def test_fact_identity_table():
    """Supersede is an IDENTITY question: same statement, new value.

    Cosine cannot answer it (the live colour pair embeds at 0.8854, under the
    0.92 threshold), so the rule compares positions and accepts a difference
    only at a VALUE position - a token carrying a digit, or a token that
    directly follows a copula.
    """
    from backend.memory.episodic import _same_fact_text

    cases = [
        # (description, a, b, same fact?)
        ("colour re-teach",
         "User: I prefer the color fern-green-1a63 for status indicators. "
         "Just acknowledge it briefly.",
         "User: I prefer the color fern-green-ba25 for status indicators. "
         "Just acknowledge it briefly.", True),
        ("card number re-teach",
         "User: my library card number is 880417. Assistant: saved.",
         "User: my library card number is 999111. Assistant: saved.", True),
        ("natural colour word after a copula",
         "my favourite colour is blue for status chips",
         "my favourite colour is green for status chips", True),
        ("two different questions sharing a template",
         "User: What is my library card number? Answer with the number only.",
         "User: Which color do I prefer for status indicators? "
         "Answer with the color only.", False),
        ("two different facts",
         "User: my library card number is 880417 and it lives in the blue wallet.",
         "User: my staging deployment is named kestrel and it lives in eu-west.",
         False),
        ("the same text is not a re-teach",
         "my library card number is 880417 and it is saved",
         "my library card number is 880417 and it is saved", False),
        ("too short to have a template",
         "my name is Ada", "my name is Bob", False),
    ]
    for name, a, b, want in cases:
        assert _same_fact_text(a, b) is want, name


def test_a_retaught_value_folds_below_the_cosine_threshold(monkeypatch, tmp_path):
    """The fold must not depend on cosine: with the comparison forced to 0.5
    (well under the 0.92 threshold) the re-taught value still supersedes."""
    import backend.memory.episodic as ep
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "fold.db"), biometric_key=b"\0" * 32)
    st._embed = _Stub()
    monkeypatch.setattr(ep, "compare_embeddings", lambda *a, **k: 0.5)

    old = ("User: I prefer the color fern-green-1a63 for status indicators. "
           "Just acknowledge it briefly.")
    new = ("User: I prefer the color fern-green-ba25 for status indicators. "
           "Just acknowledge it briefly.")
    st.fragment_and_store(old, session_id="conv-old", chunk_type="context_fragment")
    st.fragment_and_store(new, session_id="conv-new", chunk_type="context_fragment")

    rows = st.db.execute(
        "SELECT id, content, folded_into FROM context_chunks ORDER BY timestamp"
    ).fetchall()
    assert len(rows) == 2
    old_id, old_txt, old_folded = rows[0]
    new_id, _new_txt, new_folded = rows[1]
    assert "1a63" in old_txt
    assert new_folded is None, "the newest value stays live"
    assert old_folded == new_id, "the re-taught value must supersede the old one"
    assert _live(st) == 1


# ── CT-W10-12 (T48): recall returns the PRODUCER, not just the text ─────────

def test_recall_carries_the_producer_taxonomy(store):
    """`trusted` means "not outside content", nothing more. The consumer needs
    to know whether a row is the user's statement, this agent's own earlier
    answer, or a tool output - otherwise it answers from its own echo."""
    store.fragment_and_store(
        "User: my library card number is 880417. Assistant: saved.",
        session_id="s", chunk_type="context_fragment", tool_name="user_turn")
    store.fragment_and_store(
        "[Step 1: Recall my library card number from memory] I cannot provide it.",
        session_id="s", chunk_type="context_fragment", tool_name="der_step")
    store.fragment_and_store(
        "[Step 1: grep 880417 in config.json] match on line 12",
        session_id="s", chunk_type="der_output", tool_name="run_command")

    rows = store.retrieve_context_chunks(
        "Recall my library card number from memory",
        session_id=None, limit=3, min_similarity=-1.0, with_meta=True)

    producers = {r["producer"] for r in rows}
    assert "user_statement" in producers
    assert "agent_step" in producers
    assert "tool:run_command" in producers
    for r in rows:
        assert r["content"] and r["chunk_type"]


def test_recall_still_returns_plain_text_by_default(store):
    store.fragment_and_store(
        "User: my library card number is 880417. Assistant: saved.",
        session_id="s", chunk_type="context_fragment", tool_name="user_turn")

    rows = store.retrieve_context_chunks(
        "my library card number", session_id=None, limit=3, min_similarity=-1.0)

    assert rows and all(isinstance(r, str) for r in rows)


def test_a_step_fragment_without_a_tool_is_marked_der_step(tmp_path):
    """The write-side half: a step output must not look like a user turn."""
    from types import SimpleNamespace

    from backend.agent.mcm_protocol.actions import pacman_fragment as pf
    from backend.memory.episodic import EpisodicStore

    class _Stub:
        @staticmethod
        def encode_with_meta(text):
            from backend.memory.embedding import Embedding

            return Embedding(vector=[0.1] * 1024, backend="stub",
                             chunk_count=1, truncated=False)

    st = EpisodicStore(db_path=str(tmp_path / "step.db"), biometric_key=b"\0" * 32)
    st._embed = _Stub()
    mi = SimpleNamespace(episodic=st)

    pf.execute({"mi": mi, "session_id": "s", "tool_name": "",
                "response_text": (
                    "[Step 1] def parse(x): return x  # function completed, "
                    "the file was written and the result is ready for review")},
               {})
    pf._FRAGMENT_QUEUE.join()

    row = st.db.execute("SELECT content, tool_name FROM context_chunks").fetchone()
    assert row is not None, "the step fragment must be stored"
    assert row[1] == "der_step"
