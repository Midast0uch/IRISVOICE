"""Contract: `task:start` carries a revision origin.

specs/long-horizon-der-execution REQ-14 (AC1/AC5) — tasks.md T23.

`task:start` is the frontend's merge-by-id plan channel
(useTaskProgress.ts:210-227): a second `task:start` for the same task_id
keeps each existing step's live `status` while refreshing its
description/tool. A plan revision MUST reuse that same channel — not a
parallel event — with an `origin` field distinguishing the initial
announcement from revisions caused by sub-loop split (REQ-4/REQ-13) or by
user steering (REQ-15), so REQ-18's trace can attribute the origin.

Pinned here:
  - every `task:start` payload is built by ONE helper (AgentKernel.
    _task_start_payload) so the merge-by-id contract keys
    (task_id / description / plan_title / mode / steps / total_steps) and
    the origin vocabulary (initial | sub_loop_split | user_steering)
    cannot drift between emit sites — the payload passthrough.
  - a verify_failed split (agent_kernel.py, `_der_finalize_step`) re-emits
    task:start END-TO-END with origin="sub_loop_split" and the REVISED
    (child-bearing) step list — the explicit revision signal of REQ-14 AC1.
"""

import types
import uuid

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem


class _CapturingBus:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event_type, data=None, turn_id=None, conversation_id=None, session_id=None):
        self.events.append(
            {
                "type": event_type,
                "data": data or {},
                "turn_id": turn_id,
                "conversation_id": conversation_id,
                "session_id": session_id,
            }
        )


