"""Behavioral — cli-workspace-unification T12 (REQ-1..REQ-5, REQ-10).

Drives a FULL task lifecycle — plan announcement -> execution progress ->
convergence — through the REAL EventBus, asserting the EMERGENT contract
properties the CDD harness replays on every run:

  1. every task:start frame carries the full identity set: card_id /
     card_relation / conversation_id / agent_id / project_id (CT-1) —
     no phantom card is possible because identity is backend-declared;
  2. revisions re-emit through the SAME channel with a distinct origin,
     never a parallel event;
  3. the lifecycle ends in exactly one terminal frame (task:done or
     task:fail) for the conversation — failure is recorded AND addressable;
  4. the structured lifecycle log (T11) receives every terminal transition.

No live web; no kernel construction (identity helpers + bus only).
"""

import asyncio
import uuid
from pathlib import Path

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import EventBus, IRISStreamEvent


def _make_kernel(session_id=None, conversation_id=None):
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
    k.conversation_id = conversation_id or f"conv_{uuid.uuid4().hex[:8]}"
    return k


def _start_payload(k, task_id, origin="initial", card_id=None, card_relation="new"):
    if card_id is None:
        card_id = f"card_{task_id}"
    return AgentKernel._task_start_payload(
        task_id=task_id,
        description="Read the spec and implement Wave 1",
        plan_title="Implement the unified CLI",
        mode="full",
        steps=[
            {"id": "s1", "description": "read spec", "status": "pending"},
            {"id": "s2", "description": "edit chat-view", "status": "pending"},
        ],
        total_steps=2,
        origin=origin,
        card_id=card_id,
        card_relation=card_relation,
        conversation_id=k.conversation_id,
        **k._multiagent_tags(),
    )


class TestFullCliTaskLifecycle:
    def test_plan_progress_converge_carries_identity_on_every_start(self):
        """Plan -> revision -> done: EVERY task:start frame carries the full
        identity set; the revision reuses the channel with a distinct origin."""
        bus = EventBus()
        k = _make_kernel()
        seen = {"start": [], "terminal": []}
        # Handlers receive the EventPayload envelope — the contract lives on
        # `.data` (what the WS layer serialises to the frontend).
        bus.subscribe(IRISStreamEvent.TASK_START, lambda p: seen["start"].append(p.data))
        bus.subscribe(IRISStreamEvent.TASK_DONE, lambda p: seen["terminal"].append(p.data))

        # 1. initial plan announcement
        bus.emit(IRISStreamEvent.TASK_START, data=_start_payload(k, "task_a"),
                 conversation_id=k.conversation_id, turn_id="turn-1")
        # 2. sub-loop split REVISION — same channel, distinct origin
        bus.emit(
            IRISStreamEvent.TASK_START,
            data=_start_payload(k, "task_b", origin="sub_loop_split",
                                card_id="card_task_a", card_relation="continues"),
            conversation_id=k.conversation_id, turn_id="turn-1",
        )
        # 3. convergence
        bus.emit(IRISStreamEvent.TASK_DONE,
                 data={"task_id": "task_a", "outcome": "success"},
                 conversation_id=k.conversation_id, turn_id="turn-1")

        assert len(seen["start"]) == 2
        for payload in seen["start"]:
            for key in ("card_id", "card_relation", "conversation_id",
                        "agent_id", "project_id"):
                assert key in payload, f"contract key {key!r} missing from task:start"
            assert payload["agent_id"] == k.session_id
            assert payload["conversation_id"] == k.conversation_id

        origins = [p["origin"] for p in seen["start"]]
        assert origins == ["initial", "sub_loop_split"]
        # The revision CONTINUES the parent card — a branch within a card.
        assert seen["start"][1]["card_id"] == "card_task_a"
        assert seen["start"][1]["card_relation"] == "continues"

        # Exactly ONE terminal frame for the conversation.
        assert len(seen["terminal"]) == 1
        assert seen["terminal"][0]["outcome"] == "success"

    def test_failure_is_recorded_and_addressable(self):
        """A failed task emits task:fail scoped to its conversation — failure
        is recorded AND addressable, never silently swallowed."""
        bus = EventBus()
        k = _make_kernel()
        terminal = []
        bus.subscribe(IRISStreamEvent.TASK_FAIL, lambda p: terminal.append(p))

        bus.emit(IRISStreamEvent.TASK_FAIL,
                 data={"task_id": "task_x", "outcome": "failed",
                       "error": "step 9 verify_failed"},
                 conversation_id=k.conversation_id)

        assert len(terminal) == 1
        assert terminal[0].conversation_id == k.conversation_id
        assert terminal[0].data["outcome"] == "failed"

    def test_structured_log_receives_lifecycle_transitions(self, tmp_path, monkeypatch):
        """T11 (REQ-8): the structured JSONL log receives task:start/done/fail
        with ISO ts + conversation id — written to .iris-logs/, best-effort."""
        import backend.agent.event_bus as eb

        logfile = tmp_path / "backend-events.jsonl"
        monkeypatch.setattr(eb, "_structured_logger_initialized", False)

        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(logfile, maxBytes=1_000_000, backupCount=0)
        handler.setFormatter(logging_json_formatter())
        eb._structured_logger.addHandler(handler)

        try:
            bus = EventBus()
            k = _make_kernel()
            bus.emit(IRISStreamEvent.TASK_START, data=_start_payload(k, "t"),
                     conversation_id=k.conversation_id)
            bus.emit(IRISStreamEvent.TASK_DONE, data={"task_id": "t"},
                     conversation_id=k.conversation_id)
            handler.flush()
            lines = [l for l in logfile.read_text(encoding="utf-8").splitlines() if l.strip()]
            import json

            entries = [json.loads(l) for l in lines]
            assert [e["event"] for e in entries] == ["task:start", "task:done"]
            for e in entries:
                assert e["conversation_id"] == k.conversation_id
                # ISO-8601 timestamp present on every line (REQ-8 AC1).
                assert "T" in e["ts"]
        finally:
            eb._structured_logger.removeHandler(handler)
            eb._structured_logger_initialized = True  # don't re-add tmp handler later


def logging_json_formatter():
    import logging

    return logging.Formatter("%(message)s")
