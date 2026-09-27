"""Unit tests: per-consumer schema Tasks (REQ-19 AC19.1/AC19.2, T25/T26).

AC19.1  each consumer is expressed as its OWN Task (instruction + label set),
        not one shared head reused across consumers.
AC19.2  several consumers are passed as separate Tasks in ONE call.
"""

from __future__ import annotations

from backend.agent.decision_backend_onnx import (
    CONSUMER_TASKS,
    ConsumerSpec,
    GlinerOnnx,
    build_task,
    register_consumer_spec,
)


class _Runner:
    """Fake ONNX runner: records every call and the tasks in it."""

    def __init__(self, logits=None):
        self.calls = 0
        self.task_names: list = []
        self._logits = logits

    def logits(self, text, tasks):
        self.calls += 1
        self.task_names = [t.name for t in tasks]
        if self._logits is not None:
            return self._logits
        # deterministic: first label wins
        return {
            t.name: {l: (1.0 if i == 0 else 0.0) for i, l in enumerate(t.labels)}
            for t in tasks
        }


def _backend(runner) -> GlinerOnnx:
    b = GlinerOnnx(model_dir="unused")
    b._runner = runner  # load() short-circuits on a set runner
    return b


def _spec(cid: str, **kw) -> ConsumerSpec:
    base = dict(
        consumer_id=cid, task_name=cid,
        instruction=f"Question for {cid}?", labels=("yes", "no"),
    )
    base.update(kw)
    return ConsumerSpec(**base)


class TestTaskBuiltFromConsumerSpec:
    def test_task_built_from_consumer_spec(self):
        """AC19.1: the Task carries the consumer's OWN instruction + labels."""
        register_consumer_spec(_spec("tst_on_track",
                                     instruction="Is the step on track?"))
        t = build_task("tst_on_track", [])
        assert t.instruction == "Is the step on track?"
        assert list(t.labels) == ["yes", "no"]
        assert t.exclusive is True

        # a menu-shaped consumer takes its labels from the caller instead
        register_consumer_spec(_spec("tst_menu", instruction="Which one?",
                                     labels=()))
        t2 = build_task("tst_menu", ["alpha", "beta"])
        assert t2.instruction == "Which one?"
        assert list(t2.labels) == ["alpha", "beta"]

    def test_consumer_without_criteria_is_refused(self):
        """REQ-19 edge: no registered criteria → refuse, never borrow another
        consumer's head."""
        CONSUMER_TASKS.pop("tst_missing", None)
        assert build_task("tst_missing", ["a", "b"]) is None

        register_consumer_spec(_spec("tst_nocriteria", criteria=False))
        assert build_task("tst_nocriteria", ["a"]) is None


class TestMultiTaskSingleCall:
    """REQ-20 batched scoring was REMOVED 2026-09-26 (owner decision).

    This class used to prove "N consumers in ONE runner call". It is gone with
    the API it tested, and so is the `decide_many` entry point on BOTH the
    backend and the engine (see `test_batch_single_encode.py` for the guard and
    the measurement that caused it: a batch of three distinct questions changed
    a verdict, so the calibrated threshold does not transfer to a batched
    answer).

    What SURVIVES and is still tested above: the per-consumer Task specs
    (REQ-19) — each consumer has its own instruction and labels, and `decide()`
    builds exactly one Task from them. Consumers are scored ONE AT A TIME.
    """
