"""A node that did one of three asked facts does not cover all three.

Live 2026-10-04 (eval r09, conv-701 / conv-733): "Look up three separate facts
... give each one: the height of the Eiffel Tower in metres, the year the Golden
Gate Bridge opened, and the year the first Harry Potter book was published."
The one node searched the Eiffel Tower only and closed. Three faults let the
reply go out with 2 of 3 facts missing:
  1. the extractor put the Eiffel Tower and the Golden Gate Bridge in ONE fact
     and kept the lead-in "Look up three separate facts on the web" as a fact;
  2. coverage took ANY word of a fact - "year" (shared by two facts) and
     "height" covered all three, C=1.000;
  3. physics COMPRESS (rec=1) skipped the continuation consult, so an open
     fact got no step even when C was right.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.agent import goal_contract as gc
from backend.agent.agent_kernel import AgentKernel

R09 = (
    "Look up three separate facts on the web and give each one: the height of "
    "the Eiffel Tower in metres, the year the Golden Gate Bridge opened, and the "
    "year the first Harry Potter book was published."
)
# conv-733's step result, word for word (node_executor as_step_result)
CONV_733 = (
    "Searched for Eiffel Tower height\n\nActions:\n"
    "- search height of the Eiffel Tower in metres -> ok"
)


def test_a_listed_ask_is_one_fact_per_item_without_its_lead_in():
    assert gc.extract_required(R09) == (
        "the height of the Eiffel Tower in metres",
        "the year the Golden Gate Bridge opened",
        "the year the first Harry Potter book was published",
    )


def test_a_list_inside_a_call_or_after_a_sentence_end_is_not_split():
    facts = gc.extract_required(
        "Create inventory.py. add(name, qty) adds stock, remove(name, qty) "
        "removes stock. Example: f('a, b, c') returns 3"
    )
    assert not any(f.startswith("qty)") for f in facts)
    assert "Example" in " ".join(facts)


def test_one_searched_fact_covers_only_itself():
    cov = gc.mark_coverage(
        gc.Contract(required=gc.extract_required(R09)), ["VERIFIED"], [CONV_733]
    )
    assert cov.covered == ("the height of the Eiffel Tower in metres",)
    assert abs(cov.C - 1 / 3) < 1e-9


def test_shared_words_in_a_prior_research_block_cover_nothing_else():
    """conv-789 (2026-10-05): the Eiffel Tower search text carried a PRIOR
    RESEARCH block with "First floor", "published", "Gate" and "Bridge"; own
    words covered all three facts. A fact with a name needs the name."""
    text = CONV_733 + (
        "\nPRIOR RESEARCH (earlier searches close to this one):\n- 2026-10-05 "
        "\"Eiffel Tower height metres\": | First floor | 187 feet | Gate 3 | "
        "first published on the official site | the Bridge of Iena |"
    )
    cov = gc.mark_coverage(
        gc.Contract(required=gc.extract_required(R09)), ["VERIFIED"], [text]
    )
    assert cov.covered == ("the height of the Eiffel Tower in metres",)


def test_code_names_and_quoted_examples_are_not_names():
    assert gc._names_in("Running python app.py fails with an ImportError") == []
    assert gc._names_in("Example: slugify('Hello, World!') returns 'hello'") == []
    # conv-811: the eval work folder gave "users", "local", "temp"
    assert gc._names_in(
        r"The project is in C:\Users\midas\AppData\Local\Temp\iris-evals\c02. "
        "Add a function slugify(text) to textutils.py"
    ) == []
    assert gc._names_in("the year the Golden Gate Bridge opened") == ["golden gate bridge"]


def test_all_three_found_cover_all_three():
    reply = (
        "The Eiffel Tower is 330 metres tall. The Golden Gate Bridge opened in "
        "1937. Harry Potter and the Philosopher's Stone was first published in 1997."
    )
    cov = gc.mark_coverage(
        gc.Contract(required=gc.extract_required(R09)), ["VERIFIED"], [reply]
    )
    assert cov.C == 1.0


def test_an_open_fact_gives_a_cover_step():
    k = AgentKernel.__new__(AgentKernel)
    k._goal_contract_state = {
        "contract": SimpleNamespace(required=["fact a", "fact b"]),
        "covered": ["fact a"], "blocked": [],
    }
    k._der_note_depth_route = lambda *_a: None
    step = AgentKernel._goal_contract_cover_step(k)
    assert step == {"description": "Cover the open required fact: fact b"}
    # a stand-in kernel (no contract dict) never gets a step
    assert AgentKernel._goal_contract_cover_step(MagicMock()) is None


def test_a_step_added_after_planning_still_marks_coverage():
    """conv-836 (2026-10-05): the cover step searched the Golden Gate Bridge,
    but continuation/recovery/replan steps had no node record, and coverage
    is marked on the record - the fact stayed open, was pushed again and
    blocked. Finalize gives a record-less step its record BEFORE marking."""
    import inspect

    src = inspect.getsource(AgentKernel._der_finalize_step)
    i = src.index('_rec = getattr(item, "node_record", None)')
    j = src.index("_gc_mod2.mark_coverage(", i)
    assert "if _rec is None:" in src[i:j]
    assert "item.node_record = _rec" in src[i:j]


def test_compress_does_not_skip_an_open_fact():
    import inspect

    src = inspect.getsource(AgentKernel)
    gate = src[src.index("continuation consult skipped during COMPRESS"):]
    gate = gate[: gate.index("_der_plan_next_step(")]
    assert "_goal_contract_cover_step(self)" in gate
    assert "_cover_push or self._der_plan_next_step(" in src
