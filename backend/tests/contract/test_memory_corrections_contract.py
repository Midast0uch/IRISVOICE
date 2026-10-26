"""Memory corrections v1 (claims only) - the contract (MEMORY-SURFACE-BUILD.md section 5).

  POST /api/memory/correct        {action: confirm | wrong | forget, target: "claim:<id>", reason?}
  POST /api/memory/correct/undo   {correction_id}
  GET  /api/memory/corrections?limit=

Driven through the real router (FastAPI TestClient) against a TEMP store with the live schema. What this pins:
  * each action writes what the section says: confirm = ONE user_confirm evidence entry (the tier re-derived by the
    existing rule), wrong = one contradiction (a proven claim drops to 'candidate' and Kyudo no longer counts it
    proven), forget = absorbed with "forgotten by you" (Kyudo's own absorb text);
  * every correction is USER evidence and types ONE memory event whose payload holds the prior state;
  * no landmark row is ever deleted (row counts, through every action and every undo);
  * a correction on a claim absorbed by a MERGE lands on its survivor (a chain too); a forgotten or dissolved claim
    is a 409; an unknown claim is a 404; a bad action or target is a 400;
  * undo restores the EXACT prior row (every column), refuses a second time and after 600 s, and removes exactly
    the evidence entry its confirm added (also when the list was full and the oldest entry fell off);
  * the list is newest first and marks undone corrections;
  * every SELECT on memory_events that the three endpoints run is a SEARCH, never a SCAN;
  * the live taps fire with the new tier.

The rest of the v1 table (pins and strands) is pinned below the claim cases, through the same endpoints:
  * unpin / hold / release / pin write THROUGH the pin store's own methods (delete / update / add + link; restore on
    undo), type one user-evidence event each, and an undo within 600 s puts the pin back exactly (every column, the
    link rows too); a pin too big for the event is refused, never dropped without a way back;
  * forget_learned absorbs only the claims whose ONLY evidence came from the strand, never deletes, types a marker
    that recall reads (forgotten_strands -> filtered_chain_recall / chain_timeline), and undo restores every column;
  * purge needs `confirm` == the strand id, rewrites TEXT only (every id, link, timestamp and count stays), changes
    nothing in other strands, says how many rows changed per table, and is refused for undo (409);
  * every SELECT the new corrections run on the big tables is a SEARCH, never a SCAN.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.ontology_recall import RecallFilters, chain_timeline, filtered_chain_recall
from backend.memory import corrections, strand_ids
from backend.memory.db import _plain_store_connection
from backend.memory.mycelium import integrity
from backend.memory.mycelium.landmark import LandmarkIndex
from backend.memory.pin_store import PinStore
from backend.tests.contract.test_memory_api_contract import MEMORY_DDL, _chain, _ev
from backend.utils import memory_live
from backend.utils.durability_queue import lane

T0 = time.time() - 7200


def _evidence(*pairs, n_filler=0):
    out = [{"kind": k, "ref": "r", "session": s, "at": T0 + i} for i, (k, s) in enumerate(pairs)]
    out += [{"kind": "recurrence", "ref": "f", "session": f"f{i}", "at": T0 + 100 + i} for i in range(n_filler)]
    return json.dumps(out)


LONG_FALSIFY = "a dependency changes (" + "x" * 900 + ")"      # longer than corrections._FALSIFY_KEEP

# id, text, tier, absorbed, evidence, falsify_if, contradictions
CAST = [
    ("L_PROV", "The release notes live in docs", "landmark", None,
     _evidence(("test_pass", "s1"), ("task_complete", "s2")), "a dependency changes (docs)", 0),
    ("L_CAND", "Prefer small diffs", "candidate", None, _evidence(("test_pass", "s1")), None, 0),
    ("L_FULL", "A claim with a full evidence list", "candidate", None,
     _evidence(("test_pass", "s1"), n_filler=49), None, 0),
    ("L_LONG", "A claim with a long reason", "landmark", None,
     _evidence(("test_pass", "s1"), ("task_complete", "s2")), LONG_FALSIFY, 2),
    ("L_SURV", "Use the tests as the final word " * 8, "landmark", None,
     _evidence(("test_pass", "s1"), ("task_complete", "s2")), None, 0),
    ("L_MID", "Tests decide", "candidate", 1, _evidence(("test_pass", "s1")), None, 0),
    ("L_OLD", "Tests rule", "candidate", 1, _evidence(("test_pass", "s1")), None, 0),
    ("L_GONE", "A stale claim", "candidate", 1, _evidence(("test_pass", "s1")), "dissolved: no_credibility", 0),
]
LIVE_IDS = ["L_PROV", "L_CAND", "L_FULL", "L_LONG", "L_SURV"]


def _seed(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA synchronous=OFF")        # a temp store: no fsync per statement (a hard disk spends seconds on them)
    con.executescript(MEMORY_DDL)
    for i, (lid, text, tier, absorbed, ev, falsify, contra) in enumerate(CAST):
        con.execute(
            "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
            " cumulative_score, micro_abstract_text, activation_count, is_permanent, absorbed, created_at, tier,"
            " evidence, falsify_if, last_verified, contradictions) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid, lid.lower(), "task_x", "[]", "[]", 0.6, text, 3, 0, absorbed, T0 + i, tier, ev, falsify,
             T0 + 50 + i, contra))
    # the merge log: L_OLD -> L_MID -> L_SURV (a survivor that was itself absorbed later)
    con.execute("INSERT INTO mycelium_landmark_merges VALUES ('m1','L_MID','L_OLD',1.0,0.8,0.7,0.9,?)", (T0 + 20,))
    con.execute("INSERT INTO mycelium_landmark_merges VALUES ('m2','L_SURV','L_MID',1.0,0.8,0.7,0.9,?)", (T0 + 30,))
    con.commit()
    con.close()


class Env:
    pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "memory.db"
    _seed(path)
    conn = _plain_store_connection(path)        # the app's own connection class: app_write falls back to it here
    conn.execute("PRAGMA synchronous=OFF")
    import backend.api.memory as api

    monkeypatch.setattr(api, "_store_conn", lambda: conn)
    taps: list[tuple[str, dict]] = []
    monkeypatch.setattr(memory_live, "_push", lambda kind, item: taps.append((kind, item)))
    monkeypatch.setattr(memory_live, "enabled", lambda: True)
    app = FastAPI()
    app.include_router(api.router)
    e = Env()
    e.client, e.conn, e.path, e.taps, e.api = TestClient(app), conn, path, taps, api
    yield e
    lane("memory_events").flush()
    conn.close()


def _settle(e) -> None:
    lane("memory_events").flush()        # a promotion is typed on the memory_events lane
    e.conn.commit()


def _rows(e, sql, params=()):
    _settle(e)
    return e.conn.execute(sql, params).fetchall()


def _landmark(e, lid):
    """The whole row, every column."""
    _settle(e)
    cur = e.conn.execute("SELECT * FROM mycelium_landmarks WHERE landmark_id = ?", (lid,))
    names = [d[0] for d in cur.description]
    r = cur.fetchone()
    return dict(zip(names, r)) if r else None


def _count(e):
    return _rows(e, "SELECT COUNT(*) FROM mycelium_landmarks")[0][0]


def _events(e, label=None):
    sql = "SELECT event_id, ts, family, label, evidence, actor, label_source, payload FROM memory_events"
    rows = _rows(e, sql + (" WHERE label = ?" if label else ""), (label,) if label else ())
    return [dict(zip(("event_id", "ts", "family", "label", "evidence", "actor", "label_source", "payload"), r))
            for r in rows]


def _correct(e, action, claim, **extra):
    return e.client.post("/api/memory/correct", json={"action": action, "target": f"claim:{claim}", **extra})


def _evidence_list(e, lid):
    return json.loads(_landmark(e, lid)["evidence"])


# -- confirm ----------------------------------------------------------------------------------------
def test_confirm_adds_one_user_evidence_entry_and_promotes_a_learning_claim(env):
    before = _landmark(env, "L_CAND")
    r = _correct(env, "confirm", "L_CAND")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"correction_id", "action", "target", "landmark_id", "before", "after", "undo_until"}
    assert d["action"] == "confirm" and d["target"] == "claim:L_CAND" and d["landmark_id"] == "L_CAND"
    keys = {"tier", "contradictions", "absorbed", "evidence_count"}
    assert set(d["before"]) == keys and set(d["after"]) == keys
    assert d["before"] == {"tier": "candidate", "contradictions": 0, "absorbed": False, "evidence_count": 1}
    # one user evidence + one test_pass = two independent outside kinds: the existing rule promotes it
    assert d["after"] == {"tier": "landmark", "contradictions": 0, "absorbed": False, "evidence_count": 2}
    ev = _evidence_list(env, "L_CAND")
    assert len(ev) == 2 and ev[-1]["kind"] == "user_confirm" and ev[-1]["ref"] == d["correction_id"]
    assert _landmark(env, "L_CAND")["last_verified"] > before["last_verified"]
    # a confirm that does not change the tier still adds exactly one entry
    r2 = _correct(env, "confirm", "L_PROV").json()
    assert r2["before"]["tier"] == r2["after"]["tier"] == "landmark"
    assert r2["after"]["evidence_count"] == r2["before"]["evidence_count"] + 1


# -- wrong ------------------------------------------------------------------------------------------
def test_wrong_is_one_contradiction_and_a_proven_claim_drops_to_candidate(env):
    proven_before = {x["id"]: x for x in integrity._load_live(env.conn)}["L_PROV"]
    assert proven_before["proven"] is True
    d = _correct(env, "wrong", "L_PROV", reason="the notes moved").json()
    assert d["before"]["tier"] == "landmark" and d["after"]["tier"] == "candidate"
    assert d["before"]["contradictions"] == 0 and d["after"]["contradictions"] == 1
    row = _landmark(env, "L_PROV")
    assert row["tier"] == "candidate" and row["contradictions"] == 1 and row["absorbed"] is None
    assert row["falsify_if"] == "a dependency changes (docs) | contradicted: the notes moved"
    # recall's own notion of "proven" (Kyudo: tier landmark + outside evidence) no longer holds
    assert {x["id"]: x for x in integrity._load_live(env.conn)}["L_PROV"]["proven"] is False
    # a learning claim stays learning; the contradiction still counts
    c = _correct(env, "wrong", "L_CAND").json()
    assert c["before"]["tier"] == c["after"]["tier"] == "candidate" and c["after"]["contradictions"] == 1


def test_wrong_ends_permanence_and_undo_brings_it_back(env):
    """A permanent claim you call wrong stayed permanent until its next activation, and Kyudo skips permanent claims,
    so it could never dissolve it (found 2026-10-25 by the corrections builder). Undo restores the flag."""
    env.conn.execute("UPDATE mycelium_landmarks SET is_permanent = 1 WHERE landmark_id = 'L_PROV'")
    env.conn.commit()
    d = _correct(env, "wrong", "L_PROV").json()
    assert _landmark(env, "L_PROV")["is_permanent"] == 0
    r = env.client.post("/api/memory/correct/undo", json={"correction_id": d["correction_id"]})
    assert r.status_code == 200 and _landmark(env, "L_PROV")["is_permanent"] == 1


# -- forget -----------------------------------------------------------------------------------------
def test_forget_absorbs_with_the_reason_and_never_deletes(env):
    n = _count(env)
    d = _correct(env, "forget", "L_CAND").json()
    assert d["before"]["absorbed"] is False and d["after"]["absorbed"] is True
    row = _landmark(env, "L_CAND")
    assert row["absorbed"] == 1 and row["falsify_if"] == " | dissolved: forgotten by you"
    assert _count(env) == n                                          # the row is kept
    # recall reads `absorbed IS NULL` only
    assert "L_CAND" not in {x.landmark_id for x in LandmarkIndex(env.conn).get_all_active()}
    assert "L_CAND" not in {x["id"] for x in integrity._load_live(env.conn)}
    # a forgotten claim cannot be corrected again
    for action in ("confirm", "wrong", "forget"):
        assert _correct(env, action, "L_CAND").status_code == 409
    assert _landmark(env, "L_CAND")["falsify_if"] == " | dissolved: forgotten by you"      # untouched by the refusals


# -- targets ----------------------------------------------------------------------------------------
def test_a_claim_absorbed_by_a_merge_lands_on_its_survivor(env):
    before_old, before_mid = _landmark(env, "L_OLD"), _landmark(env, "L_MID")
    d = _correct(env, "confirm", "L_OLD").json()                     # L_OLD -> L_MID -> L_SURV
    assert d["landmark_id"] == "L_SURV" and d["target"] == "claim:L_OLD"
    assert _evidence_list(env, "L_SURV")[-1]["ref"] == d["correction_id"]
    assert _landmark(env, "L_OLD") == before_old and _landmark(env, "L_MID") == before_mid
    w = _correct(env, "wrong", "L_MID").json()                       # one hop
    assert w["landmark_id"] == "L_SURV" and _landmark(env, "L_SURV")["contradictions"] == 1
    f = _correct(env, "forget", "L_OLD").json()
    assert f["landmark_id"] == "L_SURV" and _landmark(env, "L_SURV")["absorbed"] == 1
    assert _landmark(env, "L_OLD") == before_old                     # the absorbed rows are never touched
    # the list names the claim actually changed, and the target the user pointed at
    c = env.client.get("/api/memory/corrections").json()["corrections"]
    assert {x["landmark_id"] for x in c} == {"L_SURV"} and {x["target"] for x in c} == {"claim:L_OLD", "claim:L_MID"}


def test_unknown_forgotten_dissolved_and_malformed_targets(env):
    assert _correct(env, "confirm", "L_NOPE").status_code == 404
    for action in ("confirm", "wrong", "forget"):
        assert _correct(env, action, "L_GONE").status_code == 409    # dissolved, no survivor
    assert _correct(env, "explode", "L_PROV").status_code == 400
    assert env.client.post("/api/memory/correct", json={"action": "confirm"}).status_code == 400
    for bad in ("L_PROV", "pin:L_PROV", "claim:", "claim:a b", 'claim:x"y'):
        assert env.client.post("/api/memory/correct", json={"action": "confirm", "target": bad}).status_code == 400, bad
    assert env.client.post("/api/memory/correct/undo", json={"correction_id": "cor-nope"}).status_code == 404
    assert env.client.post("/api/memory/correct/undo", json={}).status_code == 404
    assert _events(env) == []                                        # a refused correction types nothing
    assert _landmark(env, "L_GONE")["falsify_if"] == "dissolved: no_credibility"


# -- evidence, events, taps -------------------------------------------------------------------------
def test_every_correction_is_user_evidence_and_types_one_event_with_the_prior_state(env):
    ids = {a: _correct(env, a, c).json() for a, c in (("confirm", "L_CAND"), ("wrong", "L_PROV"), ("forget", "L_FULL"))}
    want = {"confirm": ("feedback", "CONFIRMATION"), "wrong": ("feedback", "CORRECTION"),
            "forget": ("memory", "CLAIM_FORGOTTEN")}
    for action, (family, label) in want.items():
        evs = [e for e in _events(env, label) if json.loads(e["payload"]).get("correction_id") == ids[action]["correction_id"]]
        assert len(evs) == 1, (action, evs)                          # ONE event per correction
        e = evs[0]
        assert (e["family"], e["evidence"], e["actor"], e["label_source"]) == (family, "user", "user", "user")
        p = json.loads(e["payload"])
        assert p["action"] == action and p["landmark_id"] == ids[action]["landmark_id"]
        assert {"tier", "contradictions", "absorbed", "evidence_count"} <= set(p["before"])
        assert {k: p["before"][k] for k in ids[action]["before"]} == ids[action]["before"]
        assert abs(ids[action]["undo_until"] - (e["ts"] + 600)) < 1e-6
    # the only other event is the system's own typing of the promotion the confirm caused
    assert {e["label"] for e in _events(env)} <= {"CONFIRMATION", "CORRECTION", "CLAIM_FORGOTTEN", "LANDMARK_PROMOTED"}
    # evidence entry of a confirm: an OUTSIDE kind, the user's
    assert _evidence_list(env, "L_CAND")[-1]["kind"] == "user_confirm"
    from backend.memory.mycelium.landmark import OUTSIDE_EVIDENCE
    assert "user_confirm" in OUTSIDE_EVIDENCE


def test_the_live_taps_fire_with_the_new_tier(env):
    _correct(env, "confirm", "L_CAND")
    _settle(env)
    _correct(env, "wrong", "L_PROV")
    _correct(env, "forget", "L_SURV")
    ups = [i for k, i in env.taps if k == "landmark_update"]
    by = {(u["landmark_id"], u["kind"]): u for u in ups}
    assert by[("L_CAND", "promoted")]["tier"] == "landmark"
    assert by[("L_PROV", "demoted")]["tier"] == "candidate"
    assert ("L_SURV", "dissolved") in by
    labels = [i["label"] for k, i in env.taps if k == "memory_event"]
    assert {"CONFIRMATION", "CORRECTION", "CLAIM_FORGOTTEN"} <= set(labels)
    ev = next(i for k, i in env.taps if k == "memory_event" and i["label"] == "CORRECTION")
    assert ev["landmark_id"] == "L_PROV" and ev["evidence"] == "user"


# -- no deletes -------------------------------------------------------------------------------------
def test_no_landmark_row_is_ever_deleted(env):
    n = _count(env)
    ids = []
    for action in ("confirm", "wrong", "forget"):
        for claim in LIVE_IDS + ["L_OLD"]:
            r = _correct(env, action, claim)
            assert r.status_code in (200, 409)
            if r.status_code == 200:
                ids.append(r.json()["correction_id"])
            assert _count(env) == n
    for cid in ids:
        assert env.client.post("/api/memory/correct/undo", json={"correction_id": cid}).status_code == 200
        assert _count(env) == n


# -- undo -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("action,claim", [
    ("confirm", "L_CAND"),      # promoted by the confirm
    ("confirm", "L_PROV"),
    ("confirm", "L_FULL"),      # the list was full: the oldest entry fell off and must come back
    ("wrong", "L_PROV"),        # proven -> candidate
    ("wrong", "L_LONG"),        # a falsify_if longer than the payload keeps whole
    ("forget", "L_CAND"),
    ("forget", "L_LONG"),
    ("confirm", "L_OLD"),       # lands on the survivor
])
def test_undo_restores_the_exact_prior_row(env, action, claim):
    target = {"L_OLD": "L_SURV"}.get(claim, claim)
    before = _landmark(env, target)
    d = _correct(env, action, claim).json()
    assert _landmark(env, target) != before
    u = env.client.post("/api/memory/correct/undo", json={"correction_id": d["correction_id"]})
    assert u.status_code == 200
    body = u.json()
    assert body["undone"] is True and body["landmark_id"] == target and body["after"] == d["before"]
    assert _landmark(env, target) == before                          # every column, byte for byte
    undone = _events(env, "CORRECTION_UNDONE")
    assert len(undone) == 1 and undone[0]["evidence"] == "user" and undone[0]["family"] == "feedback"
    assert json.loads(undone[0]["payload"])["correction_id"] == d["correction_id"]


def test_undo_removes_exactly_the_evidence_entry_its_confirm_added(env):
    first = _correct(env, "confirm", "L_PROV").json()
    second = _correct(env, "confirm", "L_PROV").json()
    assert [e["ref"] for e in _evidence_list(env, "L_PROV") if e["kind"] == "user_confirm"] == [
        first["correction_id"], second["correction_id"]]
    assert env.client.post("/api/memory/correct/undo", json={"correction_id": first["correction_id"]}).status_code == 200
    assert [e["ref"] for e in _evidence_list(env, "L_PROV") if e["kind"] == "user_confirm"] == [second["correction_id"]]


def test_undo_is_refused_twice_and_after_600_seconds(env, monkeypatch):
    d = _correct(env, "wrong", "L_PROV").json()
    cid = d["correction_id"]
    assert env.client.post("/api/memory/correct/undo", json={"correction_id": cid}).status_code == 200
    again = env.client.post("/api/memory/correct/undo", json={"correction_id": cid})
    assert again.status_code == 409 and "already" in again.json()["error"]
    # time: the window is 600 s from the correction's event
    d2 = _correct(env, "forget", "L_CAND").json()
    now = time.time()
    after_wrong = _landmark(env, "L_CAND")
    monkeypatch.setattr(corrections, "_now", lambda: d2["undo_until"] + 1.0)
    late = env.client.post("/api/memory/correct/undo", json={"correction_id": d2["correction_id"]})
    assert late.status_code == 409 and "window" in late.json()["error"]
    assert _landmark(env, "L_CAND") == after_wrong                   # a refused undo changes nothing
    monkeypatch.setattr(corrections, "_now", lambda: d2["undo_until"] - 1.0)
    assert env.client.post("/api/memory/correct/undo", json={"correction_id": d2["correction_id"]}).status_code == 200
    assert d2["undo_until"] - now == pytest.approx(600, abs=5)       # 600 s, give or take the test's own runtime


# -- the list ---------------------------------------------------------------------------------------
def test_the_list_is_newest_first_marks_undone_and_clips_the_claim(env):
    a = _correct(env, "confirm", "L_PROV").json()
    time.sleep(0.01)
    b = _correct(env, "wrong", "L_SURV").json()
    time.sleep(0.01)
    c = _correct(env, "forget", "L_CAND").json()
    assert env.client.post("/api/memory/correct/undo", json={"correction_id": b["correction_id"]}).status_code == 200
    d = env.client.get("/api/memory/corrections?limit=20").json()
    assert set(d) == {"corrections"}
    rows = d["corrections"]
    assert [r["correction_id"] for r in rows] == [c["correction_id"], b["correction_id"], a["correction_id"]]
    assert [r["undone"] for r in rows] == [False, True, False]
    first = rows[0]
    assert set(first) == {"correction_id", "ts", "action", "target", "landmark_id", "claim", "undone", "undo_until"}
    assert first["action"] == "forget" and first["target"] == "claim:L_CAND" and first["claim"] == "Prefer small diffs"
    assert first["undo_until"] == pytest.approx(first["ts"] + 600)
    assert [r["ts"] for r in rows] == sorted((r["ts"] for r in rows), reverse=True)
    assert len(rows[1]["claim"]) == 160 and rows[1]["landmark_id"] == "L_SURV"        # clipped
    assert len(env.client.get("/api/memory/corrections?limit=2").json()["corrections"]) == 2
    assert [r["correction_id"] for r in env.client.get("/api/memory/corrections?limit=1").json()["corrections"]] == [c["correction_id"]]
    assert len(env.client.get("/api/memory/corrections?limit=100000").json()["corrections"]) == 3     # clamped, not an error
    # the CORRECTION_UNDONE event is not itself a correction
    assert all(r["action"] in ("confirm", "wrong", "forget") for r in rows)


def test_an_empty_store_lists_nothing(env):
    assert env.client.get("/api/memory/corrections").json() == {"corrections": []}


# -- plans ------------------------------------------------------------------------------------------
def test_every_select_on_memory_events_is_a_search_never_a_scan(env):
    seen: list[str] = []
    env.conn.set_trace_callback(lambda s: seen.append(s) if s.lstrip().upper().startswith(("SELECT", "WITH")) else None)
    a = _correct(env, "confirm", "L_CAND").json()
    _correct(env, "wrong", "L_PROV")
    _correct(env, "forget", "L_FULL")
    env.client.post("/api/memory/correct/undo", json={"correction_id": a["correction_id"]})
    env.client.post("/api/memory/correct/undo", json={"correction_id": a["correction_id"]})       # the refused one reads too
    env.client.get("/api/memory/corrections")
    _settle(env)
    env.conn.set_trace_callback(None)
    on_events = [s for s in seen if re.search(r"\bFROM memory_events\b", s)]
    assert len(on_events) >= 6, on_events
    con = sqlite3.connect(env.path)
    bad = []
    for sql in on_events:
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql)]
        if not any(line.startswith("SEARCH memory_events") for line in plan) or any(
                re.match(r"SCAN memory_events", line) for line in plan):
            bad.append((" ".join(sql.split())[:140], plan))
    con.close()
    assert not bad, bad


# =====================================================================================================
# pins and strands (the rest of the v1 table)
# =====================================================================================================
# The tables the pin and strand corrections read besides the claim cast: the live pin-link table and its indexes
# (backend/memory/db.py), the documents table and the strand index of memory_events (memory_events.ensure_schema).
RICH_DDL = """
CREATE TABLE mycelium_pin_links (link_id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL,
  source_id TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, relationship TEXT NOT NULL,
  weight REAL DEFAULT 1.0, created_at REAL NOT NULL);
