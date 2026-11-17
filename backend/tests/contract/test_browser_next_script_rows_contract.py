"""browser_next rows from a Workbench script (Round 6, C4, shadow).

A script's browser_act runs on a callback thread where the node's scope
(turn_id / step_id) is unset, so the caller captures it and passes it in, with
via="run_python". Without a scope or via the row is what it always was.
"""

from __future__ import annotations

import threading

from backend.agent import browser_next_shadow as bn
from backend.agent import decision_engine as de
from backend.agent.decision_engine import CandidateScore, DecisionScore

PAGE = (
    'Page: "Python - Wikipedia" - https://en.wikipedia.org/wiki/Python\n'
    "Text: Python is a programming language ...\n"
    "Elements (pass the number as element_id to browser_act):\n"
    "[1] link: Main page\n"
    "[2] link: History (off screen)\n"
    "[3] textbox: Search Wikipedia"
)


class _Engine:
    model_id = "stub"

    def decide(self, consumer_id, options, frame):
        return DecisionScore(
            consumer_id=consumer_id, chosen="2", confidence=0.8,
            distribution=tuple(CandidateScore(o, -0.1, 0.8 if o == "2" else 0.1)
                               for o in options),
            engine_latency_ms=1)


class _Lane:
    def submit(self, _name, job):
        job()
        return True


def _record(monkeypatch, **kw):
    import backend.utils.durability_queue as dq

    monkeypatch.setattr(dq, "lane", lambda _n: _Lane())
    rows = []
    bn.set_row_sink(rows.append)
    try:
        assert bn.record_browser_next(goal="open the History section", page_text=PAGE,
                                      element_id=2, action="click", engine=_Engine(), **kw)
    finally:
        bn.set_row_sink(None)
    return rows


def test_a_script_row_carries_the_given_scope_and_via_from_a_non_node_thread(monkeypatch):
    given = {"turn_id": "t-1", "step_id": "s-1", "node_exec_id": "n-1"}
    out = {}

    def _worker():
        out["rows"] = _record(monkeypatch, scope=given, via="run_python")

    th = threading.Thread(target=_worker)
    th.start()
    th.join(10)
    rows = out["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["turn_id"] == "t-1" and row["step_id"] == "s-1" and row["node_exec_id"] == "n-1"
    assert row["via"] == "run_python"
    assert row["consumer_id"] == "browser_next" and row["job"] == "route"
    assert row["criteria_version"] == "browser_next/v1" and row["shadow"] is True


def test_a_given_scope_wins_over_the_ambient_one(monkeypatch):
    monkeypatch.setattr(bn, "_scope_now", lambda: {"turn_id": "ambient"})
    rows = _record(monkeypatch, scope={"turn_id": "given"}, via="run_python")
    assert rows[0]["turn_id"] == "given"


def test_without_scope_or_via_the_row_is_unchanged(monkeypatch):
    monkeypatch.setattr(bn, "_scope_now", lambda: {"turn_id": "ambient", "step_id": "s0"})
    row = _record(monkeypatch)[0]
    assert "via" not in row
    assert row["turn_id"] == "ambient" and row["step_id"] == "s0"
    state = de.job_input("browser_next", {
        "goal": "open the History section", "done_when": None, "calls_this_step": None,
        "last_result": bn.parse_page(PAGE)[0][:800],
        "option_criteria": {e: l for e, l in bn.parse_page(PAGE)[1]}}).text
    assert set(row) == {
        "consumer_id", "job", "chosen", "confidence", "candidates", "n_options",
        "engine_latency_ms", "brain_choice", "action", "shadow", "criteria_version",
        "state", "brain_ok", "input_key", "turn_id", "step_id"}
    assert row["state"] == state[:2000] and row["brain_ok"] is None
    assert row["brain_choice"] == "2" and row["action"] == "click"


def test_a_stored_script_rows_state_replays_to_the_same_input_key(monkeypatch):
    rows = _record(monkeypatch, scope={"turn_id": "t"}, via="run_python")
    row = rows[0]
    assert row["input_key"] and row["input_key"] == bn._browser_input_key(row["state"])
