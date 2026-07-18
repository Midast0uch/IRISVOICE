"""Behavioral test: REQ-10 — agent ESCALATES to the user when a
critical step fails past the recovery budget (regression guard).

This is the post-fix form of the gap test. It drives the real recovery
decision (`_der_handle_step_failure`) on a critical step that fails
repeatedly until `graft_attempts` is exhausted (`DER_MAX_GRAFTS` = 3).
After the budget is spent, the (MAX+1)-th critical failure MUST escalate
to the user: emit `TASK_BLOCKED` + call `ask_user` with >=2 concrete
alternative options. The task must NOT be silently reported as "done"
with a critical step unmet.

Spec: specs/der-loop-integrity-display/requirements.md (REQ-10).
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.der_constants import DER_MAX_GRAFTS
from backend.agent.der_loop import DirectorQueue, QueueItem


class _StubKernel:
    """Minimal kernel stub exposing only what _der_handle_step_failure
    touches, plus probes for escalation side-effects."""

    def __init__(self):
        self.asked = []          # captured ask_user calls
        self.blocked_events = []  # captured TASK_BLOCKED emits
        self._der_work_units = 10

    # --- attributes/methods the production recovery path touches ---
    def _der_live_cad_state(self, session):
        return {"u": 0.3, "xi": 0.1}  # oscillating -> wide split

    def _split_step(self, item, reason, cad, wu):
        from backend.agent.der_loop import QueueItem

        return [
            QueueItem(
                step_id=f"{item.step_id}_child{j}",
                step_number=item.step_number + j,
                description=f"recovery {j}",
                tool=None,
                critical=False,
                objective_anchor=item.objective_anchor,
            )
            for j in range(2)
        ]


def _make_queue(critical: bool = True) -> DirectorQueue:
    item = QueueItem(
        step_id="s1",
        step_number=1,
        description="do the critical thing",
        tool="run_command",
        params={},
        critical=critical,
        objective_anchor="complete the task",
    )
    return DirectorQueue(objective="complete the task", items=[item])


def _run_recovery(kernel, queue, item, step_result="[STEP ERROR: hard failure]"):
    """Invoke the REAL recovery decision via the kernel method.

    We route its EventBus emit + ask_user tool through our probes so we
    can detect TASK_BLOCKED escalation without a live bus / real UI.
    """
    import backend.agent.agent_kernel as ak
    import backend.agent.event_bus as _eb
    import backend.agent.tools.ask_user_tool as _aut

    _orig_bus = getattr(_eb, "get_event_bus", None)
    _orig_ask = getattr(_aut, "get_ask_user_tool", None)

    def _fake_bus():
        bus = SimpleNamespace()

        def _emit(event, data=None, **kw):
            _val = getattr(event, "value", str(event))
            if _val == "task:blocked":
                kernel.blocked_events.append(data or {})

        bus.emit = _emit
        return bus

    def _fake_ask():
        f = SimpleNamespace()

        def _ask(text, options=None, **kw):
            kernel.asked.append({"text": text, "options": list(options or [])})

        f.ask = _ask
        return f

    _eb.get_event_bus = _fake_bus
    _aut.get_ask_user_tool = _fake_ask
    try:
        ak.AgentKernel._der_handle_step_failure(
            kernel, item, queue, plan=None,
            _session="sess-req10", _turn_id="t1", context_package=None,
            step_result=step_result,
        )
    finally:
        if _orig_bus is not None:
            _eb.get_event_bus = _orig_bus
        else:
            delattr(_eb, "get_event_bus")
        if _orig_ask is not None:
            _aut.get_ask_user_tool = _orig_ask
        else:
            delattr(_aut, "get_ask_user_tool")


class TestRecoveryEscalation:
    def test_critical_failure_exhausts_grafts_then_escalates(self):
        """Drive a critical step to fail DER_MAX_GRAFTS+1 times.

        The first DER_MAX_GRAFTS failures each trigger a split (recovery
        sub-steps). The (MAX+1)-th critical failure is past budget: the
        agent MUST escalate to the user (emit TASK_BLOCKED + call ask_user
        with >=2 options) instead of silently giving up.
        """
        kernel = _StubKernel()
        queue = _make_queue(critical=True)
        item = queue.items[0]

        for _ in range(DER_MAX_GRAFTS + 1):
            _run_recovery(kernel, queue, item)
            # Keep failing the same parent step (children are not executed
            # here — we test the DECISION, not the full loop).
            if item.step_id in queue.completed_ids:
                queue.completed_ids.remove(item.step_id)

        # After exhausting the graft budget, the parent is recorded failed.
        assert item.step_id in queue.failed_ids

        # REQ-10 ASSERTION: escalation happened.
        assert kernel.blocked_events, (
            "REQ-10: no TASK_BLOCKED emitted after grafts exhausted"
        )
        assert kernel.asked, (
            "REQ-10: ask_user was never called after grafts exhausted"
        )
        opts = kernel.asked[0]["options"]
        assert len(opts) >= 2, (
            f"REQ-10: expected >=2 alternative options, got {len(opts)}"
        )
        # And the graft budget is exactly spent.
        assert queue.graft_attempts == DER_MAX_GRAFTS, (
            f"expected graft_attempts=={DER_MAX_GRAFTS}, "
            f"got {queue.graft_attempts}"
        )

    def test_non_critical_failure_never_escalates(self):
        """Non-critical failures are recorded but never escalate (by design)."""
        kernel = _StubKernel()
        queue = _make_queue(critical=False)
        item = queue.items[0]

        _run_recovery(kernel, queue, item)
        assert item.step_id in queue.failed_ids
        assert kernel.asked == []
        assert kernel.blocked_events == []
        assert queue.graft_attempts == 0
