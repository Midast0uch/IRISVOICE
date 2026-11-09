"""tool_choice label: v4 reads the CALL-level outcome; v7 reads the STEP result.

v4 (2026-10-21): the label reads the call-level outcome (`approval_ok`, the
tool_approval/v6 precedent) instead of the loop's exit-code `ok`. Measured
from the logs: 36 of 39 failed run_command calls were ran-and-exited, not
errored.

v7 (2026-11-07, owner: "get tool_choice out of shadow into enforcement, fix
the label"): measured on tc-decide-v4 (698 distinct rows), 74 rows were wrong
and EVERY one carried `outcome_label=failed`. The call-age label is answer-
blind only in the trivial sense - on a binding pick the model writes the
ARGUMENTS, so the label asked "did the arguments work", not "was this the right
TOOL". v6 tried the step's verified_label and was single-class (19 settled
rows, ALL UNVERIFIED) because the verifier grades output TEXT. v7 holds the
decided row and stamps it with the step's COMPLETION: the call worked AND the
step was not retried. This test pins the stamp and the label mechanics; the
new module's own contract lives in
test_tool_choice_outcome_label_contract.py.

Pins three seams, structurally where the method is too large to drive:
  * _on_result passes the CALL-level outcome to label_decided_row;
  * the row carries the v7 stamp and the input_key identity;
  * label_decided_row's own mechanics are unchanged (ok/overridden/finished).
"""
from __future__ import annotations

import inspect
import types

from backend.agent.agent_kernel import AgentKernel
from backend.agent.tool_decision import ToolDecisionBox


def test_the_label_reads_the_call_level_outcome():
    src = inspect.getsource(AgentKernel._der_run_node)
    assert "def _on_result(name, params, ok, approval_ok=None):" in src
    # v4: the tool_choice label reads the CALL-level outcome, not the loop's
    assert "_label_ok = bool(approval_ok) if approval_ok is not None" in src
    assert "box.label_decided_row(_pend, called=name, ok=_label_ok," in src


def test_the_row_carries_the_v7_stamp_and_the_input_identity():
    src = inspect.getsource(ToolDecisionBox.choose_node_tool)
    assert '"tc-decide-v9"' in src
    assert '"input_key": _tc_input_key(frame),' in src
    # the identity is the SAME hash implementation as every other consumer
    from backend.agent.surface_shadow import input_key
    from backend.agent.tool_decision import _tc_input_key
    frame = {"goal": "Run the tests", "last_result": "x"}
    assert _tc_input_key(frame) == input_key("tool_choice", "Run the tests", frame)


class _CaptureBox(ToolDecisionBox):
    """label_decided_row's writer, captured."""

    def __init__(self):  # noqa: D107 - no base init needed for this pin
        self.rows = []

    def _record_shadow_row(self, row, session_id=""):  # noqa: D418
        self.rows.append(row)


def test_label_mechanics_are_unchanged(monkeypatch):
    # This pin is the FLAG-OFF path: the call-age label stands.
    monkeypatch.delenv("IRIS_ORACLE_TOOL_CHOICE_OUTCOME", raising=False)
    box = _CaptureBox()
    row = {"consumer_id": "tool_choice", "chosen": "run_command",
           "confidence": 0.9}
    # the call executed -> outside_label True
    box.label_decided_row(dict(row), called="run_command", ok=True)
    assert box.rows[-1]["outside_label"] is True
    assert box.rows[-1]["outcome_label"] == "ok"
    # the model called a different tool -> overridden, scored not-held
    box.label_decided_row(dict(row), called="edit_file", ok=True)
    assert box.rows[-1]["outcome_label"] == "overridden"
    assert box.rows[-1]["outside_label"] is False
    # the step finished without a call -> counted, never scored
    box.label_decided_row(dict(row), called=None, ok=None)
    assert box.rows[-1]["outcome_label"] == "finished"
    assert "outside_label" not in box.rows[-1]


def test_the_decided_row_is_held_then_written_with_the_step_completion(monkeypatch):
    """The integration seam: label_decided_row -> _record_shadow_row -> defer,
    then the settle stamp writes the ONE row with the step's completion."""
    from backend.agent import tool_choice_outcome_label as tcol

    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_OUTCOME", "1")
    tcol.reset()
    try:
        written = []
        box = ToolDecisionBox.__new__(ToolDecisionBox)
        box._tool_bridge = types.SimpleNamespace(
            record_decision=lambda r, **kw: written.append(dict(r)),
        )
        row = {"consumer_id": "tool_choice", "chosen": "run_command",
               "confidence": 0.9, "step_id": "s3", "turn_id": "t1"}
        box.label_decided_row(dict(row), called="run_command", ok=True)
        # held: no write yet, and the call-age label was dropped
        assert written == []
        # the step completes -> exactly one row, labelled by the completion
        assert tcol.stamp("s3", "t1", True) == 1
        assert len(written) == 1
        assert written[0]["outside_label"] is True
        assert written[0]["label_reference"] == "step_completed"
        # a second settle does not double-write
        assert tcol.stamp("s3", "t1", True) == 0
        assert len(written) == 1
    finally:
        tcol.reset()


