"""Memory surface read API - the contract (MEMORY-SURFACE-BUILD.md phase 0).

  GET /api/memory/{overview, claims, claims/{id}, threads, strand/{id}, turn/{conv}/{turn}, oracle}

What this pins, against a TEMP store built here (schema = the live schema, rows = a small cast):
  * every endpoint answers with the documented shape;
  * every list is bounded by its limit;
  * the handlers open ONLY read-only connections (and a write through one raises; the store file is
    byte-identical after every endpoint ran);
  * an unknown id is a 404;
  * a store that lacks the optional tables (sectors, pins, quorum log, trajectories, ...) still answers;
  * no statement scans a big table (memory_events, memory_chain, context_chunks): the plan of every statement
    the handlers ran is read from the store and checked;
  * the chain-ref lookup (no index on memory_chain.chain_id today) is NOT run while the index is absent, and
    IS run - and resolves refs - once it exists.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import re
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = time.time()
BIG_TABLES = ("memory_events", "memory_chain", "context_chunks")

# The live schema (data/memory.db, 2026-10-21) for the tables the surface reads, indexes included.
MEMORY_DDL = """
CREATE TABLE memory_events (event_id TEXT PRIMARY KEY, ts REAL NOT NULL, schema_version INTEGER NOT NULL,
  episode_id TEXT, step_index TEXT, thread_id TEXT, family TEXT, label TEXT NOT NULL, valence TEXT, actor TEXT,
  evidence TEXT NOT NULL, cause_key TEXT, outcome_key TEXT, trigger TEXT, exec_domain TEXT, topic_domain TEXT,
  label_source TEXT NOT NULL, label_confidence REAL, sigma_from TEXT, sigma_to TEXT, hash_signature TEXT,
  hash_scheme INTEGER, action_signature TEXT, cost TEXT, links TEXT, payload TEXT, hex_bin TEXT);
CREATE INDEX idx_memory_events_episode ON memory_events(episode_id, ts);
CREATE INDEX idx_memory_events_hash ON memory_events(hash_signature);
CREATE INDEX idx_memory_events_label ON memory_events(family, label);
CREATE INDEX idx_memory_events_ts ON memory_events(ts);
CREATE TABLE memory_chain (entry_id TEXT DEFAULT NULL, thread_id TEXT NOT NULL, session_id TEXT DEFAULT NULL,
  sequence INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT DEFAULT '{}',
  session_ts REAL DEFAULT NULL, result TEXT DEFAULT NULL, distilled INTEGER DEFAULT 0, created_at REAL NOT NULL,
  chain_id TEXT, coords_from TEXT, coords_to TEXT, nbl_outcome TEXT, insight TEXT, file_path TEXT, landmark_id TEXT,
  stale INTEGER DEFAULT 0, mediator TEXT, mediator_source TEXT, node_type TEXT, topic_domain TEXT,
  execution_domain TEXT, PRIMARY KEY (thread_id, sequence));
CREATE INDEX idx_memory_chain_created ON memory_chain(created_at);
CREATE INDEX idx_memory_chain_session ON memory_chain(session_id);
CREATE INDEX idx_memory_chain_thread ON memory_chain(thread_id, created_at DESC);
CREATE TABLE mycelium_landmarks (landmark_id TEXT PRIMARY KEY, label TEXT, task_class TEXT NOT NULL,
  coordinate_cluster TEXT NOT NULL, traversal_sequence TEXT NOT NULL, cumulative_score REAL NOT NULL,
  micro_abstract BLOB, micro_abstract_text TEXT, activation_count INTEGER DEFAULT 0, is_permanent INTEGER DEFAULT 0,
  conversation_ref TEXT, absorbed INTEGER, created_at REAL NOT NULL, last_activated REAL,
  tier TEXT DEFAULT 'candidate', evidence TEXT DEFAULT '[]', depends_on TEXT DEFAULT '[]', falsify_if TEXT,
  last_verified REAL, contradictions INTEGER DEFAULT 0);
CREATE INDEX idx_landmarks_chart_origin ON mycelium_landmarks(activation_count, landmark_id) WHERE absorbed IS NULL;
CREATE TABLE mycelium_landmark_edges (edge_id TEXT PRIMARY KEY, from_landmark_id TEXT NOT NULL,
  to_landmark_id TEXT NOT NULL, score REAL NOT NULL DEFAULT 0.5, edge_type TEXT NOT NULL,
  traversal_count INTEGER DEFAULT 0, hit_count INTEGER DEFAULT 0, miss_count INTEGER DEFAULT 0,
  created_at REAL NOT NULL, last_traversed REAL, last_decayed_at REAL, UNIQUE(from_landmark_id, to_landmark_id));
