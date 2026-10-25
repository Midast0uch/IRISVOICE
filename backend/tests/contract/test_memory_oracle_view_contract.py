"""Contract pin: the data of the Memory surface's Oracle view (phase 5).

  GET /api/memory/oracle   {consumers: [<consumer>...], states}

  consumer = {consumer, state, rows, auroc, ece, ece_oof, precision, threshold, gap, fitted_at,   (phase 0, unchanged)
              job, owner_switch, clauses[9], first_missing, curve, classes, history}
  clause   = {id, met: true|false|null, value, need, words}   ids in order:
             rows, classes, minority, auroc, precision, wilson, rows_above, ece, acting
             null = waived (minority, auroc), not applicable (acting), or not reached (an earlier clause fails first)
  history  = [{at, state}] oldest first, only the CHANGES of state
  oracle_decision tap item = {consumer, job, confidence, chosen, acted, options: [{name, p}], ts}

What this pins, against TEMP bar / calibration / history files behind the real router (as test_memory_api_contract.py):
  * a passing, a failing (first_missing named), a waived and an acting-failing consumer carry the right met / value / need;
  * the limits are the bar's own constants (consumer_bar.py), never copies;
  * the history holds only changes, oldest first; the curve is bounded (<= 24 knots);
  * the live tap carries the top 8 options (sorted) and the job, from BOTH call sites of the one ledger writer
    (record_decision for shadow rows, _record_tool_event for tool_choice rows);
  * save_bar_record appends only changes, caps the file at HISTORY_MAX lines and never raises;
  * the backfill script is idempotent.
The view never switches anything: nothing here writes a bar, a threshold or a flag.
"""
from __future__ import annotations

import importlib.util
import json
import threading
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.agent.consumer_bar as cb
import backend.agent.tool_bridge as tb
import backend.api.memory as api
import backend.gateway.iris_ffi as _ffi
from backend.agent.tool_bridge import AgentToolBridge
from backend.utils import memory_live

CLAUSE_IDS = ["rows", "classes", "minority", "auroc", "precision", "wilson", "rows_above", "ece", "acting"]
ENGINE = "eng|1"
FITTED = "2026-10-24T15:38:01+00:00"


def _bar(status, rows, gap="", **config):
    return {"consumer_id": "x", "status": status, "rows": rows, "ece": 0.02, "precision": 0.93, "gap": gap,
            "config": {"backend_id": ENGINE, **config}}


def _entry(*, rows=1000, correct=900, wrong=100, auroc=0.72, ece=0.02, prec=0.93, wlb=0.91, above=700, t=0.81,
           knots=None, **oof_extra):
    return {"threshold": t, "rows_distinct": rows, "rows_above": above, "classes": {"correct": correct, "wrong": wrong},
            "oof": {"auroc": auroc, "ece": ece, "precision_at_t": prec, "wilson_lb": wlb, **oof_extra},
            "knots": knots if knots is not None else [], "fitted_at": FITTED}


def _knots(n):
    return [[round(0.3 + 0.65 * i / (n - 1), 4), round(0.8 + 0.19 * i / (n - 1), 4)] for i in range(n)]


@pytest.fixture()
def bench(tmp_path, monkeypatch):
    d = tmp_path / "bench"
    d.mkdir()
    monkeypatch.setattr(api, "_BENCH", d)
    monkeypatch.delenv("IRIS_DECISION_ENFORCE", raising=False)
    return d


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _write(bench, bars, entries, history=None):
    (bench / "consumer_bar_record.json").write_text(json.dumps(bars), encoding="utf-8")
    (bench / "oracle_calibration.json").write_text(json.dumps({ENGINE: entries}), encoding="utf-8")
    if history is not None:
        (bench / cb.HISTORY_NAME).write_text("".join(json.dumps(h) + "\n" for h in history), encoding="utf-8")


def _by_id(clauses):
    return {c["id"]: c for c in clauses}


