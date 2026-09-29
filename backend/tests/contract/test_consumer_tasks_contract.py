"""Contract tests: per-consumer Task specs (REQ-19 AC19.3, T25).

CT-DEI-9 — Consumer Head Binding: the Task used to score a consumer matches
that consumer's REGISTERED specification, so another consumer's labels or
instruction can never be silently reused.
"""

from __future__ import annotations

from backend.agent.decision_backend_onnx import (
    CONSUMER_TASKS,
    ConsumerSpec,
    build_task,
    register_consumer_spec,
)


def _spec(cid: str, **kw) -> ConsumerSpec:
    base = dict(consumer_id=cid, task_name=cid,
                instruction=f"Question for {cid}?")
    base.update(kw)
    return ConsumerSpec(**base)


class TestTaskMatchesRegisteredSpec:
    def test_task_matches_registered_spec(self):
        """AC19.3: the scored Task is built FROM the registered spec — same
        instruction, same labels, same task name."""
        register_consumer_spec(_spec(
            "tst_review", task_name="tst_review",
            instruction="Should this step pass, be refined, or be vetoed?",
            labels=("pass", "refine", "veto"),
        ))
        spec = CONSUMER_TASKS["tst_review"]

        t = build_task("tst_review", [])
        assert t.name == spec.task_name
        assert t.instruction == spec.instruction
        assert list(t.labels) == list(spec.labels)
        assert t.exclusive == spec.exclusive

    def test_two_consumers_never_share_a_head(self):
        """AC19.3: distinct consumers produce distinct Tasks — the silent-reuse
        defect this contract exists to catch."""
        register_consumer_spec(_spec("tst_x", instruction="Question X?",
                                     labels=("yes", "no")))
        register_consumer_spec(_spec("tst_y", instruction="Question Y?",
                                     labels=("up", "down")))

        tx = build_task("tst_x", [])
        ty = build_task("tst_y", [])

        assert tx.instruction != ty.instruction
        assert list(tx.labels) != list(ty.labels)
        assert tx.name != ty.name

    def test_tool_choice_keeps_the_pinned_bench_task(self):
        """AC19.4 (contract half): tool_choice's Task is byte-identical to the
        measured bench shape — otherwise the 0.40 threshold curve is invalid."""
        t = build_task("tool_choice", ["read_file", "NONE"])
        assert t.name == "tool"
        assert t.instruction == "Which tool should handle this request?"
        assert list(t.labels) == ["read_file", "NONE"]
        assert t.exclusive is True
        # labels carry NO descriptions — an unmeasured prompt change would
        # invalidate the threshold (AC22.1/D13).
        assert all(v is None for v in t.labels.values())
