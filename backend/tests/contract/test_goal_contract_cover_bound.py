"""The "cover the open required fact" push cannot loop (2026-10-01).

Measured (eval c06, reply 366 s vs the 64 s standard): the prompt's rule "do
not change app.py" became a REQUIRED FACT. A prohibition is kept by not
acting, so no step result could cover it (its only distinctive term is
"change"), and the continuation pushed "Cover the open required fact: do not
change app.py" 36 times. Two guards:
  1. a prohibition is not a deliverable (extract_required drops it);
  2. a fact that pushes cannot cover is BLOCKED (no_progress) after
     GOAL_COVER_PUSH_MAX pushes, so the turn can end and report it.
"""
from __future__ import annotations

from backend.agent.der_constants import GOAL_COVER_PUSH_MAX
from backend.agent.goal_contract import extract_required

_C06 = (
    "The project is in C:/tmp/c06. Running python app.py fails with an "
    "ImportError. Fix the shapes package so app.py runs. Keep the public names "
    "area_circle and area_square, and do not change app.py."
)


def test_prohibition_is_not_a_required_fact():
    facts = [f.lower() for f in extract_required(_C06)]
    assert not [f for f in facts if f.startswith(("do not", "and do not"))], facts
    assert any("area_circle" in f for f in facts), "deliverables must stay"


def test_cover_push_is_bounded_per_fact():
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "c"
    k._goal_contract_state = {"blocked": [], "counters": {}}
    open_facts = ["fact that no step can cover", "second fact"]
    for _ in range(GOAL_COVER_PUSH_MAX):
        assert k._goal_contract_bound_cover_push(list(open_facts))[0] == open_facts[0]
    # Past the bound the first fact is blocked and the next one is pushed.
    assert k._goal_contract_bound_cover_push(list(open_facts)) == ["second fact"]
    blocked = k._goal_contract_state["blocked"]
    assert blocked[0]["fact"] == open_facts[0]
    assert blocked[0]["reason"] == "no_progress"
    for _ in range(GOAL_COVER_PUSH_MAX - 1):
        k._goal_contract_bound_cover_push(["second fact"])
    assert k._goal_contract_bound_cover_push(["second fact"]) == [], (
        "every fact exhausted: nothing left to push, the turn may end")
