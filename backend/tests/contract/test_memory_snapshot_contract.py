"""Memory snapshot - the contract (MEMORY-SURFACE-BUILD.md section 6: ONE query module).

  GET /api/memory/snapshot?threads=&events=&include_eval=   ==   surface_queries.snapshot(...)
  docs/Design/Memory-Cortex/export_snapshot.py               ==   a thin CLI over the same function

The dashboard (components/memory/MemorySurface.tsx, lib/memory/scene/engine.ts) draws everything from ONE model:
window.IRIS_MEMORY = {meta, famCounts, domCounts, sessions, events, landmarks, edges, episodes, artifacts, oracle, mind,
sectors, pins, spaces, nodes, nodeEdges, quorum, recalls}. This file pins, against a TEMP store (the live schema, a small
cast; the fixture is the one test_memory_api_contract.py builds):
  * every key the frontend reads is present (top level, meta, and the element shape of each collection), also on a store
    that lacks every optional table;
  * every list is bounded (threads <= 120, events <= 12000, 400 events per thread) and a larger request is clamped;
  * eval-* threads are left out by default and counted in meta.eval_share;
  * read-only: the stores are byte-identical after the call and every connection is a mode=ro URI;
  * no statement scans a big table, except the one documented whole-table read (the topic-domain count), and the two
    statements that would scan without memory_events(thread_id) / memory_chain(chain_id) run only when those exist;
  * the exporter and the endpoint produce the same JSON.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

from backend.tests.contract.test_memory_api_contract import (  # noqa: F401  (env is the fixture)
    BIG_TABLES, MINIMAL_DDL, NOW, _chain, _ev, _file_digest, _plan_lines, env,
)

REPO = Path(__file__).resolve().parents[3]

# the keys of the exporter's snap dict: what the frontend reads
TOP_KEYS = ["meta", "famCounts", "domCounts", "sessions", "events", "landmarks", "edges", "episodes", "artifacts", "oracle",
            "mind", "sectors", "pins", "spaces", "nodes", "nodeEdges", "quorum", "recalls"]
META_KEYS = {"source", "generated", "counts", "eval_share", "warnings", "available"}
COUNT_KEYS = {"events", "chain", "landmarks", "landmarks_absorbed", "edges", "merges", "episodes", "fragments", "artifacts",
              "sessions", "recall_turns"}
SHAPES = {
    "sessions": {"id", "objective", "started", "ended", "exit", "traj", "eval", "episodes", "messages", "strands", "ghost"},
    "events": {"id", "ts", "family", "label", "valence", "actor", "evidence", "episode", "session", "domain", "landmark"},
    "landmarks": {"id", "claim", "cls", "tier", "permanent", "evidence", "evidence_counts", "activations", "contradictions",
                  "last_activated", "last_verified", "born", "session", "fams", "domain", "steps"},
    "edges": {"id", "a", "b", "score", "traversals", "hits", "misses", "last"},
    "episodes": {"id", "session", "summary", "outcome", "score", "failure_reason", "corrected", "confirmed", "duration",
                 "tools", "ts"},
    "artifacts": {"id", "kind", "name", "folder", "session", "ts", "weight", "seed"},
    "sectors": {"key", "parent", "label", "status", "members", "evidence", "last"},
    "pins": {"id", "title", "type", "created", "permanent", "held", "links", "refs", "tags", "domain"},
    "spaces": {"id", "description", "active", "write_lock", "render_order", "position"},
    "nodes": {"id", "space", "label", "conf", "chan", "born", "used"},
    "nodeEdges": {"a", "b", "score", "traversals", "observations", "last"},
    "quorum": {"ts", "session", "signal", "weight", "threat", "shadow", "landmark"},
    "recalls": {"turn", "session", "ts", "steps"},
}
SNAP = "/api/memory/snapshot"

# tables the snapshot reads that the shared fixture does not create (registry, coordinate nodes, documents)
EXTRA_DDL = """
CREATE TABLE mycelium_spaces (space_id TEXT PRIMARY KEY, description TEXT, active INTEGER, write_lock INTEGER,
  render_order INTEGER, position INTEGER);
CREATE TABLE mycelium_nodes (node_id TEXT PRIMARY KEY, space_id TEXT, label TEXT, confidence REAL, source_channel INTEGER,
  created_at REAL, updated_at REAL, access_count INTEGER);
