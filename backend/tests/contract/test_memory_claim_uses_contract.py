"""Memory surface: "every time it was used" - the contract (MEMORY-UX-PLAN.md 7.4).

  GET /api/memory/claims/{landmark_id}/uses?limit=50  ->  {"uses": [{ts, thread, turn, episode, outcome, step}], "total"}

The truest record that names a claim is mycelium_episode_index (one row per episode stored while the claim was in
play; indexed by landmark_id). It names the THREAD and the moment. No writer records the TURN that was given a claim
(RECALL_DELIVERED names chain ids), so `turn` is null unless the episode id itself is "<conversation>:<turn>", and
`step` is always null. `outcome` is the user's own verdict on the episode, never its success flag.

Driven through the real router against a TEMP store with the live schema. What this pins:
  * the uses of THIS claim only, newest first, bounded by `limit` (clamped), `total` counting all of them;
  * the exact keys of a use, and the honest nulls (turn, step, outcome) - "success" is NOT "helped";
  * an unknown claim is a 404; a claim nobody used is {"uses": [], "total": 0};
  * the endpoint writes nothing (the store file is byte-identical);
  * every statement it runs on the episode index and the episodes is a SEARCH, never a SCAN.
"""
from __future__ import annotations

import contextlib
import hashlib
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.contract.test_memory_api_contract import MEMORY_DDL

T0 = time.time() - 7200
USED = [  # episode_id, thread, age offset, (user_confirmed, user_corrected, outcome_type) or None for "no episodes row"
    ("ep-0", "session_iris", 0, (0, 0, "success")),       # did not fail: NOT "helped"
    ("ep-1", "conv-a", 10, (1, 0, "success")),            # the user confirmed it: helped
    ("ep-2", "conv-a", 20, (0, 1, "failure")),            # the user corrected it: misled
    ("ep-3", "conv-b", 30, (1, 1, "success")),            # both: the correction wins
    ("conv-a:t9", "conv-a", 40, None),                    # an episode id that names its turn
    ("ep-5", "conv-b", 50, (0, 0, "failure")),            # failed: NOT "misled"
    ("ep-6", "session_iris", 60, None),
]


def _seed(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(MEMORY_DDL)
    for lid in ("C_USED", "C_FRESH", "C_OTHER"):
        con.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
                    " cumulative_score, micro_abstract_text, created_at, tier) VALUES (?,?,?,?,?,?,?,?,?)",
                    (lid, lid.lower(), "task_x", "[]", "[]", 0.6, "claim " + lid, T0, "candidate"))
    for i, (ep, thread, age, verdict) in enumerate(USED):
        con.execute("INSERT INTO mycelium_episode_index VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"i{i}", ep, thread, "[]", "[]", "C_USED", "h", 3, T0 + 1000 - age))
        if verdict is not None:
            con.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_type, user_confirmed, user_corrected)"
                        " VALUES (?,?,?,?,?,?)", (ep, thread, "task", verdict[2], verdict[0], verdict[1]))
    for i in range(2):
        con.execute("INSERT INTO mycelium_episode_index VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"o{i}", f"ep-o{i}", "conv-z", "[]", "[]", "C_OTHER", "h", 3, T0 + 2000 + i))
    con.execute("INSERT INTO mycelium_episode_index VALUES ('n0','ep-n0','conv-z','[]','[]',NULL,'h',3,?)", (T0,))
    con.commit()
    con.close()


class Env:
    pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    mem = tmp_path / "memory.db"
    _seed(mem)
    from backend.memory import surface_queries as sq
    import backend.api.memory as api

    monkeypatch.setattr(sq, "memory_db_path", lambda: mem)
    app = FastAPI()
    app.include_router(api.router)
    e = Env()
    e.client, e.mem, e.sq = TestClient(app), mem, sq
    return e


def _uses(e, claim="C_USED", query=""):
    return e.client.get(f"/api/memory/claims/{claim}/uses{query}")


def test_uses_lists_this_claims_turns_newest_first_with_the_documented_keys(env):
    r = _uses(env)
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"uses", "total"} and d["total"] == len(USED) == len(d["uses"])
    assert [u["episode"] for u in d["uses"]] == [u[0] for u in USED]            # newest first (age offset ascending)
    assert [u["ts"] for u in d["uses"]] == sorted((u["ts"] for u in d["uses"]), reverse=True)
    for u in d["uses"]:
        assert set(u) == {"ts", "thread", "turn", "episode", "outcome", "step"}
    first = d["uses"][0]
    assert first["thread"] == "session_iris" and first["ts"] == pytest.approx(T0 + 1000)
    assert {u["thread"] for u in d["uses"]} == {"session_iris", "conv-a", "conv-b"}      # nothing of another claim
    assert all(u["episode"] not in ("ep-o0", "ep-o1", "ep-n0") for u in d["uses"])