CREATE INDEX idx_pin_links_source ON mycelium_pin_links(source_type, source_id);
CREATE INDEX idx_pin_links_target ON mycelium_pin_links(target_type, target_id);
CREATE TABLE document_data (document_id TEXT PRIMARY KEY, conversation_id TEXT, fmt TEXT, title TEXT, content TEXT,
  created_at TEXT);
CREATE INDEX idx_memory_events_thread_ts ON memory_events(thread_id, ts);
"""
REMOVED = "[removed by you]"
PAYLOAD_A1 = {"source": "neighbors", "refs": ["ch-a-0", "ch-a-1"], "note": "my secret plan", "n": 3, "ok": True,
              "nested": {"reason": "private", "step_id": "s1"}}


def _claim(c, lid, text, evidence, falsify=None, tier="candidate"):
    c.execute("INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,"
              " cumulative_score, micro_abstract_text, activation_count, is_permanent, created_at, tier, evidence,"
              " falsify_if, last_verified, contradictions) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (lid, lid.lower(), "task_x", "[]", "[]", 0.6, text, 1, 0, T0, tier, json.dumps(evidence), falsify, T0 + 5, 0))


def _ev_entry(kind, session):
    return {"kind": kind, "ref": "r", "session": session, "at": T0}


def _seed_rich(e) -> None:
    c = e.conn
    c.executescript(RICH_DDL)
    store = PinStore(c)
    p = e.pins = {}
    p["note"] = store.add("Keep the release notes", "body " * 20, tags=["docs"], file_refs=["docs/a.md"])
    store.link(p["note"], "L_FULL", "references", target_type="landmark")
    store.link(p["note"], "pin-other", "related_to")
    p["held"] = store.add("Held pin", "h", tags=["held", "x"])
    p["ctx"] = store.add("Context pin", "c", tags=["context"])
    p["big"] = store.add("Big pin", "z" * 3000)
    c.execute("INSERT INTO document_data (document_id, conversation_id, fmt, title, content, created_at)"
              " VALUES ('doc-1','conv-a','markdown','Release plan','x','2026-10-25 10:00:00')")
    # strand conv-a (the one the user forgets / purges) and conv-b (must never change)
    _ev(c, "a-1", T0 + 1, "RECALL_DELIVERED", "conv-a", episode="conv-a:t1", step="s1",
        links={"recall_trace_id": "rt-1"}, payload=PAYLOAD_A1)
    _ev(c, "a-2", T0 + 2, "GOAL_SET", "conv-a", episode="conv-a:t1", family="intent", payload={"goal": "buy a gift for mum"})
    _ev(c, "a-3", T0 + 3, "ANSWER_GIVEN", "conv-a", episode="conv-a:t2", family="delivery")
    _ev(c, "a-4", T0 + 4, "OBSERVED", "conv-a", episode="conv-a:t2", family="knowledge")
    c.execute("UPDATE memory_events SET payload = 'plain text note' WHERE event_id = 'a-4'")
    _ev(c, "b-1", T0 + 5, "GOAL_SET", "conv-b", episode="conv-b:t1", family="intent", payload={"goal": "keep me"})
    for i in range(3):
        _chain(c, "conv-a", i, T0 + 10 + i, f"secret insight {i}", cid=f"ch-a-{i}")
    c.execute("INSERT INTO memory_chain (thread_id, sequence, role, content, created_at, chain_id, node_type)"
              " VALUES ('conv-a', 3, 'agent', '', ?, 'ch-a-3', 'step')", (T0 + 14,))
    for i in range(2):
        _chain(c, "conv-b", i, T0 + 20 + i, f"b insight {i}", cid=f"ch-b-{i}")
    for eid, sess, summary in (("ep-a1", "conv-a", "Plan mum gift"), ("ep-a2", "conv-a", "Wrap it"), ("ep-b1", "conv-b", "Other")):
        c.execute("INSERT INTO episodes (id, session_id, task_summary, full_content, outcome_type, timestamp)"
                  " VALUES (?,?,?,?,?,?)", (eid, sess, summary, "details of " + summary, "success", "2026-10-25 10:00:00"))
    # claims: what each strand taught
    _claim(c, "L_A1", "Only conv-a taught me this", [_ev_entry("test_pass", "conv-a")])
    _claim(c, "L_A2", "Also only conv-a", [_ev_entry("test_pass", "conv-a"), _ev_entry("recurrence", "conv-a")],
           falsify="a dependency changes (x)", tier="landmark")
    _claim(c, "L_AB", "conv-a and conv-b agree", [_ev_entry("test_pass", "conv-a"), _ev_entry("test_pass", "conv-b")])
    _claim(c, "L_AU", "conv-a plus my own word", [_ev_entry("test_pass", "conv-a"), _ev_entry("user_confirm", "user")])
    _claim(c, "L_B1", "Only conv-b", [_ev_entry("test_pass", "conv-b")])
    _claim(c, "L_NOEV", "No evidence at all", [])
    c.commit()


@pytest.fixture()
def rich(env, monkeypatch):
    monkeypatch.setattr(strand_ids, "_is_conversation", lambda cid: str(cid).startswith("conv-"))
    _seed_rich(env)
    return env


def _post(e, action, target, **extra):
    return e.client.post("/api/memory/correct", json={"action": action, "target": target, **extra})


def _undo(e, d):
    return e.client.post("/api/memory/correct/undo", json={"correction_id": d["correction_id"]})


def _table(e, table, where="", params=(), skip=()):
    """Every row of ``table`` as dicts, without the columns in ``skip``, in a stable order."""
    _settle(e)
    cur = e.conn.execute(f"SELECT * FROM {table} {where} ORDER BY rowid", params)
    names = [d[0] for d in cur.description]
    return [{k: v for k, v in zip(names, r) if k not in skip} for r in cur.fetchall()]


def _pin_row(e, pin_id):
    r = _table(e, "mycelium_pins", "WHERE pin_id = ?", (pin_id,))
    return r[0] if r else None


def _links(e, pin_id):
    return _table(e, "mycelium_pin_links", "WHERE source_id = ? OR target_id = ?", (pin_id, pin_id))


def _spy_pin_store(monkeypatch):
    calls: list[str] = []
    for name in ("add", "update", "delete", "link", "restore"):
        orig = getattr(PinStore, name)

        def wrap(self, *a, _o=orig, _n=name, **k):
            calls.append(_n)
            return _o(self, *a, **k)

        monkeypatch.setattr(PinStore, name, wrap)
    return calls


def _one_event(e, label, correction_id):
    evs = [x for x in _events(e, label) if json.loads(x["payload"]).get("correction_id") == correction_id]
    assert len(evs) == 1, evs
    x = evs[0]
    assert (x["family"], x["evidence"], x["actor"], x["label_source"]) == ("memory", "user", "user", "user")
    return x, json.loads(x["payload"])


# -- pins: hold / release ---------------------------------------------------------------------------
@pytest.mark.parametrize("action,key,after_tags", [("hold", "note", ["docs", "held"]),
                                                   ("release", "held", ["x"]), ("release", "ctx", [])])
def test_hold_and_release_go_through_the_pin_stores_update_and_undo_restores_exactly(rich, monkeypatch, action, key,
                                                                                    after_tags):
    pid, calls = rich.pins[key], _spy_pin_store(monkeypatch)
    before = _pin_row(rich, pid)
    held_before = action == "release"
    d = _post(rich, action, f"pin:{pid}").json()
    assert set(d) == {"correction_id", "action", "target", "pin_id", "before", "after", "undo_until"}
    assert d["pin_id"] == pid and d["target"] == f"pin:{pid}"
    assert d["before"] == {"held": held_before, "exists": True} and d["after"] == {"held": not held_before, "exists": True}
    assert json.loads(_pin_row(rich, pid)["tags"]) == after_tags
    assert calls == ["update"]                                                  # the store's own method, nothing else
    x, p = _one_event(rich, "PIN_CORRECTED", d["correction_id"])
    assert p["action"] == action and p["pin_id"] == pid and p["before"]["tags"] == json.loads(before["tags"])
    assert d["undo_until"] == pytest.approx(x["ts"] + 600)
    u = _undo(rich, d)
    assert u.status_code == 200 and u.json()["after"] == d["before"] and u.json()["undone"] is True
    assert _pin_row(rich, pid) == before                                        # every column, updated_at too
    assert _undo(rich, d).status_code == 409                                    # once
    assert len(_events(rich, "CORRECTION_UNDONE")) == 1


def test_a_pin_the_action_does_not_fit_is_refused_and_untouched(rich):
    note, held = rich.pins["note"], rich.pins["held"]
    before, events = _table(rich, "mycelium_pins"), _table(rich, "memory_events")
    assert _post(rich, "release", f"pin:{note}").status_code == 409             # not held
    assert _post(rich, "hold", f"pin:{held}").status_code == 409                # already held
    assert _post(rich, "hold", "pin:nope").status_code == 404
    assert _post(rich, "unpin", "pin:nope").status_code == 404
    assert _table(rich, "mycelium_pins") == before and _table(rich, "memory_events") == events   # a refusal writes nothing


# -- pins: unpin ------------------------------------------------------------------------------------
def test_unpin_deletes_through_the_store_and_undo_puts_the_same_pin_back(rich, monkeypatch):
    pid, calls = rich.pins["note"], _spy_pin_store(monkeypatch)
    row, links = _pin_row(rich, pid), _links(rich, pid)
    assert len(links) == 2
    n_pins = len(_table(rich, "mycelium_pins"))
    d = _post(rich, "unpin", f"pin:{pid}").json()
    assert d["before"] == {"held": False, "exists": True} and d["after"] == {"held": False, "exists": False}
    assert _pin_row(rich, pid) is None and _links(rich, pid) == []
    assert len(_table(rich, "mycelium_pins")) == n_pins - 1
    assert calls == ["delete"]
    x, p = _one_event(rich, "PIN_CORRECTED", d["correction_id"])
    assert p["before"]["snapshot"]["pin"]["pin_id"] == pid and len(p["before"]["snapshot"]["links"]) == 2
    u = _undo(rich, d)
    assert u.status_code == 200 and u.json()["after"] == d["before"]
    assert "restore" in calls
    assert _pin_row(rich, pid) == row                                           # the pin, exactly
    assert _links(rich, pid) == links                                           # its links, link ids too
    assert len(_table(rich, "mycelium_pins")) == n_pins


def test_unpin_of_a_held_pin_says_held_and_a_big_pin_is_refused_with_its_row_kept(rich):
    d = _post(rich, "unpin", f"pin:{rich.pins['held']}").json()
    assert d["before"]["held"] is True and d["after"] == {"held": False, "exists": False}
    assert _undo(rich, d).status_code == 200
    big = _post(rich, "unpin", f"pin:{rich.pins['big']}")
    assert big.status_code == 409 and "too big" in big.json()["error"]
    assert _pin_row(rich, rich.pins["big"]) is not None                         # not dropped without a way back


def test_undo_of_an_unpin_is_refused_when_the_id_is_taken_again(rich):
    pid = rich.pins["held"]
    d = _post(rich, "unpin", f"pin:{pid}").json()
    PinStore(rich.conn).restore({"pin_id": pid, "title": "t", "pin_type": "note", "content": "", "tags": [],
                                 "file_refs": [], "image_refs": [], "url_refs": [], "project_id": None,
                                 "origin_id": None, "created_at": 1.0, "updated_at": 1.0, "is_permanent": False})
    assert _undo(rich, d).status_code == 409
    assert _pin_row(rich, pid)["title"] == "t"                                  # the newer pin is untouched


# -- pins: pin --------------------------------------------------------------------------------------
@pytest.mark.parametrize("target,link_type,link_id,title", [
    ("claim:L_PROV", "landmark", "L_PROV", "The release notes live in docs"),
    ("claim:L_OLD", "landmark", "L_SURV", None),                                 # a merged claim: its survivor is pinned
    ("turn:conv-a:t1", "turn", "conv-a:t1", "Turn t1"),
    ("artifact:doc-1", "artifact", "doc-1", "Release plan")])
def test_pin_creates_through_the_stores_add_and_link_and_undo_removes_it(rich, monkeypatch, target, link_type, link_id,
                                                                         title):
    calls = _spy_pin_store(monkeypatch)
    n = len(_table(rich, "mycelium_pins"))
    d = _post(rich, "pin", target)
    assert d.status_code == 200, d.json()
    d = d.json()
    assert set(d) == {"correction_id", "action", "target", "pin_id", "before", "after", "undo_until"}
    assert d["before"] == {"held": False, "exists": False} and d["after"] == {"held": False, "exists": True}
    assert calls == ["add", "link"]
    row = _pin_row(rich, d["pin_id"])
    assert row is not None and (title is None or row["title"] == title) and len(_table(rich, "mycelium_pins")) == n + 1
    assert json.loads(row["tags"])[0] == "user"
    (link,) = _links(rich, d["pin_id"])
    assert (link["source_type"], link["source_id"], link["target_type"], link["target_id"], link["relationship"]) == (
        "pin", d["pin_id"], link_type, link_id, "references")
    _one_event(rich, "PIN_CORRECTED", d["correction_id"])
    assert _post(rich, "pin", target).status_code == 409                        # already pinned
    u = _undo(rich, d)
    assert u.status_code == 200 and u.json()["after"] == d["before"]
    assert _pin_row(rich, d["pin_id"]) is None and _links(rich, d["pin_id"]) == []
    assert len(_table(rich, "mycelium_pins")) == n
    assert _post(rich, "pin", target).status_code == 200                        # free again after the undo


def test_pin_and_pin_actions_refuse_what_cannot_be_pinned_or_does_not_fit(rich):
    events, pins = _table(rich, "memory_events"), _table(rich, "mycelium_pins")
    assert _post(rich, "pin", "claim:L_NOPE").status_code == 404
    assert _post(rich, "pin", "claim:L_GONE").status_code == 409                # dissolved: no survivor
    assert _post(rich, "pin", "turn:conv-a:t99").status_code == 404
    assert _post(rich, "pin", "artifact:doc-nope").status_code == 404
    assert _post(rich, "pin", "turn:conv-a").status_code == 400                 # a turn needs both ids
    for action, target in (("confirm", f"pin:{rich.pins['note']}"), ("hold", "claim:L_PROV"), ("unpin", "claim:L_PROV"),
                           ("pin", f"pin:{rich.pins['note']}"), ("pin", "strand:conv-a"), ("forget", "strand:conv-a"),
                           ("forget_learned", "claim:L_PROV"), ("purge", "turn:conv-a:t1"), ("release", "artifact:doc-1")):
        assert _post(rich, action, target, confirm=target.split(":")[-1]).status_code == 400, (action, target)
    assert _table(rich, "memory_events") == events and _table(rich, "mycelium_pins") == pins


# -- strands: forget what IRIS learned here ---------------------------------------------------------
def _recalled_chain_ids(e):
    rows, _ = filtered_chain_recall(e.conn, RecallFilters(limit=50))
    return {r["chain_id"] for r in rows}


def test_forget_learned_absorbs_only_what_the_strand_alone_taught_and_never_deletes(rich):
    before = {lid: _landmark(rich, lid) for lid in ("L_A1", "L_A2", "L_AB", "L_AU", "L_B1", "L_NOEV")}
    n, n_ev = _count(rich), len(_table(rich, "memory_events"))
    a_events = _table(rich, "memory_events", "WHERE thread_id = 'conv-a'")
    d = _post(rich, "forget_learned", "strand:conv-a").json()
    assert set(d) == {"correction_id", "action", "target", "before", "after", "undo_until"}
    assert d["before"] == {"claims_absorbed": 0, "events_marked": 0}
    assert d["after"] == {"claims_absorbed": 2, "events_marked": 4}
    suffix = " | dissolved: forgotten by you (strand conv-a)"
    assert _landmark(rich, "L_A1")["absorbed"] == 1 and _landmark(rich, "L_A1")["falsify_if"] == suffix
    assert _landmark(rich, "L_A2")["absorbed"] == 1
    assert _landmark(rich, "L_A2")["falsify_if"] == "a dependency changes (x)" + suffix
    for lid in ("L_AB", "L_AU", "L_B1", "L_NOEV"):                              # other evidence, or none: untouched
        assert _landmark(rich, lid) == before[lid], lid
    assert _count(rich) == n                                                    # nothing deleted
    # kept for history: the strand's events are still there, byte for byte, plus ONE user-evidence marker
    assert _table(rich, "memory_events", "WHERE thread_id = 'conv-a'") == a_events
    x, p = _one_event(rich, "STRAND_LEARNING_FORGOTTEN", d["correction_id"])
    assert len(_table(rich, "memory_events")) == n_ev + 1
    assert p["action"] == "forget_learned" and p["strand_id"] == "conv-a" and p["session_ids"] == ["conv-a"]
    assert set(p["before"]["claim_ids"]) == {"L_A1", "L_A2"} and p["before"]["null_prior_ids"] == ["L_A1"]
    assert d["undo_until"] == pytest.approx(x["ts"] + 600)
    live = {c.landmark_id for c in LandmarkIndex(rich.conn).get_all_active()}
    assert not {"L_A1", "L_A2"} & live and {"L_AB", "L_AU", "L_B1"} <= live      # recall reads `absorbed IS NULL`
    for lid in ("L_A1", "L_A2"):                                                 # the claim corrections refuse them now
        assert _correct(rich, "confirm", lid).status_code == 409


def test_recall_leaves_a_forgotten_strand_out_and_takes_it_back_on_undo(rich):
    assert {"ch-a-0", "ch-a-1", "ch-a-2", "ch-b-0", "ch-b-1"} <= _recalled_chain_ids(rich)
    assert len(chain_timeline(rich.conn, "conv-a")) == 4
    d = _post(rich, "forget_learned", "strand:conv-a").json()
    assert corrections.forgotten_strands(rich.conn) == frozenset({"conv-a"})
    got = _recalled_chain_ids(rich)
    assert got == {"ch-b-0", "ch-b-1"}                                          # only the other strand
    assert chain_timeline(rich.conn, "conv-a") == [] and len(chain_timeline(rich.conn, "conv-b")) == 2
    assert _undo(rich, d).status_code == 200
    assert corrections.forgotten_strands(rich.conn) == frozenset()
    assert {"ch-a-0", "ch-a-1", "ch-a-2", "ch-b-0", "ch-b-1"} <= _recalled_chain_ids(rich)
    assert len(chain_timeline(rich.conn, "conv-a")) == 4


def test_undo_of_a_strand_forget_restores_every_claim_column_and_is_refused_twice_and_late(rich, monkeypatch):
    before = _table(rich, "mycelium_landmarks")
    d = _post(rich, "forget_learned", "strand:conv-a").json()
    assert _table(rich, "mycelium_landmarks") != before
    u = _undo(rich, d)
    assert u.status_code == 200 and u.json()["after"] == d["before"] and u.json()["undone"] is True
    assert _table(rich, "mycelium_landmarks") == before                         # NULL falsify_if is NULL again
    assert _undo(rich, d).status_code == 409
    d2 = _post(rich, "forget_learned", "strand:conv-a").json()
    absorbed = _table(rich, "mycelium_landmarks")
    monkeypatch.setattr(corrections, "_now", lambda: d2["undo_until"] + 1.0)
    late = _undo(rich, d2)
    assert late.status_code == 409 and "window" in late.json()["error"]
    assert _table(rich, "mycelium_landmarks") == absorbed
    assert corrections.forgotten_strands(rich.conn) == frozenset({"conv-a"})    # a refused undo changes nothing


def test_a_second_forget_keeps_the_strand_excluded_until_every_forget_is_undone(rich):
    first = _post(rich, "forget_learned", "strand:conv-a").json()
    second = _post(rich, "forget_learned", "strand:conv-a").json()
    assert second["before"] == {"claims_absorbed": 0, "events_marked": 4}       # already marked
    assert second["after"] == {"claims_absorbed": 0, "events_marked": 4}
    assert _undo(rich, second).status_code == 200
    assert corrections.forgotten_strands(rich.conn) == frozenset({"conv-a"})    # the first marker still stands
    assert _undo(rich, first).status_code == 200
    assert corrections.forgotten_strands(rich.conn) == frozenset()


# -- strands: purge ---------------------------------------------------------------------------------
def _structure(e):
    """Everything a purge must NOT change: every column except the text ones, of every strand's rows."""
    return {"events": _table(e, "memory_events", skip=("payload",)),
            "chain": _table(e, "memory_chain", skip=("content", "insight", "result")),
            "episodes": _table(e, "episodes", skip=("task_summary", "full_content")),
            "pins": _table(e, "mycelium_pins"), "links": _table(e, "mycelium_pin_links"),
            "landmarks": _table(e, "mycelium_landmarks")}