def test_the_flag_off_path_writes_immediately(monkeypatch):
    from backend.agent import tool_choice_outcome_label as tcol

    monkeypatch.delenv("IRIS_ORACLE_TOOL_CHOICE_OUTCOME", raising=False)
    tcol.reset()
    written = []
    box = ToolDecisionBox.__new__(ToolDecisionBox)
    box._tool_bridge = types.SimpleNamespace(
        record_decision=lambda r, **kw: written.append(dict(r)),
    )
    row = {"consumer_id": "tool_choice", "chosen": "run_command",
           "confidence": 0.9, "step_id": "s3", "turn_id": "t1"}
    box.label_decided_row(dict(row), called="run_command", ok=True)
    assert len(written) == 1
    assert written[0]["outside_label"] is True


def test_the_kernel_stamps_the_step_completion():
    """Both ends of the retry signal live in the settle path, not the module.

    A stamp that lived in _der_finalize_step would run BEFORE the artifact
    graft and call a grafted step "completed". A stamp that ignored
    completed_ids would call a split parent (held, not completed) "completed".
    """
    from backend.agent import agent_kernel as ak

    src = inspect.getsource(ak._der_post_step)
    # a FAILED step is a retry signal, stamped before the recovery decision
    assert '_tcol.stamp(getattr(item, "step_id", None), _turn_id, False)' in src
    # a successful step is completed only with no graft and in completed_ids
    assert "_tc_step_ok = (" in src
    assert "not int(_grafted or 0)" in src
    assert 'item.step_id in getattr(queue, "completed_ids", ())' in src
    assert '_tcol.stamp(getattr(item, "step_id", None), _turn_id, _tc_step_ok)' in src
    # the graft must REPORT its work or the completion test is blind
    gsrc = inspect.getsource(AgentKernel._der_graft_missing_artifacts)
    assert "-> int:" in gsrc
    assert "return len(_missing)" in gsrc


def test_the_action_class_label_is_final_and_not_held(monkeypatch):
    """v8: the Oracle's class verdict must survive the call-age writer.

    The model calling a DIFFERENT tool is a fact about the model, not the
    Oracle: it does not turn a correct class pick into a wrong one.
    """
    written = []
    box = ToolDecisionBox.__new__(ToolDecisionBox)
    box._tool_bridge = types.SimpleNamespace(
        record_decision=lambda r, **kw: written.append(dict(r)),
    )
    row = {"consumer_id": "tool_choice", "chosen": "read_file",
           "confidence": 0.9, "step_id": "s1", "turn_id": "t1",
           "label_source": "action_class", "label_reference": "action_class",
           "outside_label": True}
    box.label_decided_row(dict(row), called="grep_files", ok=True)
    assert len(written) == 1
    assert written[0]["outside_label"] is True
    assert written[0]["label_reference"] == "action_class"
    assert written[0]["outcome_label"] == "overridden"


def test_the_class_guard_and_always_flag_are_wired():
    """The sure path: guard the class, then let the owner's flag always enforce.

    A regression here silently returns the Oracle to an unguarded, confidence-
    thresholded path that the measurements showed cannot rank its errors.
    """
    src = inspect.getsource(ToolDecisionBox.choose_node_tool)
    assert "always_enabled()" in src
    assert "allowed_tools(" in src
    # unknown goal must ABSTAIN under enforcement, never run unguarded
    assert "if (_always or enforced) and _action_need is None:" in src
    # the owner flag makes the pick used without the calibrated threshold
    assert "enforced and not _always and not _shortlist_k" in src
    assert '"shortlist" if (_shortlist_k or _class_mode)' in src


def test_the_shortlist_mode_is_wired():
    """Candidate compression: the Oracle ranks, the model picks from the top-k.

    A single forced pick is worse than the model's own choice (c14: 301 s).
    The shortlist must reach the model as a LIST with no named tool_choice.
    """
    src = inspect.getsource(ToolDecisionBox.choose_node_tool)
    assert "shortlist_from_distribution(" in src
    assert "if (_shortlist_k or _class_mode) and not _short:" in src
    from backend.agent import node_executor as ne

    nsrc = inspect.getsource(ne.run_node)
    assert "isinstance(forced, (list, tuple, set))" in nsrc
    assert "_keep = {str(x) for x in forced} & allowed" in nsrc


def test_the_class_decision_is_wired():
    """The d1-2b decides the CLASS; the model picks inside it.

    The decision is taken only when the class mass clears the measured margin;
    otherwise the shortlist fallback keeps the model's choice open.
    """
    src = inspect.getsource(ToolDecisionBox.choose_node_tool)
    assert "class_decision_enabled()" in src
    assert "class_masses(" in src
    assert "CLASS_MARGIN_MIN" in src
    assert 'if (_top_class in (READ, WRITE, RUN)' in src
    assert '"route": ("class" if _class_decided' in src
