"""Behavioral test: REQ-4/REQ-5 — failures are classified and committed
honestly; NO TASK_BLOCKED / ask_user escalation for long-horizon tasks.

This is the post-spec form of the old gap test. The old version pinned
`der-loop-integrity-display` REQ-10 (emit TASK_BLOCKED + ask_user after the
graft budget is exhausted). That spec was deleted — its folder no longer
exists and `phase-6-der-integrity` (the successor) has no REQ-10. The
long-horizon spec (specs/long-horizon-der-execution) supersedes it:

- REQ-4 (D4): classify failures BEFORE split. Provider/transport/envelope
  failures (transient, unavailable, invalid args, empty, permanent) are
  recorded as failure evidence and must NOT recursively fan out into graft
  children. Only a genuine semantic failure splits.
- REQ-5: "IF budget ends before completion THEN THE SYSTEM SHALL emit
  remaining nodes and their last failure class." No blocker card.
- T12: escalation is retained ONLY for short responses (choice/escalation
  QuestionCard), not for long-horizon DER tasks.

This test drives the real recovery decision (`_der_handle_step_failure`) on
a critical step:
  1. a provider/empty failure -> classified, recorded, NOT split, no blocker
  2. a semantic failure (real content, verification rejected) -> still splits
  3. budget exhausted -> honest finalization (no TASK_BLOCKED, no ask_user)
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.der_constants import DER_MAX_GRAFTS
from backend.agent.der_loop import DirectorQueue, QueueItem


class _StubKernel:
    """Minimal kernel stub exposing only what _der_handle_step_failure
    touches, plus probes for escalation side-effects."""

    def __init__(self):
        self.asked = []          # captured ask_user calls (must stay empty)
        self.blocked_events = []  # captured TASK_BLOCKED emits (must stay empty)
        self._der_work_units = 10
        self.conversation_id = "conv-req45"
        self.session_id = "sess-req45"
        self._der_ledger = None   # created lazily by the handler

    # --- attributes/methods the production recovery path touches ---
    def _der_live_cad_state(self, session):
        return {"u": 0.3, "xi": 0.1}  # oscillating -> wide split

    def _split_step(self, item, reason, cad, wu, step_result="",
                    verified_fraction=0.0):
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
            _session="sess-req45", _turn_id="t1", context_package=None,
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


class TestHonestFailureFinalization:
    def test_provider_failure_recorded_not_split_no_blocker(self):
        """REQ-4/D4: a rate-limited critical step is classified (transient),
        recorded as failure evidence, and does NOT split into graft children —
        the old `not step_success -> split` rule turned one transient error
        into a recursive fan-out (observed live: 23-minute websearch loop
        under a saturated provider window)."""
        kernel = _StubKernel()
        queue = _make_queue(critical=True)
        item = queue.items[0]

        _run_recovery(
            kernel, queue, item,
            step_result="RateLimitedError(provider=cerebras, attempts=3, retry_after=None)",
        )

        # Committed honestly: step failed, descendants aborted, no children.
        assert item.step_id in queue.failed_ids
        assert queue.graft_attempts == 0, (
            "D4: provider failure must NOT consume the graft budget"
        )
        # Failure evidence recorded on the ledger.
        assert kernel._der_ledger is not None
        _evidence = kernel._der_ledger.failures()
        assert len(_evidence) >= 1
        assert _evidence[0].failure_class in (
            "transient", "empty", "permanent",
        )
        # No escalation of any kind (REQ-5 / T12).
        assert kernel.blocked_events == [], (
            "REQ-5: TASK_BLOCKED must not fire for a classified failure"
        )
        assert kernel.asked == []

    def test_empty_result_not_split_no_blocker(self):
        """REQ-4: an empty result (no candidate URLs) is classified and
        committed honestly — the exact failure that previously looped."""
        kernel = _StubKernel()
        queue = _make_queue(critical=True)
        item = queue.items[0]

        _run_recovery(
            kernel, queue, item,
            step_result="[STEP ERROR: no candidate urls found for query]",
        )

        assert item.step_id in queue.failed_ids
        assert queue.graft_attempts == 0
        assert kernel.blocked_events == []
        assert kernel.asked == []

    def test_semantic_failure_still_splits(self):
        """D4: only a genuine semantic failure (tool produced content but
        verification judged it wrong) splits — children get real content."""
        kernel = _StubKernel()
        queue = _make_queue(critical=True)
        item = queue.items[0]

        _run_recovery(
            kernel, queue, item,
            step_result="The extraction produced pages but they do not answer the question.",
        )

        assert item.step_id in queue.failed_ids
        assert queue.graft_attempts == 1, (
            "D4: semantic failure MAY split (recovery children)"
        )
        assert kernel.blocked_events == []
        assert kernel.asked == []

    def test_budget_exhausted_finalizes_honestly(self):
        """REQ-5: after the graft budget is spent, a further critical failure
        finalizes honestly — remaining nodes + last failure class are emitted
        by the loop summary; no TASK_BLOCKED card and no ask_user call."""
        kernel = _StubKernel()
        queue = _make_queue(critical=True)
        item = queue.items[0]

        # Burn the budget with semantic failures (which split), then one more.
        for _ in range(DER_MAX_GRAFTS + 1):
            _run_recovery(
                kernel, queue, item,
                step_result="The extraction produced pages but they do not answer the question.",
            )
            if item.step_id in queue.completed_ids:
                queue.completed_ids.remove(item.step_id)

        # The parent is recorded failed, budget exactly spent...
        assert item.step_id in queue.failed_ids
        assert queue.graft_attempts == DER_MAX_GRAFTS
        # ...but the OLD blocker escalation is gone (superseded by REQ-5).
        assert kernel.blocked_events == [], (
            "REQ-5: TASK_BLOCKED must not fire after grafts exhausted"
        )
        assert kernel.asked == [], (
            "REQ-5: ask_user must not fire after grafts exhausted"
        )

    def test_non_critical_failure_never_escalates(self):
        """Non-critical failures are recorded but never split or escalate."""
        kernel = _StubKernel()
        queue = _make_queue(critical=False)
        item = queue.items[0]

        _run_recovery(kernel, queue, item)
        assert item.step_id in queue.failed_ids
        assert kernel.asked == []
        assert kernel.blocked_events == []
        assert queue.graft_attempts == 0
