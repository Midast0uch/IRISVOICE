"""tool_choice label: v4 reads the CALL-level outcome; v6 reads the STEP outcome.

v4 (2026-10-21): the label reads the call-level outcome (`approval_ok`, the
tool_approval/v6 precedent) instead of the loop's exit-code `ok`. Measured
from the logs: 36 of 39 failed run_command calls were ran-and-exited, not
errored.

v6 (2026-11-07, owner: "get tool_choice out of shadow into enforcement, fix
the label"): measured on tc-decide-v4 (698 distinct rows), 74 rows were wrong
and EVERY one carried `outcome_label=failed`. The call-age label is answer-
blind only in the trivial sense - on a binding pick the model writes the
ARGUMENTS, so the label asked "did the arguments work", not "was this the right
TOOL". v6 holds the decided row and stamps it with the step's verified_label
(backend.agent.tool_choice_outcome_label). This test pins the stamp and the
label mechanics; the new module's own contract lives in
test_tool_choice_outcome_label_contract.py.

Pins three seams, structurally where the method is too large to drive:
  * _on_result passes the CALL-level outcome to label_decided_row;
  * the row carries the v6 stamp and the input_key identity;
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


def test_the_row_carries_the_v6_stamp_and_the_input_identity():
    src = inspect.getsource(ToolDecisionBox.choose_node_tool)
    assert '"tc-decide-v6"' in src
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


def test_the_decided_row_is_held_then_written_with_the_step_outcome(monkeypatch):
    """The integration seam: label_decided_row -> _record_shadow_row -> defer,
    then the settle stamp writes the ONE row with the step's outcome."""
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
        # the step settles -> exactly one row, labelled by the step
        assert tcol.stamp("s3", "t1", "VERIFIED") == 1
        assert len(written) == 1
        assert written[0]["outside_label"] is True
        assert written[0]["label_reference"] == "step_verified"
        # a second settle does not double-write
        assert tcol.stamp("s3", "t1", "VERIFIED") == 0
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
