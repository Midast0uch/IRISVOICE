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

from backend.memory import corrections
from backend.memory.db import _plain_store_connection
from backend.memory.mycelium import integrity
from backend.memory.mycelium.landmark import LandmarkIndex
from backend.tests.contract.test_memory_api_contract import MEMORY_DDL
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
