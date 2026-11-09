"""A REPORT fact is covered by tool OUTPUT that carries it, whatever the exit code.

MEASURED 2026-11-09 (c14_run_and_report, "Run the tests in this project and
tell me exactly how many of them fail. Do not fix anything"): every step ran
pytest and printed "3 failed, 4 passed", every step settled UNVERIFIED, and
the only UNVERIFIED credit needed a PASSING run. A red run is the answer to
this ask, so C stayed 0.000, the streak-gate fired coverage_stall and the
turn re-planned two steps that ran pytest again (reply 156 s). 14 of the 15
logged stalls that carry a fact diagnostic had this shape.

Pins:
  * a ran-and-exited-non-zero run whose OUTPUT carries the fact covers it;
  * a call that did not RUN ("[tool error]") is never evidence;
  * the model's summary is never evidence (only the Output section is read);
  * a change fact still needs a change or a passing run (unchanged).
"""
from backend.agent.goal_contract import Contract, mark_coverage
from backend.agent.node_executor import NodeResult

_FACT = "tell me exactly how many of them fail. Do not fix anything"


def _red_run(out="collected 7 items\n...F.F.F\n3 failed, 4 passed in 0.09s",
             ok_call=True):
    return NodeResult(
        True, "I ran the suite.",
        calls=[{"tool": "run_command", "target": "python -m pytest -q",
                "ok": False, "ok_call": ok_call, "out": out}],
        last_command_failed=True,
    ).as_step_result()


def test_a_red_run_that_prints_the_answer_covers_the_report_fact():
    res = _red_run()
    assert "exited non-zero" in res
    cov = mark_coverage(Contract(required=(_FACT,)), ["UNVERIFIED"], [res])
    assert _FACT in cov.covered, res
    assert cov.C == 1.0


def test_the_final_run_survives_a_long_early_output():
    """Live c14 2026-11-09: get_system_info and a stray long run filled the
    1200-char Output budget first, the final "3 failed" run was cut, the fact
    stayed open (one cover push, reply 300 s). The budget fills newest-first."""
    res = NodeResult(
        True, "I ran the suite.",
        calls=[{"tool": "get_system_info", "target": "", "ok": True,
                "ok_call": True, "out": "x" * 1500},
               {"tool": "run_command", "target": "python -m pytest -q",
                "ok": False, "ok_call": True, "out": "3 failed, 4 passed in 0.09s"}],
        last_command_failed=True,
    ).as_step_result()
    cov = mark_coverage(Contract(required=(_FACT,)), ["UNVERIFIED"], [res])
    assert _FACT in cov.covered, res[-400:]
    assert res.index("[get_system_info]") < res.index("[run_command]"), "call order kept"


def test_a_run_ask_is_covered_by_a_run_that_executed():
    """Live c14 2026-11-09: 'The project is in <path>. Run the tests in this
    project' stayed open - `pytest -q` prints no path and none of its words."""
    fact = r"The project is in C:\Temp\iris-evals\x\c14. Run the tests in this project"
    res = _red_run(out="..F.F.F\n3 failed, 4 passed in 0.09s")
    cov = mark_coverage(Contract(required=(fact,)), ["UNVERIFIED"], [res])
    assert fact in cov.covered
    not_run = _red_run(out="could not start command", ok_call=False)
    cov = mark_coverage(Contract(required=(fact,)), ["UNVERIFIED"], [not_run])
    assert cov.C == 0.0


def test_a_call_that_did_not_run_is_not_evidence():
    res = _red_run(out="'pytest' failed to start: executable not found",
                   ok_call=False)
    assert "[run_command error]" in res
    cov = mark_coverage(Contract(required=(_FACT,)), ["UNVERIFIED"], [res])
    assert cov.C == 0.0


def test_the_summary_is_not_evidence():
    res = NodeResult(
        True, "3 tests fail, I did not fix anything.",
        calls=[{"tool": "run_command", "target": "python -m pytest -q",
                "ok": False, "ok_call": True}],
        last_command_failed=True,
    ).as_step_result()
    assert "Output:" not in res
    cov = mark_coverage(Contract(required=(_FACT,)), ["UNVERIFIED"], [res])
    assert cov.C == 0.0


def test_failed_still_never_credits():
    cov = mark_coverage(Contract(required=(_FACT,)), ["FAILED"], [_red_run()])
    assert cov.C == 0.0


def test_a_change_fact_still_needs_a_change_or_a_passing_run():
    fact = "Fix the bug in calc.py so the tests pass"
    cov = mark_coverage(Contract(required=(fact,)), ["UNVERIFIED"],
                        [_red_run(out="calc.py 3 failed")])
    assert cov.C == 0.0