def test_what_the_record_cannot_name_is_null_and_success_is_not_helped(env):
    by = {u["episode"]: u for u in _uses(env).json()["uses"]}
    assert by["ep-1"]["outcome"] == "helped"                                    # the user confirmed
    assert by["ep-2"]["outcome"] == "misled" and by["ep-3"]["outcome"] == "misled"   # the user corrected (wins over confirmed)
    assert by["ep-0"]["outcome"] is None and by["ep-5"]["outcome"] is None      # success / failure alone say nothing about the claim
    assert by["conv-a:t9"]["outcome"] is None and by["ep-6"]["outcome"] is None  # no episode row: no verdict
    assert by["conv-a:t9"]["turn"] == "t9"                                       # an episode id that names its turn
    assert all(u["turn"] is None for e_, u in by.items() if e_ != "conv-a:t9")
    assert all(u["step"] is None for u in by.values())


def test_limit_bounds_the_rows_and_total_counts_them_all(env):
    d = _uses(env, query="?limit=3").json()
    assert [u["episode"] for u in d["uses"]] == ["ep-0", "ep-1", "ep-2"] and d["total"] == len(USED)
    assert len(_uses(env, query="?limit=0").json()["uses"]) == 1                # clamped up to 1
    assert len(_uses(env, query="?limit=100000").json()["uses"]) == len(USED)   # clamped down, not an error
    assert len(_uses(env).json()["uses"]) == len(USED)                          # the default is 50
    assert _uses(env, query="?limit=abc").status_code == 422                    # not a number: FastAPI's own answer


