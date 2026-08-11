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
        payload = AgentKernel._task_start_payload(
            task_id="t1", description="d", plan_title="p", mode="full",
            steps=[{"id": "s1"}], total_steps=1, origin="initial",
        )
        assert payload == {
            "task_id": "t1",
            "description": "d",
            "plan_title": "p",
            "mode": "full",
            "steps": [{"id": "s1"}],
            "total_steps": 1,
            "origin": "initial",
        }
        for origin in ("initial", "sub_loop_split", "user_steering"):
            assert AgentKernel._task_start_payload(
                task_id="t", description="d", plan_title="p", mode="m",
                steps=[], total_steps=0, origin=origin,
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
