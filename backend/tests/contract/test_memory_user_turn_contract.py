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
            v[4] = 1.0
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
