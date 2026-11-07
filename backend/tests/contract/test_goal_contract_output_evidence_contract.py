"""A passing run with REAL tool OUTPUT credits a BEHAVIOR fact from UNVERIFIED.

MEASURED 2026-11-06 (c02_add_slugify): two behavior facts stayed open on every
UNVERIFIED step; C stalled at 0.333 and the streak-gate re-planned three steps
that redid the work (380 s reply against a 52.9 s standard). The evidence the
coverage could not see was the tool OUTPUT ("2 passed", "hello-world").

The discriminator is the ``Output:`` section: it exists only when a call
carried real output, so it is outside the model's summary (which echoes the
goal). The pinned forbidden case - a summary echo plus a passing run and NO
output - still must not credit.
"""
from backend.agent.goal_contract import Contract, mark_coverage
from backend.agent.node_executor import NodeResult

_FACT = ("replaces every run of characters that are not letters or digits "
         "with a single hyphen")


def _result_with_output():
    return NodeResult(
        True, "Verified slugify.",
        calls=[{
            "tool": "run_command",
            "target": "python slug_check.py",
            "ok": True,
            "out": "slugify('Hello, World!') -> hello-world\n2 passed",
        }],
    ).as_step_result()


def test_output_evidence_credits_a_behavior_fact_from_unverified():
    res = _result_with_output()
    assert "Output:" in res
    cov = mark_coverage(Contract(required=(_FACT,)), ["UNVERIFIED"], [res])
    assert _FACT in cov.covered
    assert cov.C == 1.0


def test_no_output_section_does_not_credit():
    res = NodeResult(
        True, "Verified slugify.",
        calls=[{"tool": "run_command", "target": "python slug_check.py", "ok": True}],
    ).as_step_result()
    assert "Output:" not in res
    cov = mark_coverage(Contract(required=(_FACT,)), ["UNVERIFIED"], [res])
    assert _FACT not in cov.covered


def test_failed_never_credits():
    cov = mark_coverage(Contract(required=(_FACT,)), ["FAILED"], [_result_with_output()])
    assert _FACT not in cov.covered


def test_the_summary_echo_alone_still_does_not_credit():
    plain = "Bun vs Deno\n\nActions:\n- run_command python x.py -> ok"
    cov = mark_coverage(Contract(required=("compare Bun vs Deno",)), ["UNVERIFIED"], [plain])
    assert cov.C == 0.0
