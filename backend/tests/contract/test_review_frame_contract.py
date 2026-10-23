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
    out = _review_frame_evidence([], None, plan="Edit README")
    assert out == "STEP: Edit README"


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
    out = _review_frame_evidence([], None, plan="x" * 900)
    assert len(out) <= len("STEP: ") + 300