def _get(client):
    r = client.get("/api/memory/oracle")
    assert r.status_code == 200
    return {c["consumer"]: c for c in r.json()["consumers"]}


# ── the clause ladder ─────────────────────────────────────────────────────────────────────────────

def test_a_passing_consumer_shows_nine_clauses_in_order_job_and_the_owner_switch(bench, client, monkeypatch):
    _write(bench, {"tool_choice": _bar("enforced", 1000)}, {"tool_choice": _entry()})
    c = _get(client)["tool_choice"]
    assert c["job"] == "route" and c["owner_switch"] is False and c["first_missing"] is None
    assert [x["id"] for x in c["clauses"]] == CLAUSE_IDS
    k = _by_id(c["clauses"])
    assert [(k[i]["met"], k[i]["value"], k[i]["need"]) for i in CLAUSE_IDS[:8]] == [
        (True, 1000, cb.MIN_ROWS), (True, 100, 1), (True, 0.1, cb.MIN_MINORITY), (True, 0.72, cb.MIN_AUROC),
        (True, 0.93, cb.MIN_PRECISION), (True, 0.91, cb.MIN_WILSON_LB), (True, 700, cb.MIN_ROWS_ABOVE),
        (True, 0.02, cb.MAX_ECE)]
    # not an acting consumer: not applicable, not a failure
    assert k["acting"] == {"id": "acting", "met": None, "value": None, "need": None,
                           "words": k["acting"]["words"]} and "not applicable" in k["acting"]["words"]
    assert all(isinstance(x["words"], str) and x["words"] for x in c["clauses"])
    # the owner's switch is the SAME parser the decision engine reads (IRIS_DECISION_ENFORCE, a csv of known consumers)
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", "narration, tool_choice,not_a_consumer")
    assert _get(client)["tool_choice"]["owner_switch"] is True


def test_the_jobs_of_event_type_and_unassigned_consumers(bench, client):
    bars = {c: _bar("shadow", 5) for c in ("event_type:control", "mystery", "needs_action")}
    _write(bench, bars, {})
    got = _get(client)
    assert (got["event_type:control"]["job"], got["mystery"]["job"], got["needs_action"]["job"]) == \
           ("classify_event", "general", "interpret_step")


def test_a_failing_consumer_names_the_first_missing_clause_in_words(bench, client):
    _write(bench, {"done": _bar("shadow", 600, "oof AUROC 0.62 < 0.65")},
           {"done": _entry(rows=600, auroc=0.62, prec=0.88, wlb=0.80)})
    c = _get(client)["done"]
    k = _by_id(c["clauses"])
    assert c["first_missing"] == "auroc"
    assert (k["auroc"]["met"], k["auroc"]["value"], k["auroc"]["need"]) == (False, 0.62, cb.MIN_AUROC)
    assert k["auroc"]["words"] == f"needs to rank its errors better - AUROC 0.62, needs {cb.MIN_AUROC}"
    # later clauses are judged on their own numbers, not hidden behind the first failure
    assert [k[i]["met"] for i in ("precision", "wilson", "rows_above", "ece")] == [False, False, True, True]
    assert [k[i]["met"] for i in ("rows", "classes", "minority")] == [True, True, True]


def test_a_consumer_below_the_row_floor_has_unreached_clauses_not_invented_numbers(bench, client):
    # fitted on too few rows: the fit wrote nothing honest (no classes, no threshold, no oof)
    _write(bench, {"event_type:control": _bar("shadow", 34, "distinct rows 34 < 100"),
                   "mystery": _bar("shadow", 12, "distinct rows 12 < 100")},
           {"event_type:control": {"rows_distinct": 34}})
    got = _get(client)
    for cid, rows in (("event_type:control", 34), ("mystery", 12)):
        c = got[cid]
        k = _by_id(c["clauses"])
        assert c["first_missing"] == "rows" and (k["rows"]["met"], k["rows"]["value"]) == (False, rows)
        assert all(k[i]["met"] is None and k[i]["value"] is None for i in CLAUSE_IDS[1:8]), cid
        assert "not reached" in k["classes"]["words"]
        assert c["curve"] == [] and c["classes"] is None and c["history"] == []


