"""Contract (reply-surface-contract REQ-19, task T34): a turn that has produced
its final answer must not continue a recovery sub-loop.

Live finding 2026-09-23 (conv-139/140): a grafted recovery sub-loop kept
executing for ~40 minutes AFTER the final reply was delivered — the card kept
updating, sources kept crawling, and the user read it as a second agent.

The turn's public moment is the card settle (``_der_emit_card_settle``), which
marks the turn in ``_der_card_terminal_emitted``. This file pins the READ of
that marker on the one path that extends the executing graph:
``_der_amend_graph``, whose production caller is the verify-failure graft. The
spec marked T34 DONE before this read existed — the marker was written and never
consulted, so a settled turn could still be amended.
"""

from __future__ import annotations

from pathlib import Path

import backend.agent.agent_kernel as ak
from backend.agent.der_loop import DirectorQueue, QueueItem


class _Plan:
    original_task = "task"
    plan_title = "p"


class _Step:
    description = "grafted recovery step"
    tool = None            # production plans are goal-only (F6)
    params = {}
    depends_on = []        # appended steps depend on nothing pending


def _kernel(settled_turn=None):
    k = ak.AgentKernel.__new__(ak.AgentKernel)
    k._der_amendment_count = 0
    k.conversation_id = "conv"
    if settled_turn is not None:
        k._der_card_terminal_emitted = {settled_turn}
    return k


def _queue():
    q = DirectorQueue(objective="task", items=[
        QueueItem(step_id="s1", step_number=1, description="completed step"),
    ])
    q.mark_complete("s1")
    return q


class TestTurnFinalizedStopWork:
    """The refusal itself (REQ-19 AC1/AC2)."""

    def test_amendment_refused_after_the_turn_settled(self):
        k = _kernel("turn-1")
        q = _queue()
        assert k._der_amend_graph(
            [_Step()], "sess", _Plan(), q, _turn_id="turn-1"
        ) is False
        assert k._der_amendment_count == 0, "a closed turn consumes no amendment"
        assert not any(it.step_id.startswith("amend-") for it in q.items), (
            "no recovery step may be appended after the answer is public"
        )

    def test_amendment_applies_while_the_turn_is_live(self):
        # No regression: an unsettled turn amends exactly as before.
        k = _kernel()
        q = _queue()
        assert k._der_amend_graph(
            [_Step()], "sess", _Plan(), q, _turn_id="turn-1"
        ) is True
        assert k._der_amendment_count == 1
        assert any(it.step_id.startswith("amend-") for it in q.items)

    def test_another_turns_settle_does_not_block_this_turn(self):
        k = _kernel("turn-1")
        q = _queue()
        assert k._der_amend_graph(
            [_Step()], "sess", _Plan(), q, _turn_id="turn-2"
        ) is True, "the guard is keyed by turn, not by 'any settle ever'"

    def test_the_kernel_turn_pointer_is_honoured_too(self):
        # The graft path always passes its turn id; a caller that does not still
        # gets the guard through the kernel's own turn pointer.
        k = _kernel("turn-1")
        k._current_turn_id = "turn-1"
        assert k._der_amend_graph([_Step()], "sess", _Plan(), _queue()) is False


class TestTheGuardIsWired:
    """Source pins — the writer, the refusal cause, and the production caller."""

    def test_settle_emitter_writes_the_marker_the_guard_reads(self):
        src = Path(ak.__file__).read_text(encoding="utf-8", errors="replace")
        assert "self._der_card_terminal_emitted = _emitted" in src, (
            "the settle emitter must record which turn became public"
        )
        assert '"recovery_stopped_turn_finalized",' in src, (
            "a refused post-answer amendment must be recorded with its cause "
            "(REQ-5 AC5 / REQ-9 AC3)"
        )
        assert "_children, _session, plan, queue, _turn_id=_turn_id," in src, (
            "the graft is the amendment gate's production caller and must hand "
            "it the turn id, or the refusal can never fire"
        )