def test_purge_needs_the_strand_id_typed_again(rich):
    before = _table(rich, "memory_events") + _table(rich, "memory_chain") + _table(rich, "episodes")
    for extra in ({}, {"confirm": "conv-b"}, {"confirm": ""}, {"confirm": "conv-a "}):
        r = _post(rich, "purge", "strand:conv-a", **extra)
        assert r.status_code == 400 and "confirm" in r.json()["error"], extra
    assert _table(rich, "memory_events") + _table(rich, "memory_chain") + _table(rich, "episodes") == before
    assert _post(rich, "purge", "strand:conv-zzz", confirm="conv-zzz").status_code == 404


def test_purge_rewrites_text_only_keeps_every_reference_and_counts_the_rows(rich):
    struct = _structure(rich)
    refs = lambda e: {r for (p,) in e.conn.execute(  # noqa: E731 - every chain id a RECALL_DELIVERED payload names
        "SELECT payload FROM memory_events WHERE label = 'RECALL_DELIVERED'") for r in json.loads(p).get("refs", [])}
    chain_ids = lambda e: sorted(r[0] for r in e.conn.execute("SELECT chain_id FROM memory_chain"))  # noqa: E731
    b_events, b_chain = (_table(rich, "memory_events", "WHERE thread_id = 'conv-b'"),
                         _table(rich, "memory_chain", "WHERE thread_id = 'conv-b'"))
    refs_before, chain_before = refs(rich), chain_ids(rich)
    r = _post(rich, "purge", "strand:conv-a", confirm="conv-a")
    assert r.status_code == 200, r.json()
    d = r.json()
    assert set(d) == {"correction_id", "action", "target", "before", "after", "undo_until"}
    assert d["after"] == {"rows_changed": {"memory_events": 3, "memory_chain": 3, "episodes": 2}}
    assert d["undo_until"] is None
    # text is gone ...
    payloads = {r[0]: r[1] for r in _rows(rich, "SELECT event_id, payload FROM memory_events WHERE thread_id = 'conv-a'")}
    assert json.loads(payloads["a-1"]) == {"source": REMOVED, "refs": ["ch-a-0", "ch-a-1"], "note": REMOVED, "n": 3,
                                           "ok": True, "nested": {"reason": REMOVED, "step_id": "s1"}}
    assert json.loads(payloads["a-2"]) == {"goal": REMOVED} and json.loads(payloads["a-3"]) == {}
    assert json.loads(payloads["a-4"]) == REMOVED                                # a non-JSON payload is text
    chain = _table(rich, "memory_chain", "WHERE thread_id = 'conv-a'")
    assert [c["content"] for c in chain] == [REMOVED] * 3 + [""]                 # an empty one stays empty
    assert [c["insight"] for c in chain[:3]] == [REMOVED] * 3 and all(c["result"] == REMOVED for c in chain[:3])
    assert all(c["result"] is None for c in chain[3:])
    eps = _table(rich, "episodes", "WHERE session_id = 'conv-a'")
    assert {(e_["task_summary"], e_["full_content"]) for e_ in eps} == {(REMOVED, REMOVED)}
    # ... and nothing else moved: ids, links, timestamps, counts, every reference still resolves
    after = _structure(rich)
    for k in struct:
        assert after[k][:len(struct[k])] == struct[k], k                         # the new purge event is the one added row
    assert len(after["events"]) == len(struct["events"]) + 1 and len(after["chain"]) == len(struct["chain"])
    assert refs(rich) == refs_before and refs_before <= set(chain_ids(rich))
    assert chain_ids(rich) == chain_before
    assert _table(rich, "memory_events", "WHERE thread_id = 'conv-b'") == b_events      # the other strand: untouched
    assert _table(rich, "memory_chain", "WHERE thread_id = 'conv-b'") == b_chain
    assert _table(rich, "episodes", "WHERE session_id = 'conv-b'")[0]["task_summary"] == "Other"
    x, p = _one_event(rich, "STRAND_PURGED", d["correction_id"])
    assert p["rows_changed"] == d["after"]["rows_changed"] and "before" not in p        # nothing is kept to undo with
    # the same purge again changes nothing
    again = _post(rich, "purge", "strand:conv-a", confirm="conv-a").json()
    assert again["after"] == {"rows_changed": {"memory_events": 0, "memory_chain": 0, "episodes": 0}}