CREATE INDEX idx_nodes_space ON mycelium_nodes(space_id);
CREATE TABLE mycelium_edges (edge_id TEXT PRIMARY KEY, from_node_id TEXT, to_node_id TEXT, score REAL,
  traversal_count INTEGER, observation_count INTEGER, last_traversed REAL);
CREATE TABLE document_data (document_id TEXT PRIMARY KEY, conversation_id TEXT, fmt TEXT, kind TEXT, title TEXT, summary TEXT,
  created_at REAL, capture_path TEXT);
CREATE INDEX idx_document_data_created ON document_data(created_at);
"""


def _seed_extra(mem: Path) -> None:
    con = sqlite3.connect(mem)
    con.executescript(EXTRA_DDL)
    con.execute("INSERT INTO mycelium_spaces VALUES ('semantic','what is true',1,0,1,0)")
    con.executemany("INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,?,?,?)",
                    [("n1", "semantic", "alpha", 0.9, 2, NOW - 30, NOW - 20, 4), ("n2", "semantic", "beta", None, None, NOW - 30, NOW - 10, 0)])
    con.executemany("INSERT INTO mycelium_edges VALUES (?,?,?,?,?,?,?)",
                    [("ne1", "n1", "n2", 0.7, 3, 5, NOW - 5), ("ne2", "n1", "missing-node", 0.5, 1, 1, NOW - 5)])
    con.execute("INSERT INTO document_data VALUES ('doc-1','c1','json','research','Sales report',NULL,?,NULL)", (NOW - 3,))
    con.commit()
    con.close()


@pytest.fixture()
def snap_env(env):
    _seed_extra(env.mem)
    return env


def _get(env, query: str = "") -> dict:
    r = env.client.get(SNAP + query)
    assert r.status_code == 200, r.text
    return r.json()


def _assert_shapes(d: dict) -> None:
    assert list(d) == TOP_KEYS
    assert set(d["meta"]) == META_KEYS and COUNT_KEYS <= set(d["meta"]["counts"])
    assert isinstance(d["meta"]["eval_share"], list) and len(d["meta"]["eval_share"]) == 2
    for key, want in SHAPES.items():
        for item in d[key]:
            assert want <= set(item), (key, want - set(item))
    for key in ("famCounts", "domCounts"):
        assert isinstance(d[key], dict)
    assert d["mind"] == []


# ── the key guard ───────────────────────────────────────────────────────────────────────────────
def test_snapshot_has_every_key_the_frontend_reads(snap_env):
    d = _get(snap_env)
    _assert_shapes(d)
    # the cast is in it: values, not only keys
    c = d["meta"]["counts"]
    assert c["events"] == 7 and c["chain"] == 8 and c["landmarks"] == 3 and c["landmarks_absorbed"] == 2
    assert c["edges"] == 1 and c["merges"] == 1 and c["episodes"] == 1 and c["fragments"] == 0 and c["artifacts"] == 1
    assert d["famCounts"] == {"intent": 3, "memory": 4}
    live = {x["id"]: x for x in d["landmarks"]}
    assert set(live) == {"C_LIVE", "C_CAND", "C_SURV"} and live["C_LIVE"]["domain"] == "web"
    assert live["C_LIVE"]["sector"] == "web/search" and live["C_LIVE"]["channel"] == 3
    assert live["C_LIVE"]["evidence_counts"]["recurrence"] == 10
    assert [(e["a"], e["b"]) for e in d["edges"]] == [(d["landmarks"].index(live["C_LIVE"]), d["landmarks"].index(live["C_CAND"]))]
    assert [n["id"] for n in d["nodes"]] == ["n2", "n1"] and d["nodes"][0]["conf"] == 0.5   # newest first, null confidence = 0.5
    assert len(d["nodeEdges"]) == 1 and {d["nodes"][d["nodeEdges"][0]["a"]]["id"], d["nodes"][d["nodeEdges"][0]["b"]]["id"]} == {"n1", "n2"}
    assert d["artifacts"][0]["name"] == "Sales report" and d["artifacts"][0]["kind"] == "web"
    assert [s["key"] for s in d["sectors"]] == ["web", "general", "web/search"]
    assert d["pins"][0]["id"] == "p1" and d["pins"][0]["held"] is True
    assert d["spaces"][0]["id"] == "semantic" and d["quorum"][0]["signal"] == "update_velocity_anomaly"
    assert d["meta"]["available"]["sectors"] and d["meta"]["available"]["spaces"] and d["meta"]["available"]["quorum"]


def test_snapshot_sessions_recalls_and_ref_resolution(snap_env):
    r = snap_env.ids["root"]
    d = _get(snap_env)
    by_id = {s["id"]: s for s in d["sessions"]}
    assert set(by_id) == {r, snap_env.ids["strand"], "maintenance"}
    root = by_id[r]
    assert root["objective"] == "Plan the release" and len(root["messages"]) == 2 and len(root["traj"]) == 5
    assert [s["id"] for s in root["strands"]] == [snap_env.ids["strand"]] and root["episodes"] == ["ep1"]
    assert {e["session"] for e in d["events"]} == set(by_id)
    assert next(e for e in d["events"] if e["id"] == "e-prom")["landmark"] == "C_LIVE"
    # the landmark's families come from the events that name it (promotion is a 'memory' event -> index 6)
    assert next(x for x in d["landmarks"] if x["id"] == "C_LIVE")["fams"] == [6]
    (turn,) = d["recalls"]
    assert turn["turn"] == "T1" and turn["session"] == r and turn["steps"][0]["outcome"] == "helped"
    # memory_chain has no chain_id index here: refs stay empty shells and the scan never runs, and the answer says so
    assert [x["did"] for x in turn["steps"][0]["refs"]] == ["", "", ""]
    assert any("memory_chain(chain_id)" in w for w in d["meta"]["warnings"])
    con = sqlite3.connect(snap_env.mem)
    con.execute("CREATE INDEX idx_memory_chain_chain_id ON memory_chain(chain_id)")
    con.commit()
    con.close()
    d = _get(snap_env)
    assert [x["did"] for x in d["recalls"][0]["steps"][0]["refs"]] == ["step 0 of the root", "step 1 of the root", ""]
    assert not any("memory_chain(chain_id)" in w for w in d["meta"]["warnings"])


# ── eval threads ────────────────────────────────────────────────────────────────────────────────
def test_eval_threads_are_left_out_by_default_and_counted(snap_env):
    con = sqlite3.connect(snap_env.mem)
    _ev(con, "e-eval-rd", NOW - 3500, "RECALL_DELIVERED", "eval-c1_thing-abc123", episode="TE", step="s1",
        links={"recall_trace_id": "rt-eval"}, payload={"source": "neighbors", "refs": []})
    con.commit()
    con.close()
    d = _get(snap_env)
    assert not any(s["eval"] or s["id"].startswith("eval-") for s in d["sessions"])
    assert not any(e["session"].startswith("eval-") for e in d["events"])
    assert [t["turn"] for t in d["recalls"]] == ["T1"]                      # an evaluation turn's recall is left out too
    assert d["meta"]["eval_share"] == [2, 8]                                # ... but the share still counts them
    d2 = _get(snap_env, "?include_eval=true")
    assert {s["id"] for s in d2["sessions"]} >= {"eval-c1_thing-abc123"}
    assert next(s for s in d2["sessions"] if s["id"] == "eval-c1_thing-abc123")["eval"] is True
    assert {t["turn"] for t in d2["recalls"]} == {"T1", "TE"}
    # the share is a sample while memory_events(thread_id) is not indexed (and says so), exact once it is
    assert any("memory_events(thread_id)" in w for w in d["meta"]["warnings"])
    con = sqlite3.connect(snap_env.mem)
    con.execute("CREATE INDEX idx_memory_events_thread_ts ON memory_events(thread_id, ts)")
    con.commit()
    con.close()
    d3 = _get(snap_env)
    assert d3["meta"]["eval_share"] == [2, 8] and not any("memory_events(thread_id)" in w for w in d3["meta"]["warnings"])
    assert d3["meta"]["counts"]["sessions"] == 4                             # COUNT(DISTINCT thread_id), eval included


def test_a_chat_eval_run_is_left_out_before_the_thread_cut(snap_env):
    """The eval harness runs its tasks as chat conversations titled "[eval] ..." (ids conv-NNNN): no thread-id prefix
    names them. 2026-10-24, live: 46 of the 48 sessions of a snapshot were such runs, each with eval=False. The chat
    TITLE decides, and it decides before the cut to `threads`, so a run never takes a real thread's slot."""
    ev = snap_env.ids["eval_root"]
    con = sqlite3.connect(snap_env.mem)
    _ev(con, "e-chat-eval", NOW - 3400, "GOAL_SET", ev, episode="TC", family="intent")   # the newest thread
    con.commit()
    con.close()
    d = _get(snap_env)
    assert ev not in {s["id"] for s in d["sessions"]}
    assert not any(e["session"] == ev for e in d["events"])
    one = _get(snap_env, "?threads=1")["sessions"]
    assert len(one) == 1 and one[0]["id"] != ev                              # the slot went to a real thread
    d2 = _get(snap_env, "?include_eval=true")
    assert next(s for s in d2["sessions"] if s["id"] == ev)["eval"] is True