def test_a_consumer_with_no_error_mass_is_waived_not_failed(bench, client):
    # 79 wrong in 2782 rows excludes a 5% error rate (p <= 0.01): minority + AUROC are untestable, not failed
    _write(bench, {"escalate_incomplete": _bar("enforced", 2782, "no-error-mass waiver: 79 wrong")},
           {"escalate_incomplete": _entry(rows=2782, correct=2703, wrong=79, auroc=0.55, above=2000)})
    c = _get(client)["escalate_incomplete"]
    k = _by_id(c["clauses"])
    assert k["minority"]["met"] is None and k["auroc"]["met"] is None
    assert k["minority"]["words"] == k["auroc"]["words"] == "waived: errors are too rare to rank (79 wrong of 2782)"
    assert k["minority"]["need"] == cb.MIN_MINORITY and k["auroc"]["need"] == cb.MIN_AUROC
    assert k["auroc"]["value"] == 0.55          # shown, not judged
    assert c["first_missing"] is None and [k[i]["met"] for i in ("rows", "classes", "precision", "wilson", "ece")] == [True] * 5
    # thin data is NOT waived: 100 rows with 4 wrong does not exclude a 5% error rate
    _write(bench, {"thin": _bar("shadow", 100)}, {"thin": _entry(rows=100, correct=96, wrong=4, auroc=0.7, above=80)})
    k = _by_id(_get(client)["thin"]["clauses"])
    assert k["minority"]["met"] is False and k["auroc"]["met"] is True


def test_the_acting_clause_applies_only_to_a_consumer_in_acting_enforced(bench, client):
    assert "needs_action" in cb.ACTING_ENFORCED and "tool_approval" not in cb.ACTING_ENFORCED
    acting = dict(acting_answer="no", acting_rows_above=17, acting_precision=0.706, acting_wilson_lb=0.49)
    _write(bench, {"needs_action": _bar("shadow", 111), "tool_approval": _bar("shadow", 111)},
           {"needs_action": _entry(rows=111, **acting), "tool_approval": _entry(rows=111, **acting)})
    got = _get(client)
    k = _by_id(got["needs_action"]["clauses"])
    assert (k["acting"]["met"], k["acting"]["value"], k["acting"]["need"]) == (False, 0.706, cb.MIN_PRECISION)
    assert "'no'" in k["acting"]["words"] and got["needs_action"]["first_missing"] == "acting"
    ta = _by_id(got["tool_approval"]["clauses"])["acting"]
    assert ta["met"] is None and got["tool_approval"]["first_missing"] is None
    # the same consumer, its acting side holding
    good = dict(acting_answer="no", acting_rows_above=60, acting_precision=0.95, acting_wilson_lb=0.89)
    _write(bench, {"needs_action": _bar("enforced", 111)}, {"needs_action": _entry(rows=111, **good)})
    c = _get(client)["needs_action"]
    assert _by_id(c["clauses"])["acting"]["met"] is True and c["first_missing"] is None


def test_the_phase0_keys_are_unchanged(bench, client):
    _write(bench, {"tool_choice": _bar("enforced", 1000)}, {"tool_choice": _entry()})
    d = client.get("/api/memory/oracle").json()
    assert set(d) == {"consumers", "states"} and d["states"] == {"enforced": 1}
    c = d["consumers"][0]
    assert {"consumer", "state", "rows", "auroc", "ece", "ece_oof", "precision", "threshold", "gap",
            "fitted_at"} <= set(c)
    assert (c["auroc"], c["ece_oof"], c["threshold"], c["fitted_at"]) == (0.72, 0.02, 0.81, FITTED)


# ── the curve and the history ──────────────────────────────────────────────────────────────────────

