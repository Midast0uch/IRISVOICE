"""tool_choice v4: the label reads the CALL-level outcome (2026-10-21).

The grown tc-decide-v3 cohort (2231 legacy-distinct rows) fell to OOF AUROC
0.617 and was demoted. The honest state-keyed cohort (2428 rows) showed the
cause: BINDING run_command rows ranked at chance (AUROC 0.4982, 488 rows).
The v3 label read the loop's `ok`, which counts a non-zero returncode as
failure - so a mid-iteration pytest exit (the command RAN, the call did its
job) was labeled a wrong pick. Measured from the logs: 36 of 39 failed
run_command calls were ran-and-exited, not errored. v4 reads the call-level
outcome (`approval_ok`, the tool_approval/v6 precedent); the offline
re-label takes the honest cohort from AUROC 0.657 to 0.7988.

Pins three seams, structurally where the method is too large to drive:
  * _on_result passes the CALL-level outcome to label_decided_row;
  * the row carries the v4 stamp and the input_key identity;
  * label_decided_row's own mechanics are unchanged (ok/overridden/finished).
"""
from __future__ import annotations

import inspect

from backend.agent.agent_kernel import AgentKernel
from backend.agent.tool_decision import ToolDecisionBox


def test_the_label_reads_the_call_level_outcome():
    src = inspect.getsource(AgentKernel._der_run_node)
    assert "def _on_result(name, params, ok, approval_ok=None):" in src
    # v4: the tool_choice label reads the CALL-level outcome, not the loop's
    assert "_label_ok = bool(approval_ok) if approval_ok is not None" in src
    assert "box.label_decided_row(_pend, called=name, ok=_label_ok," in src


def test_the_row_carries_the_v4_stamp_and_the_input_identity():
    src = inspect.getsource(ToolDecisionBox.choose_node_tool)
    assert '"tc-decide-v4"' in src
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


def test_label_mechanics_are_unchanged():
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
