"""When the goal contract is met, the continuation consult does not run.

Live 2026-10-02 (run A5, Wikipedia task): C=1.000 (3/3 required facts covered)
at 23:56:37, yet the continuation consult ran (a Brain call), added 2 steps and
a bonus pass chased the agent's own action lines as "ceiling facts" - 46 s
before the same answer. The gate reads _goal_contract_met(); no contract, an
open fact or a blocked fact keeps the consult.
"""
from types import SimpleNamespace

from backend.agent.agent_kernel import AgentKernel


def _k(required, covered, blocked=()):
    k = AgentKernel.__new__(AgentKernel)
    k._goal_contract_state = {
        "contract": SimpleNamespace(required=list(required)),
        "covered": list(covered), "blocked": list(blocked),
    }
    return k


def test_all_required_covered_is_met():
    facts = ["height in metres", "year of the first recorded ascent", "open the article"]
    assert _k(facts, facts)._goal_contract_met() is True


def test_an_open_or_blocked_fact_or_no_contract_is_not_met():
    facts = ["height in metres", "year of the first recorded ascent"]
    assert _k(facts, facts[:1])._goal_contract_met() is False
    assert _k(facts, facts, blocked=[{"fact": "x"}])._goal_contract_met() is False
    k = AgentKernel.__new__(AgentKernel)
    assert k._goal_contract_met() is False
    assert _k([], [])._goal_contract_met() is False


def test_the_continuation_gate_reads_it():
    import inspect

    src = inspect.getsource(AgentKernel)
    gate = src[src.index("[DER] continuation gate: mode="):]
    assert "_goal_contract_met()" in gate[: gate.index("_der_plan_next_step(")]
