"""A recall "helped" only when the step it was delivered to was VERIFIED (owner 2026-11-23).

Measured before: 6,115 of 9,683 RECALL_HELPED rows (63 %) came from steps nobody checked; they slowed the fading of 26,221
of 95,358 chunks and raised their rank. Each test FAILS on the code before this change.
"""
from __future__ import annotations

import sqlite3

from backend.memory import memory_events as me
from backend.tests.contract.test_event_emitters_memory_contract import _rows, _step, store  # noqa: F401  (the fixture)


def test_an_unchecked_step_credits_nothing_and_a_later_check_still_can(store):  # noqa: F811
    assert "RECALL_HELPED" not in _step(store, "2", True, ["rt-a"], verified="UNVERIFIED")
    assert _rows(store, "RECALL_HELPED") == [] and _rows(store, "RECALL_MISLED") == []
    assert "RECALL_HELPED" in _step(store, "3", True, ["rt-a"], verified="VERIFIED")     # unknown was not an outcome
    assert "RECALL_MISLED" in _step(store, "4", False, ["rt-b"], verified="UNVERIFIED")  # it failed: that is known


def _old_rows():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE memory_events (label TEXT, thread_id TEXT, evidence TEXT)")
    con.executemany("INSERT INTO memory_events VALUES (?,?,?)", [
        ("RECALL_HELPED", "unchecked", "none")] * 4 + [("RECALL_HELPED", "checked", "verifier"), ("RECALL_MISLED", "bad", "verifier"),
                                                       ("RECALL_MISLED", "failed", "none")])
    return con


def test_the_rows_already_stored_do_not_slow_the_fade():
    from backend.memory.chunk_decay import _outcome_multipliers

    m = _outcome_multipliers(_old_rows())
    assert "unchecked" not in m and m["checked"] == 0.5 and m["bad"] == 1.8 and m["failed"] == 1.8


def test_the_rows_already_stored_do_not_raise_the_rank():
    from backend.memory import memory_rank as mr

    mr._cache.clear()
    out = mr._strand_outcomes(_old_rows())
    mr._cache.clear()
    assert "unchecked" not in out and out["checked"] == (1, 0) and out["bad"] == (0, 1)


def test_every_reader_of_outcomes_uses_the_one_predicate():
    from pathlib import Path

    root = Path(me.__file__).parent
    for name in ("chunk_decay.py", "memory_rank.py", "event_export.py"):
        assert "RECALL_COUNTS_SQL" in root.joinpath(name).read_text(encoding="utf-8"), name