class TestTaskStartRevisionOrigin:
    """The payload carries an origin; revisions re-emit through the same channel."""

    def test_payload_contract_and_origin_vocabulary(self):
        """REQ-14 AC5: the payload is one construction point with the
        merge-by-id contract keys PLUS an origin in the documented
        vocabulary (initial | sub_loop_split | user_steering)."""
        # UPDATED 2026-08-19 by task-card-v2-liquid-ink T1 (REQ-3 AC1/AC2) —
        # CALLED OUT DELIBERATELY, not a silent fix.
        # This test and backend/tests/unit/test_task_start_payload_baseline.py
        # pin the SAME producer from two different specs. T1 adds three identity
        # keys (card_id / card_relation / conversation_id) to every task:start
        # payload, so the exact-equality literal here moves from 7 keys to 10.
        # RE-UPDATED 2026-08-21 by cli-workspace-unification T9a (REQ-5 AC1):
        # agent_id / project_id join additively (backend-emitted Kanban tags),
        # moving the literal from 10 keys to 12; direct calls default both to
        # None because the kernel-resolved values arrive via _multiagent_tags()
        # at the real emit sites.
        # RE-UPDATED 2026-08-21, session 244 (card↔response inline join):
        # turn_id joins additively — the kernel's current response turn id
        # (self._current_turn_id), the SAME id space as the assistant message
        # id on the frontend, so a card can render inline with its response
        # (the join documents already use). Literal moves from 12 keys to 13;
        # direct calls default it to None because the live value arrives from
        # kernel state at the real emit sites.
        # WHAT THIS TEST ASSERTS IS UNCHANGED: one construction point, no drift
        # between emit sites, and the origin vocabulary passing through. The
        # assertion is still EXACT equality — that strictness is the whole point,
        # because it is what proves each addition was additive, not a rewrite.
        payload = AgentKernel._task_start_payload(
            task_id="t1", description="d", plan_title="p", mode="full",
            steps=[{"id": "s1"}], total_steps=1, origin="initial",
            card_id="card_t1", card_relation="new", conversation_id="conv_1",
        )
        assert payload == {
            "task_id": "t1",
            "description": "d",
            "plan_title": "p",
            "mode": "full",
            "steps": [{"id": "s1"}],
            "total_steps": 1,
            "origin": "initial",
            "card_id": "card_t1",
            "card_relation": "new",
            "conversation_id": "conv_1",
            "agent_id": None,
            "project_id": None,
            "turn_id": None,
        }
        # NOTE: a fourth origin, "amendment", exists in agent_kernel.py and is not
        # in this docstring's vocabulary. Left as found — correcting that belongs
        # to specs/long-horizon-der-execution, not here. The three below still
        # pass through unchanged, which is what this loop asserts.
        for origin in ("initial", "sub_loop_split", "user_steering"):
            assert AgentKernel._task_start_payload(
                task_id="t", description="d", plan_title="p", mode="m",
                steps=[], total_steps=0, origin=origin,
                card_id="card_t", card_relation="new", conversation_id="conv_1",
            )["origin"] == origin

    def test_split_revision_reemits_with_sub_loop_split_origin(self, monkeypatch):
        """REQ-14 AC1/AC5 end-to-end: a genuine verify_failed split re-emits
        task:start through the SAME channel with origin="sub_loop_split" and
        the revised (child-bearing) step list — the explicit revision signal."""
        from backend.agent.event_bus import IRISStreamEvent

        k = AgentKernel.__new__(AgentKernel)
        k._memory_interface = None
        k._tool_bridge = None
        k._reviewer = None
        k._mcm_orch = None
        k.conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
        k.session_id = f"sess_{uuid.uuid4().hex[:8]}"
        k._der_work_units = 30000
        k._der_crawl_attempts = {}
        k._der_task_class = "full"
        k._der_completed_tools = []

        # Seam-patch the trajectory recorder (test_failed_step_writes_commit_row
        # pattern): the kernel imports get_trajectory_recorder lazily, so patch
        # the module function, not the class.
        import backend.agent.caducean_trajectory as ct

        class _StubRecorder:
            def record_commit(self, *a, **kw):
                pass

            def record_fan_trace(self, *a, **kw):
                pass

            def get_latest_coordinate(self, *a, **kw):
                return ""

            def add_session(self, *a, **kw):
                pass

            def close(self, *a, **kw):
                pass

        monkeypatch.setattr(ct, "get_trajectory_recorder", lambda _mi: _StubRecorder())

        bus = _CapturingBus()
        monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)

        fail_item = QueueItem(
            step_id="s9", step_number=9, description="do risky thing",
            objective_anchor="obj", depth_layer=0,
            expected_output="thing done correctly",
        )
        queue = DirectorQueue(objective="obj")
        queue.add_item(fail_item)
        plan_ns = types.SimpleNamespace(
            steps=[fail_item], original_task="obj", plan_title="smoke"
        )
        ctx = types.SimpleNamespace()

        k._der_finalize_step(
            fail_item,
            "[step 9 completed]",  # bare stub -> FAILED -> split
            False,
            [(fail_item, "[step 9 completed]")],
            [fail_item],
            0,
            30000,
            k.session_id,
            "turn-9",
            "execute",
            False,
            None,
            plan_ns,
            ctx,
            queue,
            None,
        )

        # A real FAILED semantic step splits into Sub-Loop children...
        assert any(c.is_subloop for c in queue.items), "verify_failed must split"
        # ...and REQ-14 AC1/AC5: the revision re-emits task:start with the
        # sub_loop_split origin and the REVISED (child-bearing) step list.
        starts = [e for e in bus.events if e["type"] == IRISStreamEvent.TASK_START]
        revision = [e for e in starts if e["data"].get("origin") == "sub_loop_split"]
        assert len(revision) == 1, (
            "a sub-loop split emits exactly ONE revision signal "
            "(REQ-14 AC1 — distinct revision signal)"
        )
        data = revision[0]["data"]
        for key in ("task_id", "description", "plan_title", "mode", "steps", "total_steps"):
            assert key in data, f"contract key {key!r} missing from revision emit"
        child_ids = {c.step_id for c in queue.items if c.is_subloop}
        assert child_ids, "split must have produced children"
        assert data["total_steps"] == len(queue.items)
        assert {s["id"] for s in data["steps"]} >= child_ids, (
            "revision payload carries the new sub-loop steps"
        )
