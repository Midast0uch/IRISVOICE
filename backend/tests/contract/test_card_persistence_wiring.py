"""T4a (REQ-4 AC1/AC5) — specs/task-card-v2-liquid-ink: PROOF that the card
store is REACHED from real kernel emit sites, not merely exercised directly.

T4 built ``ConversationContextStore.save_card`` /
``get_cards_for_conversation`` and tested them fully
(test_conversation_card_persistence_baseline.py) — but nothing called them.
A test that calls ``save_card`` directly proves nothing about T4a: T4's own
tests already do that and would stay green with zero wiring. This file
drives the REAL, unstubbed ``AgentKernel`` methods that CONTAIN the wiring —
same "stub kernel + real DirectorQueue/QueueItem" harness already
established by
backend/tests/behavioral/test_failed_step_writes_commit_row.py:
  - ``_der_amend_graph`` — a real ``task:start`` (``origin="amendment"``)
    emit site, callable without an LLM because amendment steps are
    pre-planned (unlike the ``user_steering`` site, which calls
    ``self._plan_task``).
  - ``_der_finalize_step`` — the real ``task:progress`` (``step_done``)
    emit site.

Each test must FAIL if ``AgentKernel._persist_card_snapshot`` (or its call
sites) is deleted while ``save_card`` itself keeps working.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import backend.agent.conversation_context_store as ccs_module
import backend.agent.event_bus as eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem


class _CapturingBus:
    def __init__(self) -> None:
        self.emitted = []

    def emit(self, event, data=None, **kw):
        self.emitted.append((getattr(event, "value", str(event)), data or {}))


def _make_stub_kernel(conversation_id: str) -> AgentKernel:
    """Same recipe as test_failed_step_writes_commit_row.py's
    _make_stub_kernel — a real AgentKernel built via __new__ (skips
    __init__'s heavy service wiring) with only the attributes the DER
    finalize/amend paths actually touch, plus the card-identity state T1/T2
    added (``_card_by_task`` / ``_active_card_id`` / ``_CARD_REGISTRY_CAP``)."""
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k._memory_interface = None
    k._trailing_director = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu, step_result="": []
    k._verify_step_result = (
        lambda goal, expected, result, tool=None, success=False: "VERIFIED"
    )
    k._card_by_task = {}
    k._active_card_id = None
    k._CARD_REGISTRY_CAP = 200
    k._der_amendment_count = 0
    return k


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point BOTH singletons (the store and its write queue) at a
    tmp_path-isolated DB — never data/databases/conversation_contexts.db."""
    ccs_module.reset_context_store_for_testing()
    ccs_module.reset_card_write_queue_for_testing()
    store = ccs_module.ConversationContextStore(db_path=tmp_path / "test_contexts.db")
    monkeypatch.setattr(ccs_module, "_store_instance", store)
    yield store
    store.close()
    ccs_module.reset_context_store_for_testing()
    ccs_module.reset_card_write_queue_for_testing()


def _wait_for_drain():
    """The write is on T4a's coalescing background queue, not synchronous —
    block until it drains instead of sleeping arbitrarily. Timing out here
    means the emit site never enqueued anything (wiring absent) or the
    writer thread is stuck, either of which is a real failure."""
    drained = ccs_module.get_card_write_queue().wait_idle(timeout=2.0)
    assert drained, (
        "card write queue never drained within 2s — either the emit site "
        "never enqueued a write (wiring missing) or the writer thread "
        "stalled"
    )


def _make_amend_step(description: str = "do the new thing"):
    return type(
        "S",
        (),
        {
            "description": description,
            "tool": "run_command",
            "params": {},
            "depends_on": [],
            "critical": True,
        },
    )()


class TestTaskStartReachesTheStore:
    """REQ-4 AC1: the task:start-class emit persists a card."""

    def test_amendment_task_start_write_lands_in_the_store(
        self, isolated_store, monkeypatch
    ):
        bus = _CapturingBus()
        monkeypatch.setattr(eb_module, "get_event_bus", lambda: bus)

        conv_id = "conv-wiring-start"
        kernel = _make_stub_kernel(conv_id)

        plan = type(
            "P", (), {"original_task": "amend the plan", "plan_title": "Amend Plan"}
        )()
        queue = DirectorQueue(objective="amend the plan", items=[])
        queue.mode = ExecutionMode.QUICK

        applied = kernel._der_amend_graph(
            new_steps=[_make_amend_step()],
            _session="sess-1",
            plan=plan,
            queue=queue,
        )
        assert applied is True

        # Sanity: the real emit branch ran (not just the queue append).
        started = [d for (name, d) in bus.emitted if name == "task:start"]
        assert len(started) == 1
        card_id = started[0]["card_id"]
        assert card_id

        _wait_for_drain()

        cards = isolated_store.get_cards_for_conversation(conv_id)
        assert len(cards) == 1, (
            f"task:start emitted card_id={card_id!r} but no row landed in "
            "the store — _persist_card_snapshot is not reached from "
            "_der_amend_graph"
        )
        assert cards[0].card_id == card_id
        assert cards[0].conversation_id == conv_id
        assert cards[0].plan_title == "Amend Plan"


class TestInterruptedMidRunRestoresWithStepStatuses:
    """REQ-4 AC5: start + a progress write, no done — restores as
    terminated_unknown with step statuses intact. Meaningless if the only
    write happens at task:done, because the interrupted case never reaches
    it (the entire reason T4a exists)."""

    def test_start_then_progress_no_done_restores_terminated_unknown(
        self, isolated_store, monkeypatch
    ):
        bus = _CapturingBus()
        monkeypatch.setattr(eb_module, "get_event_bus", lambda: bus)

        conv_id = "conv-mid-run"
        kernel = _make_stub_kernel(conv_id)

        plan = type(
            "P", (), {"original_task": "research something", "plan_title": "Research"}
        )()
        queue = DirectorQueue(objective="research something", items=[])
        queue.mode = ExecutionMode.QUICK

        # task:start (real emit site, origin="amendment") mints the card and
        # persists it with the new step "pending".
        step = _make_amend_step("search the web")
        assert kernel._der_amend_graph(
            new_steps=[step], _session="sess-2", plan=plan, queue=queue,
        )
        _wait_for_drain()
        item = queue.items[0]  # the "amend-1" QueueItem _der_amend_graph appended

        pre = isolated_store.get_cards_for_conversation(conv_id)
        assert len(pre) == 1
        assert pre[0].terminal_state == "terminated_unknown", (
            "AC5: nothing has finished yet, so even the very first "
            "snapshot must resolve to terminated_unknown on read, never "
            "'running' forever"
        )
        assert [s.status for s in pre[0].steps] == ["pending"]

        # task:progress (real emit site — _der_finalize_step's step_done
        # write) marks the step complete. Never call task:done/fail: this
        # is the interrupted-mid-run case.
        kernel._der_finalize_step(
            item=item,
            step_result="found it",
            step_success=True,
            step_outputs=[],
            completed_items=[],
            _tokens_used=0,
            _token_budget=10_000,
            _session="sess-2",
            _turn_id=conv_id,
            _phase=2,
            is_mature=False,
            _live_ctx=None,
            plan=plan,
            context_package=None,
            queue=queue,
            verdict=None,
        )
        _wait_for_drain()

        restored = isolated_store.get_cards_for_conversation(conv_id)
        assert len(restored) == 1, (
            "task:progress ran but no updated row landed — "
            "_persist_card_snapshot is not reached from _der_finalize_step"
        )
        card = restored[0]
        assert card.card_id == pre[0].card_id, "same card, not a second one"
        assert card.terminal_state == "terminated_unknown", (
            "REQ-4 AC5: a card that never reached task:done/fail must "
            "restore as terminated_unknown, never 'running'"
        )
        assert [s.status for s in card.steps] == ["done"], (
            "the step transition recorded by task:progress must survive "
            "into the restored card — AC5 is meaningless if only the "
            "initial 'pending' snapshot persisted"
        )
