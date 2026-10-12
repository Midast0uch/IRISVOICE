"""browser_next (2026-10-11): the element-choice shadow consumer's boundary.

The question's answer must be IN the state: the goal plus the SAME numbered
element list the tool model read. These pins keep it that way - the labels are
the options, the page head is the state, and an element the list never offered
is unscoreable (no row), never scored wrong.
"""

from __future__ import annotations

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

    def __init__(self):
        self.calls = []

    def decide(self, consumer_id, options, frame):
        self.calls.append((consumer_id, list(options), dict(frame)))
        return DecisionScore(
            consumer_id=consumer_id, chosen="2", confidence=0.8,
            distribution=tuple(CandidateScore(o, -0.1, 0.8 if o == "2" else 0.1)
                               for o in options),
            engine_latency_ms=1)


class _Lane:
    def submit(self, _name, job):
        job()
        return True


def test_parse_page_splits_head_and_numbered_elements():
    head, els = bn.parse_page(PAGE)
    assert head.startswith('Page: "Python - Wikipedia"') and "Elements" not in head
    assert els == [("1", "link: Main page"), ("2", "link: History (off screen)"),
                   ("3", "textbox: Search Wikipedia")]
    assert bn.parse_page("read_file: 12 lines") == ("", [])


def test_the_options_are_the_page_elements_and_the_row_pairs_the_models_pick(monkeypatch):
    import backend.utils.durability_queue as dq

    monkeypatch.setattr(dq, "lane", lambda _n: _Lane())
    rows, eng = [], _Engine()
    bn.set_row_sink(rows.append)
    try:
        assert bn.record_browser_next(goal="open the History section", page_text=PAGE,
                                      element_id=2, action="click", engine=eng)
    finally:
        bn.set_row_sink(None)
    cid, options, frame = eng.calls[0]
    assert cid == "browser_next" and options == ["1", "2", "3"]
    assert frame["option_criteria"] == {"1": "link: Main page", "2": "link: History (off screen)",
                                        "3": "textbox: Search Wikipedia"}
    # the page head renders as state; the element labels do not (they are options)
    text = de.job_input("browser_next", frame).text
    assert "Python - Wikipedia" in text and "Search Wikipedia" not in text
    row = rows[0]
    assert row["consumer_id"] == "browser_next" and row["chosen"] == "2"
    assert row["brain_choice"] == "2" and row["criteria_version"] == "browser_next/v1"


def test_an_element_off_the_list_or_no_list_writes_no_row():
    eng = _Engine()
    assert not bn.record_browser_next(goal="g", page_text=PAGE, element_id=9,
                                      action="click", engine=eng)
    assert not bn.record_browser_next(goal="g", page_text="no list here", element_id=1,
                                      action="click", engine=eng)
    assert eng.calls == []


def test_browser_next_is_a_declared_choice_on_the_route_job():
    assert de.declared_type("browser_next") == "choice"
    assert de.oracle_job("browser_next").name == "route"