def test_a_purge_cannot_be_undone(rich):
    d = _post(rich, "purge", "strand:conv-a", confirm="conv-a").json()
    u = _undo(rich, d)
    assert u.status_code == 409 and "cannot be undone" in u.json()["error"]
    assert _events(rich, "CORRECTION_UNDONE") == []
    assert _table(rich, "memory_chain", "WHERE thread_id = 'conv-a'")[0]["content"] == REMOVED


# -- the list ---------------------------------------------------------------------------------------
def test_the_list_holds_every_kind_and_the_target_tells_which(rich):
    a = _post(rich, "pin", "claim:L_PROV").json()
    time.sleep(0.02)
    b = _post(rich, "hold", f"pin:{a['pin_id']}").json()
    time.sleep(0.02)
    c = _post(rich, "forget_learned", "strand:conv-a").json()
    time.sleep(0.02)
    d = _post(rich, "purge", "strand:conv-b", confirm="conv-b").json()
    time.sleep(0.02)
    f = _correct(rich, "wrong", "L_PROV").json()
    assert _undo(rich, b).status_code == 200
    rows = rich.client.get("/api/memory/corrections").json()["corrections"]
    assert [r["correction_id"] for r in rows] == [x["correction_id"] for x in (f, d, c, b, a)]
    assert [r["undone"] for r in rows] == [False, False, False, True, False]
    for r in rows:
        assert set(r) == {"correction_id", "ts", "action", "target", "landmark_id", "claim", "undone", "undo_until"}
    by = {r["action"]: r for r in rows}
    assert by["pin"]["target"] == "claim:L_PROV" and by["pin"]["claim"] == "The release notes live in docs"
    assert by["hold"]["target"] == f"pin:{a['pin_id']}" and by["hold"]["claim"] == "The release notes live in docs"
    assert by["forget_learned"]["target"] == "strand:conv-a" and by["forget_learned"]["landmark_id"] is None
    assert by["purge"]["target"] == "strand:conv-b" and by["purge"]["undo_until"] is None
    assert by["wrong"]["landmark_id"] == "L_PROV"
    assert by["hold"]["undo_until"] == pytest.approx(by["hold"]["ts"] + 600)