def test_the_curve_is_bounded_evenly_thinned_and_carries_its_classes(bench, client):
    knots = _knots(60)
    _write(bench, {"tool_choice": _bar("enforced", 1000), "done": _bar("shadow", 1000)},
           {"tool_choice": _entry(knots=knots), "done": _entry(knots=_knots(11))})
    got = _get(client)
    curve = got["tool_choice"]["curve"]
    assert len(curve) == 24 and curve[0] == knots[0] and curve[-1] == knots[-1]
    assert all(p in knots for p in curve) and [p[0] for p in curve] == sorted(p[0] for p in curve)
    assert len({tuple(p) for p in curve}) == 24
    assert got["tool_choice"]["classes"] == {"correct": 900, "wrong": 100}
    assert got["done"]["curve"] == _knots(11)          # at most 24: left as it is


def test_the_history_holds_only_changes_oldest_first(bench, client):
    h = [{"at": "2026-10-21T08:00:00+00:00", "consumer": "tool_choice", "status": "shadow", "gap": "g"},
         {"at": "2026-10-12T21:00:00+00:00", "consumer": "tool_choice", "status": "enforced", "gap": ""},   # out of order
         {"at": "2026-10-13T00:00:00+00:00", "consumer": "tool_choice", "status": "enforced", "gap": ""},   # not a change
         {"at": "2026-10-22T14:00:00+00:00", "consumer": "tool_choice", "status": "enforced", "gap": ""},
         {"at": "2026-10-22T14:00:01+00:00", "consumer": "tool_choice", "status": "enforced", "gap": ""},   # not a change
         {"at": "2026-10-05T00:00:00+00:00", "consumer": "done", "status": "shadow", "gap": "g"}]
    _write(bench, {"tool_choice": _bar("enforced", 1000), "done": _bar("shadow", 5)}, {})
    (bench / cb.HISTORY_NAME).write_text("".join(json.dumps(x) + "\n" for x in h) + "not json\n", encoding="utf-8")
    got = _get(client)
    assert got["tool_choice"]["history"] == [
        {"at": "2026-10-12T21:00:00+00:00", "state": "enforced"}, {"at": "2026-10-21T08:00:00+00:00", "state": "shadow"},
        {"at": "2026-10-22T14:00:00+00:00", "state": "enforced"}]
    assert got["done"]["history"] == [{"at": "2026-10-05T00:00:00+00:00", "state": "shadow"}]
    # no history file: an empty list, not an error
    (bench / cb.HISTORY_NAME).unlink()
    assert _get(client)["done"]["history"] == []


# ── the live tap ───────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def live(monkeypatch):
    monkeypatch.delenv("IRIS_MEMORY_LIVE", raising=False)
    monkeypatch.setattr(memory_live, "_start_drain", lambda: None)
    monkeypatch.setattr(memory_live, "_wake", threading.Event())
    memory_live.reset()
    sent: list = []
    memory_live.set_sender(lambda msg: sent.append(msg) or True)
    yield sent
    memory_live.set_sender(None)
    memory_live.reset()


@pytest.fixture()
def ledger(monkeypatch):
    rows: list = []
    monkeypatch.setattr(_ffi, "ffi_ingest_event", lambda **kw: rows.append(kw) or True)
    return rows


def _decisions(sent):
    memory_live.flush_once()
    out = [d for m in sent if m["type"] == "oracle_decision" for d in m["payload"]["decisions"]]
    sent[:] = []
    return out


# 12 candidates in a scrambled order; the two highest sit in the middle
_CANDS = [{"name": f"tool_{i}", "prob": p} for i, p in enumerate(
    [0.01, 0.02, 0.30, 0.03, 0.04, 0.05, 0.20, 0.06, 0.07, 0.08, 0.09, 0.15])]
_TOP8 = [("tool_2", 0.3), ("tool_6", 0.2), ("tool_11", 0.15), ("tool_10", 0.09), ("tool_9", 0.08), ("tool_8", 0.07),
         ("tool_7", 0.06), ("tool_5", 0.05)]


