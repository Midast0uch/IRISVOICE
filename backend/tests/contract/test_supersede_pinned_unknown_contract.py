"""A supersede fold never runs while the pinned set cannot be read.

Found 2026-11-09 (memory writer audit): when fold_chunks.pinned_chunk_ids
raised, EpisodicStore treated the pinned set as EMPTY and folded anyway, so a
pinned chunk could be folded with no log line (REQ-4 AC2 says never). Now an
unreadable pinned set skips the fold for that write and logs it. Same store
and stub as test_memory_user_turn_contract (the real supersede path).
"""
from __future__ import annotations

import pytest

from backend.tests.contract.test_memory_user_turn_contract import _Stub


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "user.db"), biometric_key=b"\0" * 32)
    st._embed = _Stub()
    return st


def test_no_fold_when_the_pinned_set_is_unknown(store, monkeypatch, caplog):
    import backend.memory.fold_chunks as fc

    def _boom(_db):
        raise RuntimeError("pins unreadable")

    monkeypatch.setattr(fc, "pinned_chunk_ids", _boom)
    store.fragment_and_store(
        "the user's favourite colour is green for status chips", session_id="s")
    store.fragment_and_store(
        "the user's favourite colour is blue for status chips", session_id="s")
    folded = store.db.execute(
        "SELECT COUNT(*) FROM context_chunks WHERE folded_into IS NOT NULL").fetchone()[0]
    assert folded == 0, "folded while the pinned set was unknown"
    assert any("supersede fold skipped" in r.getMessage() for r in caplog.records)