# -- plans ------------------------------------------------------------------------------------------
def test_every_select_the_pin_and_strand_corrections_run_on_a_big_table_is_a_search(rich, monkeypatch):
    monkeypatch.setattr(strand_ids, "_is_conversation", lambda cid: str(cid).startswith("conv-"))
    seen: list[str] = []
    rich.conn.set_trace_callback(lambda s: seen.append(s) if s.lstrip().upper().startswith(("SELECT", "WITH")) else None)
    pinned = _post(rich, "pin", "claim:L_PROV").json()
    _post(rich, "pin", "turn:conv-a:t1")
    _post(rich, "pin", "artifact:doc-1")
    h = _post(rich, "hold", f"pin:{rich.pins['note']}").json()
    _post(rich, "release", f"pin:{rich.pins['held']}")
    u = _post(rich, "unpin", f"pin:{rich.pins['note']}").json()
    _undo(rich, u)
    _undo(rich, h)
    _undo(rich, pinned)
    f1 = _post(rich, "forget_learned", "strand:conv-a").json()
    _post(rich, "forget_learned", "strand:conv-a")
    _undo(rich, f1)
    _post(rich, "purge", "strand:conv-a", confirm="conv-a")
    rich.client.get("/api/memory/corrections")
    corrections.forgotten_strands(rich.conn)
    chain_timeline(rich.conn, "conv-a")
    _settle(rich)
    rich.conn.set_trace_callback(None)
    big = ("memory_events", "memory_chain", "episodes", "mycelium_pin_links", "document_data")
    stmts = [s for s in seen if any(re.search(rf"\bFROM {t}\b", s) for t in big)]
    assert len(stmts) >= 20, len(stmts)
    con, bad = sqlite3.connect(rich.path), []
    for sql in stmts:
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql)]
        for t in (t for t in big if re.search(rf"\bFROM {t}\b", sql)):
            if not any(line.startswith(f"SEARCH {t}") for line in plan) or any(line.startswith(f"SCAN {t}") for line in plan):
                bad.append((" ".join(sql.split())[:150], plan))
    con.close()
    assert not bad, bad[:3]