def test_eval_runs_never_starve_the_window_of_real_threads(snap_env):
    """Live, 2026-10-24: 5,881 of the newest 6,000 events belonged to eval chat runs, so the ts-ordered window held 4
    real threads. With memory_events(thread_id) indexed, the newest REAL threads come first. Both harnesses count:
    "[eval] ..." (run_evals.py) and "[pair] ..." (run_pairs.py)."""
    pair = snap_env.cs.create_conversation(title="[pair] c2_other")["id"]
    con = sqlite3.connect(snap_env.mem)
    con.execute("CREATE INDEX idx_memory_events_thread_ts ON memory_events(thread_id, ts)")
    for i in range(6):                                                       # all newer than every real event
        _ev(con, f"e-run-{i}", NOW - 100 + i, "PLAN_MADE", (snap_env.ids["eval_root"], pair)[i % 2], episode="TR")
    con.commit()
    con.close()
    d = _get(snap_env, "?events=3&threads=2")
    ids = {s["id"] for s in d["sessions"]}
    assert len(ids) == 2 and not ids & {snap_env.ids["eval_root"], pair}    # old: the 3 newest events were all runs
    assert not any(e["session"] in (snap_env.ids["eval_root"], pair) for e in d["events"])


def test_a_strand_chat_deleted_is_a_ghost_with_its_name(snap_env):
    """Phase 3 DONE (MEMORY-SURFACE-BUILD section 7): a deleted strand shows as a ghost with its name. Chat's delete
    writes a STRAND_DELETED tombstone that keeps the title; the snapshot named such a thread by its raw id."""
    con = sqlite3.connect(snap_env.mem)
    _ev(con, "e-gone-goal", NOW - 3300, "GOAL_SET", "conv-gone", episode="TG", family="intent")
    _ev(con, "e-gone-tomb", NOW - 3200, "STRAND_DELETED", "conv-gone", family="memory",
        payload={"title": "Plan the trip", "at": NOW - 3200})
    con.commit()
    con.close()
    sess = {s["id"]: s for s in _get(snap_env)["sessions"]}
    assert sess["conv-gone"]["ghost"] is True and sess["conv-gone"]["objective"] == "Plan the trip"
    assert sess[snap_env.ids["root"]]["ghost"] is False                      # a live chat strand is no ghost