CREATE INDEX idx_landmark_edges_from ON mycelium_landmark_edges(from_landmark_id);
CREATE TABLE mycelium_landmark_merges (merge_id TEXT PRIMARY KEY, survivor_id TEXT NOT NULL, absorbed_id TEXT NOT NULL,
  overlap_score REAL NOT NULL, pre_merge_score_s REAL NOT NULL, pre_merge_score_a REAL NOT NULL,
  post_merge_score REAL NOT NULL, created_at REAL NOT NULL);
CREATE INDEX idx_merges_survivor ON mycelium_landmark_merges(survivor_id);
CREATE TABLE mycelium_sectors (sector_key TEXT PRIMARY KEY, parent_key TEXT, depth INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate', alias_of TEXT, born_from TEXT, members INTEGER DEFAULT 0,
  outside_evidence INTEGER DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE mycelium_landmark_sectors (landmark_id TEXT NOT NULL, sector_key TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0, source TEXT NOT NULL, created_at REAL NOT NULL,
  PRIMARY KEY (landmark_id, sector_key));
CREATE INDEX idx_landmark_sectors_sector ON mycelium_landmark_sectors(sector_key);
CREATE TABLE mycelium_episode_index (idx_id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, session_id TEXT NOT NULL,
  node_ids TEXT NOT NULL, space_ids TEXT NOT NULL, landmark_id TEXT, coordinate_hash TEXT NOT NULL,
  source_channel INTEGER, created_at REAL NOT NULL);
CREATE INDEX idx_epindex_landmark ON mycelium_episode_index(landmark_id);
CREATE TABLE mycelium_quorum_log (id INTEGER PRIMARY KEY, ts REAL NOT NULL, session_id TEXT, signal_type TEXT NOT NULL,
  weight REAL, threat_after REAL, shadow INTEGER DEFAULT 0, detail TEXT);
CREATE INDEX idx_quorum_log_ts ON mycelium_quorum_log(ts);
CREATE TABLE mycelium_pins (pin_id TEXT PRIMARY KEY, title TEXT NOT NULL, pin_type TEXT DEFAULT 'note', content TEXT,
  tags TEXT DEFAULT '[]', file_refs TEXT DEFAULT '[]', image_refs TEXT DEFAULT '[]', url_refs TEXT DEFAULT '[]',
  project_id TEXT, origin_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL, is_permanent INTEGER DEFAULT 0);
CREATE TABLE episodes (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, task_summary TEXT NOT NULL, full_content TEXT,
  tool_sequence TEXT, outcome_score REAL DEFAULT 0.0, outcome_type TEXT NOT NULL, failure_reason TEXT,
  user_corrected INTEGER DEFAULT 0, user_confirmed INTEGER DEFAULT 0, duration_ms INTEGER DEFAULT 0,
  tokens_used INTEGER DEFAULT 0, model_id TEXT DEFAULT '', source_channel TEXT DEFAULT 'websocket',
  node_id TEXT DEFAULT 'local', origin TEXT DEFAULT 'local', embedding BLOB, timestamp TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX idx_ep_session ON episodes(session_id);
CREATE TABLE caducean_trajectories (id INTEGER PRIMARY KEY, ts REAL, session_id TEXT, step_num INTEGER, x REAL, y REAL,
  xi REAL, u REAL, action INTEGER, outcome TEXT, eml_after REAL);
CREATE INDEX idx_ct_session ON caducean_trajectories(session_id);
CREATE TABLE caducean_session_exits (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id TEXT, domain TEXT,
  natural_exit INTEGER, route_score REAL, drift REAL, conversation_id TEXT);
CREATE INDEX idx_se_session ON caducean_session_exits(session_id);
"""

# a store from before sectors / pins / quorum / trajectories / edges / merges / episodes existed
MINIMAL_DDL = ";\n".join(s for s in MEMORY_DDL.split(";\n") if re.search(
    r"CREATE (TABLE|INDEX) (memory_events|memory_chain|mycelium_landmarks|idx_memory_|idx_landmarks_)", s)) + ";"


def _ev(con, eid, ts, label, thread, episode=None, step=None, family="memory", links=None, payload=None):
    con.execute("INSERT INTO memory_events (event_id, ts, schema_version, episode_id, step_index, thread_id, family, label,"
                " valence, actor, evidence, label_source, links, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, ts, 1, episode, step, thread, family, label, "neutral", "agent", "none", "rule",
                 json.dumps(links or {}), json.dumps(payload or {})))


def _chain(con, thread, seq, ts, insight="", cid=None, tool="read_file:x"):
    con.execute("INSERT INTO memory_chain (thread_id, sequence, role, content, created_at, chain_id, insight, mediator, result,"
                " node_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (thread, seq, "agent", "c" * 50, ts, cid, insight, tool, "ok", "step"))


def _seed_memory(path: Path, chat_ids: dict) -> dict:
    con = sqlite3.connect(path)
    con.executescript(MEMORY_DDL)
    r1, s1, ev_chat = chat_ids["root"], chat_ids["strand"], chat_ids["eval_root"]
    t0 = NOW - 3600
    # claims: C_LIVE proven in 'web/search'; C_CAND learning in 'general'; C_SURV survivor of C_MERGED; C_GONE dissolved
    lm = [("C_LIVE", "landmark", None, "Open the site and read the version", "web/search", t0),
          ("C_CAND", "candidate", None, "Prefer small diffs", None, t0 + 5),
          ("C_SURV", "landmark", None, "Use the tests as the final word", None, t0 + 9),
          ("C_MERGED", "candidate", 1, "Tests decide", None, t0 + 1),
          ("C_GONE", "candidate", 1, "Stale claim", None, t0 + 2)]
    for lid, tier, absorbed, text, _sec, born in lm:
        ev = json.dumps([{"kind": "task_complete", "at": born, "session": r1}, {"kind": "test_pass", "at": born + 1, "session": r1},
                         {"kind": "mystery", "at": born + 2}] + [{"kind": "recurrence", "at": born + i} for i in range(10)])
        con.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
                    " cumulative_score, micro_abstract_text, activation_count, conversation_ref, absorbed, created_at, tier,"
                    " evidence, falsify_if) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (lid, lid.lower(), "task_x", "[]", "[]", 0.6, text, 3, r1, absorbed, born, tier, ev,
                     "dissolved: no_credibility" if lid == "C_GONE" else None))
    con.execute("INSERT INTO mycelium_landmark_merges VALUES ('m1','C_SURV','C_MERGED',1.0,0.8,0.7,0.9,?)", (t0 + 20,))
    con.execute("INSERT INTO mycelium_landmark_edges (edge_id, from_landmark_id, to_landmark_id, edge_type, created_at)"
                " VALUES ('e1','C_LIVE','C_CAND','similarity',?)", (t0,))
    con.execute("INSERT INTO mycelium_sectors (sector_key, parent_key, status, members, created_at, updated_at)"
                " VALUES ('web', NULL, 'proven', 0, ?, ?), ('general', NULL, 'proven', 0, ?, ?),"
                " ('web/search', 'web', 'candidate', 4, ?, ?)", (t0, t0, t0, t0, t0, t0))
    con.execute("INSERT INTO mycelium_landmark_sectors VALUES ('C_LIVE','web/search',1.0,'t',?)", (t0,))
    con.execute("INSERT INTO mycelium_episode_index VALUES ('i1','ep-a',?,'[]','[]','C_LIVE','h',3,?)", (r1, t0 + 3))
    con.execute("INSERT INTO mycelium_quorum_log (ts, signal_type, shadow) VALUES (?, 'update_velocity_anomaly', 1)", (t0,))
    con.execute("INSERT INTO mycelium_pins (pin_id, title, project_id, created_at, updated_at, tags)"
                " VALUES ('p1','Pinned note','proj-1',?,?,'[\"held\"]')", (t0, t0))
    # steps (chain): chat root + strand + eval root + eval thread + an outside (system) thread
    for i in range(3):
        _chain(con, r1, i, t0 + 10 + i, f"step {i} of the root", cid=f"chain-r1-{i}")
    _chain(con, s1, 0, t0 + 50, "strand step", cid="chain-s1-0")
    _chain(con, ev_chat, 0, t0 + 60, "eval chat step")
    _chain(con, "eval-c1_thing-abc123", 0, t0 + 70, "eval step")
    _chain(con, "eval-c1_thing-abc123", 1, t0 + 71, "eval step 2")
    _chain(con, "sys_test_thread", 0, t0 + 80, "system step")
    # events: root turn T1 (a goal, a recall delivered + verdict naming chain refs), strand moment
    _ev(con, "e-goal", t0 + 10, "GOAL_SET", r1, episode="T1", family="intent")
    _ev(con, "e-rd", t0 + 11, "RECALL_DELIVERED", r1, episode="T1", step="s1", links={"recall_trace_id": "rt-1"},
        payload={"source": "neighbors", "refs": ["chain-r1-0", "chain-r1-1", "not-in-chain"]})
    _ev(con, "e-rh", t0 + 12, "RECALL_HELPED", r1, episode="T1", step="s1", links={"recall_trace_id": "rt-1"})
    _ev(con, "e-prom", t0 + 13, "LANDMARK_PROMOTED", r1, episode="T1", links={"landmark_id": "C_LIVE"})
    _ev(con, "e-s1", t0 + 50, "GOAL_SET", s1, episode="T2", family="intent")
    _ev(con, "e-eval", t0 + 70, "GOAL_SET", "eval-c1_thing-abc123", episode="eval-c1_thing-abc123:xyz", family="intent")
    _ev(con, "e-clean", t0 + 90, "LANDMARK_DISSOLVED", "maintenance", family="memory")
    con.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_type, tool_sequence, timestamp)"
                " VALUES ('ep1', ?, 'did a thing', 'success', '[{\"tool\":\"read_file\"}]', '2026-10-21 10:00:00')", (r1,))
    for i in range(5):
        con.execute("INSERT INTO caducean_trajectories (ts, session_id, step_num, x, y, xi, u) VALUES (?,?,?,?,?,?,?)",
                    (t0 + i, r1, i, 0.1 * i, 0.2, 0.3, 0.4))
    con.execute("INSERT INTO caducean_session_exits (ts, session_id, natural_exit, drift, conversation_id) VALUES (?,?,1,0.0,?)",
                (t0, r1, r1))
    con.commit()
    con.close()
    return {"t0": t0}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A real conversation store (temp file) + a temp memory store, behind the real router."""
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as cs

    importlib.reload(cs)
    root = cs.create_conversation(title="Plan the release")["id"]
    cs.add_message(root, role="user", text="Please plan the release. " + "x" * 400)
    cs.add_message(root, role="assistant", text="Plan: " + "y" * 400, turn_id="T1")
    strand = cs.create_strand(root, "side check")["id"]
    cs.add_message(strand, role="user", text="check the thing")
    eval_root = cs.create_conversation(title="[eval] c1_thing")["id"]
    ids = {"root": root, "strand": strand, "eval_root": eval_root}
    mem = tmp_path / "memory.db"
    info = _seed_memory(mem, ids)

    from backend.memory import surface_queries as sq
    import backend.api.memory as api

    monkeypatch.setattr(sq, "memory_db_path", lambda: mem)
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    return type("Env", (), {"client": client, "sq": sq, "api": api, "mem": mem, "ids": ids, "cs": cs, **info})


def _file_digest(p: Path) -> str:
    """The LOGICAL content of a store (every row of every table): a write through any path changes it, WAL or not."""
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


def _all_paths(e) -> list[str]:
    r, s, ev = e.ids["root"], e.ids["strand"], e.ids["eval_root"]
    return ["/api/memory/overview", "/api/memory/claims", "/api/memory/claims/C_LIVE", "/api/memory/claims/C_MERGED",
            "/api/memory/threads", "/api/memory/threads?include_eval=true", f"/api/memory/strand/{r}",
            f"/api/memory/strand/{s}", f"/api/memory/strand/{ev}", f"/api/memory/turn/{r}/T1", "/api/memory/oracle"]


# ── shapes ──────────────────────────────────────────────────────────────────────────────────────
def test_overview_shape_and_values(env):
    d = env.client.get("/api/memory/overview").json()
    assert set(d) >= {"generated", "claims", "territories", "counts", "eval_share", "last_integrity_pass",
                      "last_quorum_signal", "available"}
    assert d["claims"] == {"live": {"landmark": 2, "candidate": 1}, "absorbed": {"candidate": 2}}
    c = d["counts"]
    assert c["claims_live"] == 3 and c["claims_absorbed"] == 2
    assert c["events"] == 7 and c["steps"] == 8
    assert c["threads"] == 2 and c["strands"] == 1 and c["threads_eval"] == 1
    terr = {t["key"]: t for t in d["territories"]}
    assert terr["web"]["claims"] == 1 and terr["web"]["proven"] == 1 and terr["web"]["proven_share"] == 1.0
    assert terr["general"]["claims"] == 2 and terr["general"]["learning"] == 1
    assert terr["web"]["children"][0]["key"] == "web/search" and terr["web"]["children"][0]["claims"] == 1
    assert d["last_integrity_pass"]["label"] == "LANDMARK_DISSOLVED"
    assert d["last_quorum_signal"]["signal"] == "update_velocity_anomaly"
    assert d["eval_share"]["total"] == 8 and d["eval_share"]["eval"] == 2


def test_claims_list_shape_bounds_and_filters(env):
    d = env.client.get("/api/memory/claims").json()
    assert {c["id"] for c in d["claims"]} == {"C_LIVE", "C_CAND", "C_SURV"}   # absorbed claims are not live
    card = next(c for c in d["claims"] if c["id"] == "C_LIVE")
    assert set(card) >= {"id", "claim", "cls", "tier", "permanent", "evidence", "evidence_counts", "activations",
                         "contradictions", "last_activated", "last_verified", "born", "session", "domain", "sector",
                         "channel", "absorbed"}
    assert card["domain"] == "web" and card["sector"] == "web/search" and card["tier"] == "landmark"
    # evidence in the closed alphabet, at most 4 dated entries per kind (the exporter's card)
    assert card["evidence_counts"]["recurrence"] == 10 and card["evidence_counts"]["claim"] == 1   # 'mystery' -> claim
    assert sum(1 for e in card["evidence"] if e["kind"] == "recurrence") == 4
    assert {e["kind"] for e in card["evidence"]} <= {"completion", "test", "recurrence", "claim"}
    # bounds and filters
    assert len(env.client.get("/api/memory/claims?limit=2").json()["claims"]) == 2
    assert len(env.client.get("/api/memory/claims?limit=0").json()["claims"]) == 1      # clamped up to 1
    assert env.client.get("/api/memory/claims?limit=100000").json()["limit"] == env.sq.CLAIMS_MAX
    assert [c["id"] for c in env.client.get("/api/memory/claims?territory=web").json()["claims"]] == ["C_LIVE"]
    assert {c["id"] for c in env.client.get("/api/memory/claims?territory=general").json()["claims"]} == {"C_CAND", "C_SURV"}
    assert [c["id"] for c in env.client.get("/api/memory/claims?tier=learning").json()["claims"]] == ["C_CAND"]
    assert {c["id"] for c in env.client.get("/api/memory/claims?tier=proven").json()["claims"]} == {"C_LIVE", "C_SURV"}
    assert env.client.get("/api/memory/claims?tier=bogus").status_code == 400
    assert env.client.get("/api/memory/claims?territory=nowhere").json()["claims"] == []


def test_claim_detail_live_absorbed_and_unknown(env):
    live = env.client.get("/api/memory/claims/C_LIVE").json()
    assert live["state"] == "live" and live["survivor"] is None
    assert [e["dir"] for e in live["edges"]] == ["out"] and live["edges"][0]["other"]["id"] == "C_CAND"
    assert live["observed_in"][0]["episode"] == "ep-a" and live["observed_in"][0]["channel"] == 3
    assert len(live["evidence"]) <= env.sq.EVIDENCE_SHOWN and len(live["evidence"]) == 13   # detail keeps every entry
    # absorbed into a survivor: the merge log is followed
    merged = env.client.get("/api/memory/claims/C_MERGED").json()
    assert merged["absorbed"] is True and merged["state"] == "merged"
    assert merged["survivor"]["id"] == "C_SURV" and merged["merge_path"] == ["C_SURV"]
    assert env.client.get("/api/memory/claims/C_SURV").json()["merged_from"] == ["C_MERGED"]
    # absorbed with no survivor: dissolved, with the reason Kyudo wrote
    gone = env.client.get("/api/memory/claims/C_GONE").json()
    assert gone["state"] == "dissolved" and gone["survivor"] is None and gone["cleaned_reason"] == "dissolved: no_credibility"
    assert env.client.get("/api/memory/claims/nope").status_code == 404


def test_threads_shape_strands_outside_chat_and_eval_toggle(env):
    d = env.client.get("/api/memory/threads").json()
    assert set(d) >= {"threads", "limit", "total", "eval_hidden", "outside_chat"}
    assert [t["id"] for t in d["threads"]] == [env.ids["root"]]            # the eval chat is hidden ...
    assert d["total"] == 2 and d["eval_hidden"] == 1                       # ... but counted
    t = d["threads"][0]
    assert t["title"] == "Plan the release" and t["strand_count"] == 2
    assert [s["id"] for s in t["strands"]] == [env.ids["root"], env.ids["strand"]] and t["strands"][0]["root"] is True
    root_s, strand_s = t["strands"]
    assert root_s["steps"] == 3 and root_s["messages"] == 2 and root_s["last_activity"] > 0
    assert strand_s["steps"] == 1 and strand_s["parent"] == env.ids["root"]
    oc = d["outside_chat"]
    assert [i["id"] for i in oc["items"]] == ["sys_test_thread"] and oc["count"] == 1 and oc["eval_included"] is False
    # include_eval: the evaluation chat and the evaluation run's memory thread appear
    d2 = env.client.get("/api/memory/threads?include_eval=true").json()
    assert {x["id"] for x in d2["threads"]} == {env.ids["root"], env.ids["eval_root"]}
    assert next(x for x in d2["threads"] if x["id"] == env.ids["eval_root"])["eval"] is True
    assert {i["id"]: i["source"] for i in d2["outside_chat"]["items"]} == {
        "sys_test_thread": "outside", "eval-c1_thing-abc123": "evaluation"}
    assert d2["eval_hidden"] == 0
    assert len(env.client.get("/api/memory/threads?limit=1&include_eval=true").json()["threads"]) == 1


def test_strand_shape_previews_and_unknown(env):
    r = env.ids["root"]
    d = env.client.get(f"/api/memory/strand/{r}").json()
    assert set(d) >= {"id", "objective", "in_chat", "eval", "started", "ended", "exit", "activity", "traj", "events",
                      "episodes", "messages", "strands", "pins"}
    assert d["objective"] == "Plan the release" and d["in_chat"] is True and d["eval"] is False
    assert [m["role"] for m in d["messages"]] == ["user", "iris"]
    assert all(len(m["text"]) <= env.sq.PREVIEW_MESSAGE for m in d["messages"]) and d["messages"][0]["len"] > 400
    assert [e["label"] for e in d["events"]] == ["LANDMARK_PROMOTED", "RECALL_HELPED", "RECALL_DELIVERED", "GOAL_SET"]
    assert {e["session"] for e in d["events"]} == {r}                      # no event of another thread leaks in
    assert d["events"][0]["landmark"] == "C_LIVE"
    assert len(d["traj"]) == 5 and set(d["traj"][0]) == {"x", "y", "xi", "u"}
    assert d["episodes"][0]["id"] == "ep1" and d["episodes"][0]["tools"] == ["read_file"]
    assert [s["id"] for s in d["strands"]] == [env.ids["strand"]]
    assert d["activity"]["steps"] == 3 and d["activity"]["events_partial"] is False
    assert d["exit"] in ("natural", "live", "drift")
    # a strand of the thread: its own events only; an evaluation thread is flagged
    s = env.client.get(f"/api/memory/strand/{env.ids['strand']}").json()
    assert [e["id"] for e in s["events"]] == ["e-s1"] and s["parent"] == r
    ev = env.client.get("/api/memory/strand/eval-c1_thing-abc123").json()
    assert ev["eval"] is True and ev["in_chat"] is False and [e["id"] for e in ev["events"]] == ["e-eval"]
    assert env.client.get("/api/memory/strand/nope").status_code == 404


def test_strand_pins_come_from_the_conversation_project(env):
    con = sqlite3.connect(env.cs._DB_PATH)
    con.execute("UPDATE conversations SET project_id = 'proj-1' WHERE id = ?", (env.ids["root"],))
    con.commit()
    con.close()
    d = env.client.get(f"/api/memory/strand/{env.ids['root']}").json()
    assert [p["id"] for p in d["pins"]] == ["p1"] and d["pins"][0]["held"] is True


def test_strand_events_bounded(env):
    con = sqlite3.connect(env.mem)
    for i in range(env.sq.EVENTS_CAP + 50):
        _ev(con, f"bulk-{i}", env.t0 + 10 + i * 0.001, "STEP_RESULT", env.ids["root"], family="control")
    con.commit()
    con.close()
    d = env.client.get(f"/api/memory/strand/{env.ids['root']}").json()
    assert len(d["events"]) == env.sq.EVENTS_CAP


def test_turn_recalls_moments_and_refs_follow_the_index(env):
    r = env.ids["root"]
    d = env.client.get(f"/api/memory/turn/{r}/T1").json()
    assert set(d) >= {"conversation", "turn", "recalls", "moments", "refs_resolved"}
    assert [m["label"] for m in d["moments"]] == ["GOAL_SET", "LANDMARK_PROMOTED"]
    (rec,) = d["recalls"]
    assert rec["trace"] == "rt-1" and rec["outcome"] == "helped" and rec["source"] == "neighbors" and rec["step"] == "s1"
    assert [x["id"] for x in rec["refs"]] == ["chain-r1-0", "chain-r1-1", "not-in-chain"]
    # memory_chain has NO index on chain_id (live, today): the refs stay unresolved and the scan never runs
    assert d["refs_resolved"] is False and all(x["resolved"] is False for x in rec["refs"])
    # with the index, the same endpoint resolves them (thread, insight preview, tool, result)
    con = sqlite3.connect(env.mem)
    con.execute("CREATE INDEX idx_memory_chain_chain_id ON memory_chain(chain_id)")
    con.commit()
    con.close()
    d = env.client.get(f"/api/memory/turn/{r}/T1").json()
    got = {x["id"]: x for x in d["recalls"][0]["refs"]}
    assert d["refs_resolved"] is True
    assert got["chain-r1-0"]["resolved"] is True and got["chain-r1-0"]["session"] == r
    assert got["chain-r1-0"]["did"] == "step 0 of the root" and got["chain-r1-0"]["tool"] == "read_file"
    assert got["not-in-chain"]["resolved"] is False                           # a dangling ref is shown as one
    # an evaluation turn is addressed by the bare id as well as '<thread>:<id>'
    assert env.client.get("/api/memory/turn/eval-c1_thing-abc123/xyz").status_code == 200
    # a wrong thread never borrows another thread's turn; unknown turn is a 404
    assert env.client.get("/api/memory/turn/other-thread/T1").status_code == 404
    assert env.client.get(f"/api/memory/turn/{r}/nope").status_code == 404


def test_oracle_joins_bar_record_to_calibration(env, tmp_path, monkeypatch):
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "consumer_bar_record.json").write_text(json.dumps({
        "alpha": {"consumer_id": "alpha", "status": "enforced", "rows": 900, "ece": 0.04, "precision": 0.93, "gap": "",
                  "config": {"backend_id": "eng|1"}},
        "beta": {"consumer_id": "beta", "status": "shadow", "rows": 12, "ece": None, "precision": 0.0,
                 "gap": "distinct rows 12 < 100", "config": {"backend_id": "eng|1"}}}), encoding="utf-8")
    (bench / "oracle_calibration.json").write_text(json.dumps({
        "eng|1": {"alpha": {"threshold": 0.8, "oof": {"auroc": 0.77, "ece": 0.02}, "fitted_at": "2026-10-21T00:00:00+00:00"}}}),
        encoding="utf-8")
    monkeypatch.setattr(env.api, "_BENCH", bench)
    d = env.client.get("/api/memory/oracle").json()
    assert set(d) == {"consumers", "states"} and d["states"] == {"enforced": 1, "shadow": 1}
    a, b = d["consumers"]
    assert (a["consumer"], a["state"], a["rows"], a["auroc"], a["ece"], a["precision"], a["threshold"], a["gap"]) == \
           ("alpha", "enforced", 900, 0.77, 0.04, 0.93, 0.8, "")
    assert (b["consumer"], b["auroc"], b["threshold"], b["gap"]) == ("beta", None, None, "distinct rows 12 < 100")
    # missing files: an empty answer, not an error
    monkeypatch.setattr(env.api, "_BENCH", tmp_path / "nowhere")
    assert env.client.get("/api/memory/oracle").json() == {"consumers": [], "states": {}}


# ── read-only, no writes ────────────────────────────────────────────────────────────────────────
def test_connections_are_read_only_and_a_write_raises(env):
    with env.sq.read_only(env.mem) as con:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO mycelium_pins (pin_id, title, created_at, updated_at) VALUES ('x','x',0,0)")
        with pytest.raises(sqlite3.OperationalError):
            con.execute("CREATE TABLE sneaky (a)")
    with env.sq.read_only(env.cs._DB_PATH) as con:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM conversations")
    with pytest.raises(env.sq.StoreUnavailable):
        with env.sq.read_only(env.mem.with_name("absent.db")):
            pass


def test_every_handler_opens_only_read_only_connections_and_leaves_the_stores_untouched(env, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def spy(database, *a, **kw):
        opened.append((str(database), kw.get("uri", False)))
        return real_connect(database, *a, **kw)

    monkeypatch.setattr(env.sq.sqlite3, "connect", spy)
    before = (_file_digest(env.mem), _file_digest(Path(env.cs._DB_PATH)))
    for p in _all_paths(env):
        assert env.client.get(p).status_code == 200, p
    after = (_file_digest(env.mem), _file_digest(Path(env.cs._DB_PATH)))
    assert opened and all(uri and database.endswith("?mode=ro") for database, uri in opened), opened
    assert before == after, "an endpoint changed a store"


def test_handlers_are_worker_thread_functions_not_async(env):
    import inspect

    for route in env.api.router.routes:
        assert not inspect.iscoroutinefunction(route.endpoint), f"{route.path} would block the event loop"


# ── unknown ids, missing optional tables ────────────────────────────────────────────────────────
def test_unknown_ids_are_404(env):
    for p in ("/api/memory/claims/nope", "/api/memory/strand/nope", "/api/memory/turn/nope/nope",
              f"/api/memory/turn/{env.ids['root']}/nope"):
        r = env.client.get(p)
        assert r.status_code == 404 and r.json()["error"] == "not found", p


def test_store_missing_optional_tables_still_answers(env, tmp_path, monkeypatch):
    mini = tmp_path / "old_memory.db"
    con = sqlite3.connect(mini)
    con.executescript(MINIMAL_DDL)
    _chain(con, env.ids["root"], 0, NOW, "only step")
    _ev(con, "e1", NOW, "GOAL_SET", env.ids["root"], episode="T1", family="intent")
    con.execute("INSERT INTO mycelium_landmarks (landmark_id, task_class, coordinate_cluster, traversal_sequence,"
                " cumulative_score, micro_abstract_text, created_at, tier) VALUES ('L1','c','[]','[]',0.5,'a claim',?, 'candidate')",
                (NOW,))
    con.commit()
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert not {"mycelium_sectors", "mycelium_pins", "mycelium_quorum_log", "caducean_trajectories", "episodes",
                "mycelium_landmark_edges", "mycelium_landmark_merges", "mycelium_episode_index"} & have
    monkeypatch.setattr(env.sq, "memory_db_path", lambda: mini)
    r = env.ids["root"]
    for p in ("/api/memory/overview", "/api/memory/claims", "/api/memory/claims?territory=general", "/api/memory/claims/L1",
              "/api/memory/threads", f"/api/memory/strand/{r}", f"/api/memory/turn/{r}/T1"):
        resp = env.client.get(p)
        assert resp.status_code == 200, (p, resp.text)
    ov = env.client.get("/api/memory/overview").json()
    assert ov["available"]["sectors"] is False and ov["last_quorum_signal"] is None
    assert [t["key"] for t in ov["territories"]] == ["general"] and ov["territories"][0]["claims"] == 1
    assert env.client.get("/api/memory/claims/L1").json()["edges"] == []


def test_missing_store_is_a_resting_503_not_a_crash(env, tmp_path, monkeypatch):
    monkeypatch.setattr(env.sq, "memory_db_path", lambda: tmp_path / "nothing.db")
    for p in ("/api/memory/overview", "/api/memory/claims", "/api/memory/threads", "/api/memory/strand/x",
              "/api/memory/turn/a/b", "/api/memory/claims/x"):
        r = env.client.get(p)
        assert r.status_code == 503 and r.json()["error"] == "the memory is resting" and r.json()["ref"], p


def test_empty_memory_has_no_division_by_zero(env, tmp_path, monkeypatch):
    empty = tmp_path / "empty.db"
    con = sqlite3.connect(empty)
    con.executescript(MEMORY_DDL)
    con.commit()
    con.close()
    monkeypatch.setattr(env.sq, "memory_db_path", lambda: empty)
    ov = env.client.get("/api/memory/overview").json()
    assert ov["counts"]["claims_live"] == 0 and ov["eval_share"] == {"basis": "newest_steps", "eval": 0, "total": 0}
    assert all(t["proven_share"] is None for t in ov["territories"])         # nothing to share is null, not 0 and not NaN
    assert env.client.get("/api/memory/claims").json()["claims"] == []


# ── plans: no statement scans a big table ───────────────────────────────────────────────────────
def _plan_lines(con, sql):
    return [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql)]


def _run_all_traced(env, monkeypatch):
    seen: list[tuple[str, str]] = []
    orig = env.sq.read_only

    @contextlib.contextmanager
    def traced(path):
        with orig(path) as con:
            name = Path(path).name
            con.set_trace_callback(lambda s: seen.append((name, s)) if s.lstrip().upper().startswith(("SELECT", "WITH")) else None)
            yield con

    monkeypatch.setattr(env.sq, "read_only", traced)
    for p in _all_paths(env):
        assert env.client.get(p).status_code == 200, p
    return seen


def test_no_statement_scans_a_big_table(env, monkeypatch):
    seen = _run_all_traced(env, monkeypatch)
    assert any("memory_events" in s for _, s in seen) and any("memory_chain" in s for _, s in seen)
    con = sqlite3.connect(env.mem)
    bad = []
    for db, sql in seen:
        if db != env.mem.name:
            continue
        for line in _plan_lines(con, sql):
            m = re.match(r"SCAN (\w+)(?: USING (COVERING )?INDEX (\w+))?", line)
            if not m or m.group(1) not in BIG_TABLES:
                continue
            bounded = m.group(3) is not None and ("LIMIT" in sql.upper() or sql.lstrip().upper().startswith("SELECT COUNT(*) FROM"))
            if not bounded:
                bad.append((line, " ".join(sql.split())[:160]))
    assert not bad, bad
    # the unindexed chain-ref lookup WOULD scan: that is why it is gated, and it was not among the statements run
    chain_sql = env.sq.CHAIN_REFS_SQL.format(marks="'a','b'").replace("LIMIT ?", "LIMIT 5")
    assert any(re.match(r"SCAN memory_chain$", ln) for ln in _plan_lines(con, chain_sql))
    assert not any("WHERE chain_id IN" in s for _, s in seen)
    con.close()


def test_strand_events_use_the_thread_index_when_one_exists(env, monkeypatch):
    r = env.ids["root"]
    window = env.client.get(f"/api/memory/strand/{r}").json()
    con = sqlite3.connect(env.mem)
    con.execute("CREATE INDEX idx_memory_events_thread ON memory_events(thread_id, ts)")
    con.commit()
    con.close()
    seen = _run_all_traced(env, monkeypatch)
    direct = env.client.get(f"/api/memory/strand/{r}").json()
    assert direct["activity"]["events_how"] == "index" and window["activity"]["events_how"] == "window"
    assert [e["id"] for e in direct["events"]] == [e["id"] for e in window["events"]]
    assert any("WHERE thread_id = " in s for _, s in seen)


def test_window_scan_is_capped_and_says_partial(env, monkeypatch):
    monkeypatch.setattr(env.sq, "WINDOW_SCAN_CAP", 5)
    d = env.client.get(f"/api/memory/strand/{env.ids['root']}").json()
    assert d["activity"]["events_partial"] is True and d["activity"]["events_how"] == "window"