def test_the_limit_cap_holds_with_more_rows_than_the_cap(env):
    con = sqlite3.connect(env.mem)
    for i in range(130):
        con.execute("INSERT INTO mycelium_episode_index VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"x{i}", f"ep-x{i}", "conv-a", "[]", "[]", "C_FRESH", "h", 3, T0 + 3000 + i))
    con.commit()
    con.close()
    d = _uses(env, "C_FRESH", "?limit=100000").json()
    assert len(d["uses"]) == env.sq.USES_MAX == 100 and d["total"] == 130
    assert d["uses"][0]["episode"] == "ep-x129"                                 # still newest first
    assert len(_uses(env, "C_FRESH").json()["uses"]) == 50                      # the default limit


def test_unknown_claim_is_404_and_an_unused_claim_is_empty(env):
    assert _uses(env, "C_NOPE").status_code == 404
    assert _uses(env, "C_FRESH").json() == {"uses": [], "total": 0}


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    con = sqlite3.connect("file:" + Path(p).as_posix() + "?mode=ro", uri=True)
    try:
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
            h.update(name.encode())
            for row in con.execute(f'SELECT * FROM "{name}" ORDER BY rowid'):
                h.update(repr(row).encode())
    finally:
        con.close()
    return h.hexdigest()


def test_the_endpoint_writes_nothing(env):
    before = _digest(env.mem)
    for q in ("", "?limit=2", "?limit=9999"):
        assert _uses(env, query=q).status_code == 200
    assert _uses(env, "C_NOPE").status_code == 404
    assert _digest(env.mem) == before


def test_every_statement_on_the_episode_index_and_episodes_is_a_search(env, monkeypatch):
    seen: list[str] = []
    real = env.sq.read_only

    @contextlib.contextmanager
    def traced(path):
        with real(path) as con:
            con.set_trace_callback(lambda s: seen.append(s) if s.lstrip().upper().startswith(("SELECT", "WITH")) else None)
            yield con

    monkeypatch.setattr(env.sq, "read_only", traced)
    assert _uses(env).status_code == 200
    assert _uses(env, "C_FRESH").status_code == 200
    assert _uses(env, "C_NOPE").status_code == 404
    tables = ("mycelium_episode_index", "episodes", "mycelium_landmarks")
    stmts = [s for s in seen if any(f"FROM {t}" in s for t in tables)]
    assert len(stmts) >= 6, stmts
    con, bad = sqlite3.connect(env.mem), []
    for sql in stmts:
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql)]
        for t in (t for t in tables if f"FROM {t}" in sql):
            if not any(line.startswith(f"SEARCH {t}") for line in plan) or any(line.startswith(f"SCAN {t}") for line in plan):
                bad.append((" ".join(sql.split())[:140], plan))
    con.close()
    assert not bad, bad


def test_a_use_names_the_turn_whose_events_came_just_before_it(env):
    """No writer puts the turn on the index row and live episode ids are uuids (0 of 4,460 named a turn, 2026-10-26).
    Each turn's events carry "<conversation>:<turn>" and the episode is stored at the turn's end, so the use names
    the turn whose last event in the SAME thread precedes it within USE_TURN_WINDOW_S - and nothing else."""
    from backend.tests.contract.test_memory_api_contract import _ev

    con = sqlite3.connect(env.mem)
    con.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_thread_ts ON memory_events(thread_id, ts)")
    at = {ep: T0 + 1000 - age for ep, _t, age, _v in USED}
    _ev(con, "e1", at["ep-1"] - 30, "STEP_DONE", "conv-a", episode="conv-a:t1")       # ep-1's turn
    _ev(con, "e0", at["ep-1"] - 90, "STEP_DONE", "conv-a", episode="conv-a:t0")       # an older turn: not it
    _ev(con, "e2", at["ep-3"] - env.sq.USE_TURN_WINDOW_S - 5, "STEP_DONE", "conv-b", episode="conv-b:t2")  # too old
    _ev(con, "e3", at["ep-0"] - 5, "STEP_DONE", "conv-x", episode="conv-x:t3")        # another thread
    _ev(con, "e4", at["ep-6"] - 5, "STEP_DONE", "session_iris", episode="plain-episode")  # no turn in the id
    con.commit()
    plan = " ".join(str(r) for r in con.execute(
        "EXPLAIN QUERY PLAN SELECT episode_id FROM memory_events WHERE thread_id = ? AND ts <= ? AND ts >= ? "
        "AND instr(episode_id, ':') > 0 ORDER BY ts DESC LIMIT 1", ("conv-a", 1.0, 0.0)))
    con.close()
    assert "idx_memory_events_thread_ts" in plan and "TEMP B-TREE" not in plan, plan

    by = {u["episode"]: u for u in _uses(env).json()["uses"]}
    assert by["ep-1"]["turn"] == "t1"
    assert by["conv-a:t9"]["turn"] == "t9"              # an episode id that names its turn still wins
    assert by["ep-3"]["turn"] is None                   # its only event is outside the window
    assert by["ep-0"]["turn"] is None                   # an event of another thread never counts
    assert by["ep-6"]["turn"] is None                   # an event whose episode id names no turn
    assert all(u["step"] is None for u in by.values())
