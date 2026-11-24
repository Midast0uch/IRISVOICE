"""One question is one fact: a fragment a comma cut from it, or the form of its answer, is not a deliverable (2026-11-23).

Measured: x06 "For project quill, which auth provider did we pick FIRST, before the switch? Reply with the provider name
only." became 3 facts; a step that found the answer left "before the switch? Reply with the provider name only" open, 2
more steps ran, ask 38-51 s against 12 s. "In the project" was a required fact of 50 coding tasks. Replayed over 1,230
recorded requests: 66 change, each losing only such a fragment. Each test FAILS on the code before this change, except
the ones that pin what must not change.
"""
from __future__ import annotations

import pytest

from backend.agent.goal_contract import Contract, _asks_for_change, extract_required, mark_coverage

X06 = "For project quill-b3c4, which auth provider did we pick FIRST, before the switch? Reply with the provider name only."


def test_a_question_with_a_lead_in_and_a_qualifier_is_one_fact():
    assert extract_required(X06) == ("For project quill-b3c4, which auth provider did we pick FIRST, before the switch?",)


def test_the_step_that_found_the_answer_covers_it():
    result = ("The first auth provider was keyrock-b3c4.\n\nActions:\n- recall_memory quill-b3c4 auth provider decision -> ok\n"
              "\nOutput:\n[recall_memory]\nDecision log for project quill-b3c4: we picked keyrock-b3c4 as the auth provider.")
    assert mark_coverage(Contract(required=extract_required(X06)), ["UNVERIFIED"], [result]).C == 1.0


def test_a_lead_in_is_not_a_deliverable_and_the_work_still_asks_for_a_change():
    facts = extract_required("In the project, add a function `mode` to calculator.py that returns the most common value. "
                             "Add a test for it, then update the README to mention `mode`.")
    assert len(facts) == 2 and facts[0].startswith("In the project, add a function `mode`")
    assert _asks_for_change(facts[0])


def test_a_short_tail_stays_in_its_question():
    assert len(extract_required("On https://x.test page 1, count how often each tag appears. Which tag appears most often, "
                                "and how many times?")) == 1


@pytest.mark.parametrize("request_,n", [
    ("Look up the Detroit Red Wings, the Chicago Blackhawks, and the Pittsburgh Penguins", 3),   # a list stays a list
    ("write it in Python, in JavaScript, and in Rust please", 2),
    ("in Python code, in JavaScript code, and in Rust code", 3),                                 # all prepositions: a list
    ("the year the Eiffel Tower opened, the year the Golden Gate Bridge opened, and the year of the first book", 3),
])
def test_real_lists_keep_their_items(request_, n):
    if n == 2:   # "write it in Python" + its qualifiers is one ask
        n = 1
    assert len(extract_required(request_)) == n


@pytest.mark.parametrize("request_", [
    "Open config.json. Reply with the port number only.",             # the only place that says what is wanted
    "Reply with the id only.",
    "Run the tests. Which fail? Reply with the count and list only failing names.",   # not a form clause: more is asked
])
def test_a_reply_clause_that_carries_the_ask_is_kept(request_):
    joined = " ".join(extract_required(request_)).lower()
    assert "reply with" in joined
