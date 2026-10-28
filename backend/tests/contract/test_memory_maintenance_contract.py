"""REQ-5 AC2 contract: one pass, one law, and a dry run that changes nothing."""
import time

import pytest


@pytest.fixture()
def store(tmp_path):
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=str(tmp_path / "memory.db"), biometric_key=b"\0" * 32)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for i in range(20):
        st.db.execute(
            """INSERT INTO context_chunks (id, session_id, chunk_type, zone, content,
                                           embedding_backend, retrieval_count, timestamp)
               VALUES (?,?,?,?,?,?,?,?)""",
            (f"t{i}", "sess-m", "context_fragment", "tool", f"row {i}", "lfm25-emb-350m", 0, now),
        )
    st.db.commit()
    yield st


def test_dry_run_reports_the_prune_and_deletes_nothing(store, monkeypatch):
    from backend.memory import chunk_decay, maintenance

    monkeypatch.setattr(chunk_decay, "ZONE_BUDGET", {"tool": (5, 10 ** 9)})
    rep = maintenance.maintain(store.db, dry_run=True)

    assert rep["ok"] is True
    assert rep["decay"]["pruned"] == 15, "the pass must see 20 rows against a budget of 5"
    assert store.db.execute("SELECT COUNT(*) FROM context_chunks").fetchone()[0] == 20
    assert "tool" in rep["before"]["over_budget"]


def test_real_pass_brings_the_zone_within_budget(store, monkeypatch):
    from backend.memory import chunk_decay, maintenance

    monkeypatch.setattr(chunk_decay, "ZONE_BUDGET", {"tool": (5, 10 ** 9)})
    rep = maintenance.maintain(store.db)

    assert rep["ok"] is True
    left = store.db.execute("SELECT COUNT(*) FROM context_chunks").fetchone()[0]
    assert left == 5, f"expected 5 rows after the budget prune, found {left}"
    assert rep["after"]["over_budget"] == []
    # The law is the judge, and the report says where the rows came from.
    assert rep["decay"]["by_zone"].get("tool") == 15
    has_events = store.db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'memory_events'").fetchone()[0]
    if has_events:  # a real store records WHY; a bare test store has no event table
        reasons = [r[0] for r in store.db.execute(
            "SELECT payload FROM memory_events WHERE label = 'MEMORY_PRUNED'").fetchall()]
        assert any("zone_budget" in str(r) for r in reasons)


def test_reclaim_refuses_below_the_minimum(store):
    from backend.memory import maintenance

    rep = maintenance.reclaim(store.db)
    assert rep["vacuumed"] is False
    assert rep["reason"] in ("below_minimum", "dry_run")
