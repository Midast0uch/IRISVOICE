"""review_verdict/v7: the frame carries the STEP line + the evidence."""
import types

from backend.agent.der_loop import _review_frame_evidence


def _step(line=None, result=""):
    ev = None
    if line is not None:
        ev = types.SimpleNamespace(line=lambda: line)
    return types.SimpleNamespace(envelope=ev, result=result)


def test_prior_steps_are_the_gate_evidence():
    out = _review_frame_evidence([_step("success, matched - proceed | 3 passed")])
    assert "3 passed" in out


def test_the_plan_line_is_the_step_under_review():
    out = _review_frame_evidence([_step("success | 3 passed")],
                                 plan="Fix the failing test in calc.py")
    assert out.startswith("STEP: Fix the failing test")
    assert "3 passed" in out


def test_the_plan_alone_is_a_frame():
    """CHANGED 2026-11-05 (owner: "label fix first"). This used to assert that
    a plan line with no evidence is still a frame ("the plan makes an
    otherwise-empty frame informative"). MEASURED on the v10 cohort (180
    distinct rows, label fixed so both classes exist): the confidence bands
    are monotonically INVERTED - accuracy 0.593 / 0.538 / 0.826 / 0.474 /
    0.362 / 0.250 as confidence rises from 0.4 to 1.0, oof AUROC 0.4117. The
    evidence-free rows are the cause: their whole frame was
    "RECENT RESULTS: STEP: <one line>", so d1 answered from the binary prior
    and was most confident exactly where it was most wrong. A plan line is not
    evidence about how the work is going.

    The v6 rule is now enforced for the plan case too - see
    test_no_evidence_means_no_row, which already pinned it for the no-plan
    case. The plan line still rides along when evidence exists."""
    assert _review_frame_evidence([], None, plan="Edit README") is None
    # ...and it still rides along when there IS evidence
    out = _review_frame_evidence([_step("success | 3 passed")], plan="Edit README")
    assert out.startswith("STEP: Edit README")
    assert "3 passed" in out


def test_the_last_result_is_the_fallback():
    ctx = types.SimpleNamespace(last_result_text="2 failed, 1 passed")
    out = _review_frame_evidence([], ctx)
    assert "output: " in out and "2 failed" in out


def test_no_evidence_means_no_row():
    assert _review_frame_evidence([], None) is None
    assert _review_frame_evidence([], types.SimpleNamespace(last_result_text="")) is None
    assert _review_frame_evidence(None, None) is None


def test_a_step_without_a_line_falls_back_to_its_result():
    out = _review_frame_evidence([_step(None, "raw output here")])
    assert "raw output here" in out


def test_the_plan_is_capped():
    """CHANGED 2026-11-05: the cap is unchanged, but the frame now needs
    evidence to exist at all (see test_the_plan_alone_is_a_frame), so this
    drives it with one evidence line."""
    out = _review_frame_evidence([_step("success | 3 passed")], plan="x" * 900)
    assert out.startswith("STEP: " + "x" * 300)
    assert len(out.split("\n")[0]) <= len("STEP: ") + 300


def test_the_action_and_criterion_ride_between_the_plan_and_the_evidence():
    """v12 (2026-11-06): the gate needs WHAT the step will do and HOW success
    is judged. MEASURED on the v11 cohort, the same model ranked agreement
    with the Brain's plan verdict at AUROC 0.8201 but ranked the execution
    OUTCOME at 0.5139 - neither the action nor the criterion was in the frame.
    They ride as their own lines so the pinned STEP line and its cap hold."""
    out = _review_frame_evidence(
        [_step("success | 3 passed")], plan="Fix calc.py",
        action="run_command {'cmd': 'pytest tests/test_calc.py'}",
        expected="all calc tests pass")
    assert out.split("\n")[0] == "STEP: Fix calc.py"
    assert "ACTION: run_command" in out
    assert "SUCCESS CRITERION: all calc tests pass" in out
    assert "3 passed" in out


def test_the_action_and_criterion_never_replace_the_evidence_requirement():
    """A first step with an action and a criterion but NO evidence still writes
    no row: a plan and a prediction target are not evidence of how the work is
    going (the v6 rule, unchanged by v12)."""
    assert _review_frame_evidence([], None, plan="x",
                                  action="run", expected="y") is None


def test_the_criterion_is_capped():
    out = _review_frame_evidence([_step("success | ok")], plan="p",
                                 expected="z" * 500)
    crit = [l for l in out.split("\n") if l.startswith("SUCCESS CRITERION: ")][0]
    assert len(crit) <= len("SUCCESS CRITERION: ") + 200
