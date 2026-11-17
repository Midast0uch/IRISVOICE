"""A code step whose harness check PASSED covers the facts its manifest answers.

MEASURED (TG-7 v2 stage 1, conv-7816/7840 c47): the step result of a passed
Workbench check is the outputs MANIFEST (node_executor `_manifest_only`):
purpose, "Outputs:", "name = value" lines, "check: passed". It has no Actions
or Output section, so mark_coverage left both required facts open (covered=0
required=2), the Explorer added "Cover the open required fact" and a second
plan re-read the file. Gap opens 36 with the harness check on vs 23 off.

Pins:
  * one manifest step with both values and "check: passed" covers both facts;
  * the same text with "check: failed", or with no check line, is not credited;
  * a result with no manifest (flag off) is judged as before.
"""
from backend.agent import goal_contract
from backend.agent.goal_contract import Contract, mark_coverage

_F1 = "Report the total revenue of all orders in orders.csv"
_F2 = "Report the largest single order amount in orders.csv"
_BODY = ("Compute revenue and the largest order\n\nOutputs:\n"
         "total_revenue = 48213.5\nlargest_order_amount = 9120.0\n\n")


def _cov(result, label="UNVERIFIED"):
    return mark_coverage(Contract(required=(_F1, _F2)), [label], [result])


def test_passed_manifest_covers_both_facts():
    cov = _cov(_BODY + "check: passed")
    assert cov.C == 1.0, cov


def test_failed_or_absent_check_is_not_credited():
    assert _cov(_BODY + "check: failed").C == 0.0
    assert _cov(_BODY.rstrip()).C == 0.0
    assert not goal_contract._harness_check_passed(_BODY + "check: failed")
    assert not goal_contract._checked_after_change(_BODY + "check: failed")


def test_a_passed_check_counts_as_the_check_after_a_change():
    assert goal_contract._checked_after_change(_BODY + "check: passed")


def test_flag_off_result_without_manifest_is_unchanged():
    res = "I read orders.csv.\nActions:\n- read_file orders.csv -> ok"
    assert not goal_contract._harness_check_passed(res)
    assert _cov(res).C == 0.0