def test_forget_and_purge_refuse_a_thread_that_is_not_one_conversation(env):
    """A shared thread id ("session_iris": the chat connection's own; "voice_headless") carries many conversations'
    rows. Taken literally, forget / purge would hit all of them (2026-10-25). Only a chat conversation qualifies."""
    n = _count(env)
    for action, extra in (("forget_learned", {}), ("purge", {"confirm": "session_iris"})):
        r = env.client.post("/api/memory/correct", json={"action": action, "target": "strand:session_iris", **extra})
        assert r.status_code == 409, (action, r.text)
    assert _count(env) == n


def test_every_recall_path_leaves_a_forgotten_strand_out(rich, monkeypatch):
    """Until 2026-10-26 a forget reached the chain recall only: the forgotten conversation's episodes still came back
    as "similar episodes" / "past failures" in every plan, and its research as "prior research"."""
    from backend.agent import research_memory
    from backend.memory import episodic

    c = rich.conn
    try:
        c.execute("ALTER TABLE episodes ADD COLUMN embedding_backend TEXT")
    except sqlite3.OperationalError:
        pass
    for sid in ("conv-a", "conv-b"):
        for kind, score in (("success", 0.9), ("failure", 0.1)):
            c.execute("INSERT INTO episodes (id, session_id, task_summary, outcome_score, outcome_type, failure_reason,"
                      " embedding, embedding_backend) VALUES (?, ?, ?, ?, ?, ?, ?, 'bge-m3')",
                      (f"ep-{sid}-{kind}", sid, f"task of {sid}", score, kind, "boom" if kind == "failure" else None,
                       b"[1.0, 0.0, 0.0]"))
    c.commit()

    class _Meta:
        vector, backend = [1.0, 0.0, 0.0], "bge-m3"

    store = object.__new__(episodic.EpisodicStore)
    store._db = c
    store._embed = type("E", (), {"encode_with_meta": lambda self, _t: _Meta()})()
    store._mycelium = None
    monkeypatch.setattr(episodic, "get_reindex_manager", lambda: None)

    def _sessions(rows):
        return {r["task_summary"].rsplit(" ", 1)[-1] for r in rows}

    assert _sessions(store.retrieve_similar("task", limit=10, min_score=0.0)) == {"conv-a", "conv-b"}
    d = _post(rich, "forget_learned", "strand:conv-a").json()
    assert _sessions(store.retrieve_similar("task", limit=10, min_score=0.0)) == {"conv-b"}
    assert _sessions(store.retrieve_failures("task", limit=10)) == {"conv-b"}

    recs = {"r-a": {"job_id": "j-a", "conversation_id": "conv-a", "session_id": "conv-a", "text": "a"},
            "r-b": {"job_id": "j-b", "conversation_id": "conv-b", "session_id": "conv-b", "text": "b"}}
    store.retrieve_context_chunks = lambda *_a, **_k: [f"[research r-a]", f"[research r-b]"]
    monkeypatch.setattr(research_memory, "_HEADER_RE", re.compile(r"\[(research) ([\w-]+)\]"))
    monkeypatch.setattr(research_memory, "load_record", lambda rid, mi=None: recs.get(rid))
    monkeypatch.setattr(research_memory, "_record_body", lambda rec: rec["text"])
    mi = type("MI", (), {"episodic": store})()
    got = research_memory.recall_prior_research("q", limit=5, mi=mi)
    assert [r["job_id"] for r in got] == ["j-b"]

    assert _undo(rich, d).status_code == 200
    assert _sessions(store.retrieve_similar("task", limit=10, min_score=0.0)) == {"conv-a", "conv-b"}
    assert [r["job_id"] for r in research_memory.recall_prior_research("q", limit=5, mi=mi)] == ["j-a", "j-b"]
