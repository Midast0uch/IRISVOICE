"""CT-CS — card-settle at the grade chokepoint.

Live finding (session-326, live probes): conversations ended with a grade
recorded in the DER node but the task card never settled — it sat in
"Active Execution" until the user reloaded. The reason: the grade was
computed in `_der_report_run_grade` (the single deduped chokepoint for
*three* terminal paths), but the card-settle event was only emitted inside
`_execute_plan_der`. When a turn ended through `_der_finalize_step` or
`_der_plan_next_step`, the grade wrote and the card didn't.

This test pins the fixed behavior: the moment a grade is reported, a card
terminal frame must also be emitted, so the card can't outlive its grade.
"""
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, '.')

import pytest
from backend.agent.agent_kernel import AgentKernel


def _fresh_kernel(card_id=None):
    k = AgentKernel.__new__(AgentKernel)
    k._card_by_task = {}
    k._der_card_terminal_emitted = set()
    k.conversation_id = "conv-test"
    k.session_id = "sess-test"
    if card_id:
        k._card_by_task["turn-1"] = card_id
    return k


def _seed_card_envelope(k, card_id, conv_id):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "backend.agent.agent_kernel.AgentKernel._card_envelope",
            lambda _s, t: {"card_id": card_id, "conversation_id": conv_id},
            raising=False,
        )
        yield


def test_grade_yields_card_terminal_event():
    """Passing grade on a turn with a known card must emit task:done."""
    card_id, conv, turn = "card_1", "conv-test", "turn-settle"
    k = _fresh_kernel(card_id)
    bus = MagicMock()

    with patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        with patch(
            "backend.agent.agent_kernel.AgentKernel._card_envelope",
            new=lambda *_a, **_kw: {"card_id": card_id, "conversation_id": conv},
        ):
            k._der_emit_card_settle(
                turn, completed_items=[], _grade="pass", _where="test"
            )
    assert bus.emit.call_count == 1
    evt = bus.emit.call_args[0][0]
    assert "TASK_DONE" in str(evt)


def test_emit_once_per_turn_only():
    """A second call with the same turn_id must not re-emit."""
    k = _fresh_kernel("card_x")
    bus = MagicMock()
    with patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        with patch(
            "backend.agent.agent_kernel.AgentKernel._card_envelope",
            new=lambda *_a, **_kw: {
                "card_id": "card_x",
                "conversation_id": "conv-test",
            },
        ):
            k._der_emit_card_settle(
                "turn-dedup", completed_items=[], _grade="pass", _where="a"
            )
            k._der_emit_card_settle(
                "turn-dedup", completed_items=[], _grade="pass", _where="b"
            )
    assert bus.emit.call_count == 1


def test_no_card_no_emit():
    """No card, no event — never synthesize a phantom card frame."""
    k = _fresh_kernel()
    bus = MagicMock()
    with patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        with patch(
            "backend.agent.agent_kernel.AgentKernel._card_envelope",
            new=lambda *_a, **_kw: {"card_id": None, "conversation_id": "conv-test"},
        ):
            k._der_emit_card_settle(
                "turn-none", completed_items=[], _grade="pass", _where="t"
            )
    assert bus.emit.call_count == 0


def test_capped_grade_maps_to_fail():
    """'capped' is still terminal-but-failed for the card's purpose."""
    k = _fresh_kernel("card_y")
    bus = MagicMock()
    with patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        with patch(
            "backend.agent.agent_kernel.AgentKernel._card_envelope",
            new=lambda *_a, **_kw: {
                "card_id": "card_y",
                "conversation_id": "conv-test",
            },
        ):
            k._der_emit_card_settle(
                "turn-capped", completed_items=[], _grade="capped", _where="t"
            )
    evt = bus.emit.call_args[0][0]
    assert "FAIL" in str(evt)