def test_the_tap_carries_options_and_job_from_both_call_sites_of_the_ledger_writer(ledger, live):
    # call site 1: a SHADOW row, written by record_decision (the engine's shadow rows reach it through the kernel sink)
    AgentToolBridge().record_decision(
        {"consumer_id": "needs_action", "engine": "d1", "chosen": "no", "confidence": 0.91, "route": "shadow",
         "candidates": _CANDS, "turn_id": "t-" + uuid.uuid4().hex[:8]}, "shadow", session_id="s-oracle-view")
    # call site 2: a tool_choice row that dispatched a tool (_record_tool_event with a decision block)
    tb._DECISION_META.set({"consumer_id": "tool_choice", "engine": "d1", "chosen": "tool_2", "confidence": 0.8,
                           "route": "engine", "candidates": _CANDS})
    try:
        AgentToolBridge()._record_tool_event("s-oracle-view", "tool_2", "success", {}, {"success": True})
    finally:
        tb._DECISION_META.set(None)
    assert tb._LEDGER_LANE.flush(10.0)
    shadow, enforced = _decisions(live)
    for d, consumer, job, acted in ((shadow, "needs_action", "interpret_step", "shadow"),
                                    (enforced, "tool_choice", "route", "enforced")):
        assert (d["consumer"], d["job"], d["acted"]) == (consumer, job, acted)
        assert [(o["name"], o["p"]) for o in d["options"]] == _TOP8           # top 8, by p, descending
        assert all(set(o) == {"name", "p"} for o in d["options"])
        assert set(d) == {"consumer", "job", "confidence", "chosen", "acted", "options", "ts"}


def test_a_row_without_a_distribution_has_no_options_and_the_row_job_wins(live):
    # tool_choice's own row carries only the menu size (candidates = a count, candidate_names = names without p)
    memory_live.oracle_decision({"consumer_id": "tool_choice", "route": "engine", "chosen": "x", "confidence": 0.9,
                                 "candidates": 12, "candidate_names": ["a", "b"]})
    memory_live.oracle_decision({"consumer_id": "event_type:control", "route": "shadow", "chosen": "y",
                                 "confidence": 0.5, "candidates": [{"name": "y"}, {"prob": 0.2}, "z", {"name": "w", "prob": 0.4}]})
    memory_live.oracle_decision({"consumer_id": "mystery", "job": "row_job", "route": "shadow", "chosen": "y"})
    a, b, c = _decisions(live)
    assert a["options"] == [] and a["job"] == "route"
    assert b["options"] == [{"name": "w", "p": 0.4}] and b["job"] == "classify_event"
    assert c["job"] == "row_job"


# ── the history source: save_bar_record ────────────────────────────────────────────────────────────

def _rec(**statuses):
    return {c: cb.ConsumerBar(consumer_id=c, rows=1, precision=0.5, ece=None, status=s, gap="g:" + s)
            for c, s in statuses.items()}


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_save_bar_record_appends_only_changes(tmp_path):
    p = tmp_path / "consumer_bar_record.json"
    h = tmp_path / cb.HISTORY_NAME
    cb.save_bar_record(_rec(a="shadow", b="enforced"), p)
    assert [(x["consumer"], x["status"]) for x in _lines(h)] == [("a", "shadow"), ("b", "enforced")]
    cb.save_bar_record(_rec(a="shadow", b="enforced"), p)               # nothing changed: nothing appended
    assert len(_lines(h)) == 2
    cb.save_bar_record(_rec(a="shadow", b="shadow", c="sampled"), p)    # b demoted, c new, a unchanged
    got = _lines(h)[2:]
    assert [(x["consumer"], x["status"], x["gap"]) for x in got] == [("b", "shadow", "g:shadow"), ("c", "sampled", "g:sampled")]
    assert all(set(x) == {"at", "consumer", "status", "gap"} and x["at"] for x in got)
    cb.save_bar_record(_rec(a="shadow", b="enforced", c="sampled"), p)  # b earned again: a change
    assert [(x["consumer"], x["status"]) for x in _lines(h)[4:]] == [("b", "enforced")]


