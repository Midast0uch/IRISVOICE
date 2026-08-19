"""Contract: a sub-loop split's re-emitted `task:start` labels the CHILD
steps it just produced, and only those steps.

specs/task-card-v2-liquid-ink REQ-1 AC8 — tasks.md T2b.

T8's `CardChassis` exports `ChassisBranchBadge`, which renders
`↳ {branchLabel}`. `branchLabel` is free text supplied by the backend — the
chassis hardcodes no copy. Decision 13 (revised 2026-08-19): the words are
"Diving Deeper", never "Sub-Loop" and never "Detour" — those stay as
internal identifiers (`sub_loop_split` / `is_subloop`) only.

Pinned here, driven through the REAL split path
(`AgentKernel._der_finalize_step` -> `_split_step` ->
`_der_route_subloop_children` -> the `task:start` revision emit), reusing
the harness from test_task_start_revision_origin.py's
`test_split_revision_reemits_with_sub_loop_split_origin`:

  - the child steps created by the split carry `branchLabel == "Diving Deeper"`.
  - every OTHER step in the same revision payload (the parent/unbranched
    steps) carries NO `branchLabel` key at all — not `None`, not `""`.
  - the literal string "Sub-Loop" appears on no user-facing wire field of
    the emitted payload (CT-9).
"""

import json
import types
import uuid

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


class TestSubLoopSplitBranchLabel:
    def test_split_children_carry_diving_deeper_branch_label(self, monkeypatch):
        """REQ-1 AC8 (T2b): a real verify_failed split's revision emit sets
        branchLabel="Diving Deeper" on the child steps only; unbranched
        steps carry no branchLabel key, and "Sub-Loop" reaches no
        user-facing field (CT-9)."""
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

        # Seam-patch the trajectory recorder — same pattern as
        # test_task_start_revision_origin.py.
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

        assert any(c.is_subloop for c in queue.items), "verify_failed must split"
        starts = [e for e in bus.events if e["type"] == IRISStreamEvent.TASK_START]
        revision = [e for e in starts if e["data"].get("origin") == "sub_loop_split"]
        assert len(revision) == 1
        data = revision[0]["data"]

        child_ids = {c.step_id for c in queue.items if c.is_subloop}
        assert child_ids, "split must have produced children"

        steps_by_id = {s["id"]: s for s in data["steps"]}
        assert child_ids <= set(steps_by_id), "revision payload carries the new sub-loop steps"

        for step_id, step in steps_by_id.items():
            if step_id in child_ids:
                # Fails if the assignment in agent_kernel.py is removed —
                # the key would be absent, not merely a different value.
                assert step.get("branchLabel") == "Diving Deeper", (
                    f"child step {step_id!r} must carry branchLabel='Diving Deeper', "
                    f"got {step.get('branchLabel')!r}"
                )
            else:
                assert "branchLabel" not in step, (
                    f"unbranched step {step_id!r} must carry NO branchLabel key "
                    f"(got {step.get('branchLabel')!r}) — every-row badges are a defect"
                )

        # CT-9: "Sub-Loop" is an internal identifier only — it must never
        # reach a user-facing wire field.
        assert "Sub-Loop" not in json.dumps(data)