def test_a_claim_carries_its_steps_and_every_territory_has_a_name(snap_env):
    """The page says how a claim was done ("how: read file -> write file") from the nodes its traversal walked, and
    names every territory; the snapshot dropped traversal_sequence and sent label NULL for all 21 live sectors."""
    con = sqlite3.connect(snap_env.mem)
    con.execute("UPDATE mycelium_landmarks SET traversal_sequence = ? WHERE landmark_id = 'C_LIVE'",
                (json.dumps(["n2", "not-a-node", "n1"]),))
    con.commit()
    con.close()
    d = _get(snap_env)
    live = {x["id"]: x for x in d["landmarks"]}
    assert live["C_LIVE"]["steps"] == [{"space": "semantic", "label": "beta"}, {"space": "semantic", "label": "alpha"}]
    assert live["C_CAND"]["steps"] == []
    assert {s["key"]: s["label"] for s in d["sectors"]} == {"web": "web", "general": "general", "web/search": "search"}


# ── bounds ──────────────────────────────────────────────────────────────────────────────────────
def test_lists_are_bounded_and_a_larger_request_is_clamped(snap_env, monkeypatch):
    sq = snap_env.sq
    assert (sq.SNAPSHOT_THREADS_MAX, sq.SNAPSHOT_EVENTS_MAX, sq.EVENTS_CAP) == (120, 12000, 400)
    con = sqlite3.connect(snap_env.mem)
    rows = []
    for t in range(130):                      # 130 threads x 100 events = 13,000 > 12,000, interleaved in time
        for i in range(100):
            rows.append((f"b-{t}-{i}", NOW + i + t * 0.0001, 1, None, None, f"bulk-{t}", "control", "STEP_RESULT", "neutral",
                         "agent", "none", "rule", "{}", "{}"))
    for i in range(450):                                                    # one thread past the per-thread cap
        rows.append((f"big-{i}", NOW + 500 + i * 0.001, 1, None, None, "big-thread", "control", "STEP_RESULT", "neutral",
                     "agent", "none", "rule", "{}", "{}"))
    con.executemany("INSERT INTO memory_events (event_id, ts, schema_version, episode_id, step_index, thread_id, family, label,"
                    " valence, actor, evidence, label_source, links, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    seen = _run_snapshot_traced(snap_env, monkeypatch, "?threads=100000&events=100000")
    assert any(re.search(r"FROM memory_events .*ORDER BY ts DESC LIMIT 12000$", s) for _, s in seen)   # events <= 12000 rows read
    d = _get(snap_env, "?threads=100000&events=100000")
    assert len(d["sessions"]) == 120                                        # threads <= 120
    assert len(d["events"]) <= 12000
    per_thread = {}
    for e in d["events"]:
        per_thread[e["session"]] = per_thread.get(e["session"], 0) + 1
    assert per_thread["big-thread"] == 400                                  # <= 400 per thread
    assert max(per_thread.values()) <= 400
    # a small request is honoured, a zero or negative one is raised to 1
    small = _get(snap_env, "?threads=2&events=500")
    assert len(small["sessions"]) == 2 and len(small["events"]) <= 500
    assert len(_get(snap_env, "?threads=5&events=5")["events"]) <= 5
    assert len(_get(snap_env, "?threads=0&events=0")["sessions"]) == 1
    assert d["meta"]["counts"]["events"] == 7 + 13000 + 450                 # counts are exact, lists are bounded
    for key in ("landmarks", "episodes", "artifacts", "nodes", "quorum", "recalls"):
        assert len(d[key]) <= {"landmarks": 400, "episodes": 300, "artifacts": 80, "nodes": 600, "quorum": 80, "recalls": 60}[key]


# ── read-only ───────────────────────────────────────────────────────────────────────────────────
def test_snapshot_is_read_only_and_leaves_the_stores_untouched(snap_env, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def spy(database, *a, **kw):
        opened.append((str(database), kw.get("uri", False)))
        return real_connect(database, *a, **kw)

    monkeypatch.setattr(snap_env.sq.sqlite3, "connect", spy)
    before = (_file_digest(snap_env.mem), _file_digest(Path(snap_env.cs._DB_PATH)))
    for q in ("", "?include_eval=true", "?threads=1&events=1"):
        _get(snap_env, q)
    after = (_file_digest(snap_env.mem), _file_digest(Path(snap_env.cs._DB_PATH)))
    assert opened and all(uri and database.endswith("?mode=ro") for database, uri in opened), opened
    assert before == after, "the snapshot changed a store"


def test_snapshot_handler_is_a_worker_thread_function_and_a_missing_store_is_503(snap_env, tmp_path, monkeypatch):
    import inspect

    route = next(r for r in snap_env.api.router.routes if r.path == "/api/memory/snapshot")
    assert not inspect.iscoroutinefunction(route.endpoint)
    monkeypatch.setattr(snap_env.sq, "memory_db_path", lambda: tmp_path / "nothing.db")
    r = snap_env.client.get(SNAP)
    assert r.status_code == 503 and r.json()["error"] == "the memory is resting" and r.json()["ref"]


# ── a store from before the optional tables existed ─────────────────────────────────────────────
def test_store_missing_optional_tables_still_answers(snap_env, tmp_path, monkeypatch):
    mini = tmp_path / "old_memory.db"
    con = sqlite3.connect(mini)
    con.executescript(MINIMAL_DDL)
    _chain(con, snap_env.ids["root"], 0, NOW, "only step")
    _ev(con, "e1", NOW, "GOAL_SET", snap_env.ids["root"], episode="T1", family="intent")
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, task_class, coordinate_cluster, traversal_sequence,"
                " cumulative_score, micro_abstract_text, created_at, tier) VALUES ('L1','c','[]','[]',0.5,'a claim',?, 'candidate')",
                (NOW,))
    con.commit()
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert not {"mycelium_sectors", "mycelium_pins", "mycelium_quorum_log", "caducean_trajectories", "episodes",
                "mycelium_landmark_edges", "mycelium_nodes", "mycelium_spaces", "document_data", "context_chunks"} & have
    monkeypatch.setattr(snap_env.sq, "memory_db_path", lambda: mini)
    d = _get(snap_env)
    _assert_shapes(d)
    assert d["meta"]["available"] == {"landmark_channel": False, "sectors": False, "landmark_sectors": False, "pins": False,
                                      "spaces": False, "node_channel": False, "quorum": False}
    assert [x["id"] for x in d["landmarks"]] == ["L1"] and len(d["sessions"]) == 1 and len(d["events"]) == 1
    for key in ("edges", "episodes", "artifacts", "sectors", "pins", "spaces", "nodes", "nodeEdges", "quorum", "recalls"):
        assert d[key] == [], key
    # an empty store answers too
    empty = tmp_path / "empty.db"
    con = sqlite3.connect(empty)
    con.executescript(MINIMAL_DDL)
    con.commit()
    con.close()
    monkeypatch.setattr(snap_env.sq, "memory_db_path", lambda: empty)
    d = _get(snap_env)
    _assert_shapes(d)
    assert d["sessions"] == [] and d["landmarks"] == [] and d["meta"]["counts"]["events"] == 0


# ── plans ───────────────────────────────────────────────────────────────────────────────────────
def _run_snapshot_traced(env, monkeypatch, query: str = "?include_eval=true"):
    seen: list[tuple[str, str]] = []
    orig = env.sq.read_only

    @contextlib.contextmanager
    def traced(path):
        with orig(path) as con:
            name = Path(path).name
            con.set_trace_callback(lambda s: seen.append((name, s)) if s.lstrip().upper().startswith(("SELECT", "WITH")) else None)
            yield con

    monkeypatch.setattr(env.sq, "read_only", traced)
    _get(env, query)
    return seen


def test_no_statement_scans_a_big_table_except_the_documented_domain_count(snap_env, monkeypatch):
    for with_indexes in (False, True):
        if with_indexes:
            con = sqlite3.connect(snap_env.mem)
            con.execute("CREATE INDEX idx_memory_events_thread_ts ON memory_events(thread_id, ts)")
            con.execute("CREATE INDEX idx_memory_chain_chain_id ON memory_chain(chain_id)")
            con.commit()
            con.close()
        for query in ("?include_eval=true", ""):
            seen = _run_snapshot_traced(snap_env, monkeypatch, query)
            assert any("memory_events" in s for _, s in seen) and any("memory_chain" in s for _, s in seen)
            con = sqlite3.connect(snap_env.mem)
            whole_table = []
            for db, sql in seen:
                if db != snap_env.mem.name:
                    continue
                for line in _plan_lines(con, sql):
                    m = re.match(r"SCAN (\w+)(?: USING (COVERING )?INDEX (\w+))?", line)
                    if not m or m.group(1) not in BIG_TABLES:
                        continue
                    indexed_and_bounded = m.group(3) is not None and (
                        "LIMIT" in sql.upper() or sql.lstrip().upper().startswith(("SELECT COUNT(*) FROM", "SELECT COUNT(DISTINCT")))
                    if m.group(2) or indexed_and_bounded:
                        continue
                    whole_table.append(" ".join(sql.split())[:90])
            con.close()
            # the ONE whole-table read: the topic-domain count (no index carries topic_domain), one per big table
            assert sorted(whole_table) == sorted(
                f"SELECT COALESCE(topic_domain, 'general'), COUNT(*) FROM {t} GROUP BY 1" for t in ("memory_chain", "memory_events")), \
                (with_indexes, query, whole_table)


def test_the_statements_that_would_scan_run_only_when_their_index_exists(snap_env, monkeypatch):
    absent = _run_snapshot_traced(snap_env, monkeypatch)
    assert not any("WHERE chain_id IN" in s for _, s in absent)
    assert not any("COUNT(DISTINCT thread_id)" in s for _, s in absent)
    con = sqlite3.connect(snap_env.mem)
    con.execute("CREATE INDEX idx_memory_events_thread_ts ON memory_events(thread_id, ts)")
    con.execute("CREATE INDEX idx_memory_chain_chain_id ON memory_chain(chain_id)")
    con.commit()
    present = _run_snapshot_traced(snap_env, monkeypatch)
    assert any("WHERE chain_id IN" in s for _, s in present) and any("COUNT(DISTINCT thread_id)" in s for _, s in present)
    plans = {kind: " | ".join(_plan_lines(con, sql)) for kind, sql in
             (("chain", next(s for _, s in present if "WHERE chain_id IN" in s)),
              ("distinct", "SELECT COUNT(DISTINCT thread_id) FROM memory_events"),
              ("eval", "SELECT COUNT(*) FROM memory_events WHERE thread_id >= 'eval-' AND thread_id < 'eval.'"),
              ("recall", next(s for _, s in present if "label IN (" in s and "RECALL_DELIVERED" in s)))}
    con.close()
    assert "idx_memory_chain_chain_id" in plans["chain"] and "SCAN memory_chain" not in plans["chain"]
    assert "COVERING INDEX idx_memory_events_thread_ts" in plans["distinct"]
    assert "idx_memory_events_thread_ts" in plans["eval"] and "SEARCH" in plans["eval"]
    assert "idx_memory_events_label" in plans["recall"]                     # family + label: not a ts-order scan of the table


def test_the_recall_read_streams_the_newest_turns_without_a_sort(snap_env, monkeypatch):
    """2026-10-26: the recall read took every RECALL_* row (12.4k live) and sorted it to keep 60 turns - 156 s cold on
    the hard disk after a restart. With idx_memory_events_label_ts it reads the newest deliveries in time order and
    stops at SNAPSHOT_RECALL_TURNS turns; outcomes are read by turn."""
    from backend.memory.memory_events import _SCHEMA

    assert "idx_memory_events_label_ts ON memory_events(family, label, ts)" in _SCHEMA   # new stores get the index
    con = sqlite3.connect(snap_env.mem)
    con.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_label_ts ON memory_events(family, label, ts)")
    con.commit()
    present = _run_snapshot_traced(snap_env, monkeypatch)
    delivered = next(s for _, s in present if "label IN (" in s and "RECALL_DELIVERED" in s)
    plan = " | ".join(_plan_lines(con, delivered))
    con.close()
    assert "idx_memory_events_label_ts" in plan and "TEMP B-TREE" not in plan, plan
    assert "RECALL_HELPED" not in delivered                                # outcomes come from a per-turn read


# ── the exporter is the same function ───────────────────────────────────────────────────────────
def test_exporter_cli_writes_the_same_json_as_the_endpoint(snap_env, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("export_snapshot_under_test", REPO / "docs/Design/Memory-Cortex/export_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    out = tmp_path / "memory-snapshot.js"
    monkeypatch.setattr(mod, "OUT", out)
    # --db names the store; the chat store is its sibling conversations.db (the fixture puts both in tmp_path)
    assert Path(snap_env.cs._DB_PATH).parent == snap_env.mem.parent and Path(snap_env.cs._DB_PATH).name == "conversations.db"
    for flags, query in (([], "?include_eval=true"), (["--no-eval"], ""), (["--no-eval", "--threads", "1", "--events", "3"], "?threads=1&events=3")):
        monkeypatch.setattr(sys, "argv", ["export_snapshot.py", "--db", str(snap_env.mem), *flags])
        assert mod.main() == 0
        text = out.read_text(encoding="utf-8")
        assert text.startswith("window.IRIS_MEMORY = ") and text.rstrip().endswith(";")
        exported = json.loads(text[len("window.IRIS_MEMORY = "):].rstrip().rstrip(";"))
        served = _get(snap_env, query)
        for d in (exported, served):
            d["meta"].pop("generated")                                       # the one field that is the moment of the call
        assert exported == served, flags