def test_the_history_file_is_capped_at_the_last_5000_lines(tmp_path):
    assert cb.HISTORY_MAX == 5000
    p, h = tmp_path / "consumer_bar_record.json", tmp_path / cb.HISTORY_NAME
    old = [{"at": f"2026-01-01T00:00:{i % 60:02d}+00:00", "consumer": f"old{i}", "status": "shadow", "gap": ""}
           for i in range(4999)]
    h.write_text("".join(json.dumps(x) + "\n" for x in old), encoding="utf-8")
    cb.save_bar_record(_rec(n1="shadow", n2="enforced", n3="sampled"), p)      # three new lines: 5002 -> the last 5000
    got = _lines(h)
    assert len(got) == 5000
    assert [x["consumer"] for x in got[-3:]] == ["n1", "n2", "n3"] and got[0]["consumer"] == "old2"


def test_a_history_failure_never_fails_the_save(tmp_path):
    p = tmp_path / "consumer_bar_record.json"
    (tmp_path / cb.HISTORY_NAME).mkdir()                 # the history path is a directory: every write to it raises
    cb.save_bar_record(_rec(a="shadow"), p)              # must not raise
    assert json.loads(p.read_text(encoding="utf-8"))["a"]["status"] == "shadow"


# ── the backfill ───────────────────────────────────────────────────────────────────────────────────

def _load_backfill():
    spec = importlib.util.spec_from_file_location(
        "backfill_consumer_bar_history",
        Path(__file__).resolve().parents[3] / "scripts" / "backfill_consumer_bar_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_backfill_writes_changes_once_and_a_rerun_writes_nothing(tmp_path, monkeypatch, capsys):
    bf = _load_backfill()
    h = tmp_path / cb.HISTORY_NAME
    versions = [("2026-10-05T10:00:00+00:00", {"a": {"status": "shadow", "gap": "g1"}, "b": {"status": "shadow", "gap": ""}}),
                ("2026-10-12T10:00:00+00:00", {"a": {"status": "enforced", "gap": ""}, "b": {"status": "shadow", "gap": ""}}),
                ("2026-10-21T10:00:00+00:00", {"a": {"status": "shadow", "gap": "g2"}, "b": {"status": "shadow", "gap": ""},
                                               "c": {"status": "shadow", "gap": ""}})]
    monkeypatch.setattr(bf, "git_versions", lambda: versions)
    monkeypatch.setattr(bf, "history_path", lambda *_: h)
    assert bf.main([]) == 0
    first = h.read_bytes()
    assert [(x["at"][:10], x["consumer"], x["status"]) for x in _lines(h)] == [
        ("2026-10-05", "a", "shadow"), ("2026-10-05", "b", "shadow"), ("2026-10-12", "a", "enforced"),
        ("2026-10-21", "a", "shadow"), ("2026-10-21", "c", "shadow")]       # b never changed: one line
    capsys.readouterr()
    assert bf.main([]) == 0
    assert h.read_bytes() == first and "0 line(s) to add" in capsys.readouterr().out
    # a line the app appended since stays, and a third run still writes nothing
    live_line = {"at": "2026-10-25T00:00:00+00:00", "consumer": "a", "status": "enforced", "gap": ""}
    h.write_bytes(first + (json.dumps(live_line) + "\n").encode())
    assert bf.main([]) == 0
    assert _lines(h)[-1] == live_line and len(_lines(h)) == 6


def test_the_backfill_reads_the_real_git_versions_oldest_first():
    bf = _load_backfill()
    versions = bf.git_versions()
    assert len(versions) >= 2 and [v[0] for v in versions] == sorted(v[0] for v in versions)
    assert all(isinstance(rec, dict) for _, rec in versions)
