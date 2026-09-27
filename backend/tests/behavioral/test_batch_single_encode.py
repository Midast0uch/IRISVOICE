"""REQ-20 batched scoring is REMOVED — this file guards the removal.

THE MEASUREMENT THAT REMOVED IT (2026-09-26, real model). Three DISTINCT
questions (distinct instructions, distinct consumer ids, own labels) were
scored two ways against the same state:

    in one batch of three, `bench_t40_m1` chose "no"
    scored alone, the same question chose "yes"

So batching MOVED a verdict. The pre-existing tests here only ever compared a
batch of ONE against a solo run (equal within 1e-6), which is why this stayed
invisible while the machinery looked healthy.

WHY THAT MATTERS MORE THAN THE SPEED. The calibrated threshold is only valid
for the distribution it was measured on (solo runs, one question per session
run). A consumer enforced on a batched verdict is enforced on a curve nobody
measured — the same silent mis-enforcement class as judging GLiNER at 0.85
instead of 0.40.

WHY IT COULD NOT BE FIXED CHEAPLY. JEV's fan-out property is INDEPENDENCE:
"one answer is never hidden context for another, so adding or removing a
question does not move the others." Sharing one encoder pass across questions
is exactly what breaks that. With this ONNX export, one session run carries one
question's context, so reading the state once AND isolating the questions is not
available without re-exporting the model — which means a new backend identity
and a fresh calibration.

THE OWNER'S RULE (2026-09-26): no parallelism without a no-regression benefit.
`decide_many` is therefore DELETED from both `GlinerOnnx` and `DecisionEngine`
rather than left in place, because the temptation is the danger. These tests
fail loudly if it comes back, and re-adding it requires a NEW calibration for
the batch shape — not a call site.
"""

from __future__ import annotations

import inspect

import backend.agent.decision_backend_onnx as backend_mod
import backend.agent.decision_engine as engine_mod
from backend.agent.decision_backend_onnx import GlinerOnnx
from backend.agent.decision_engine import DecisionEngine


class TestBatchingStaysRemoved:
    def test_the_batched_entry_point_is_gone_from_the_backend(self):
        assert not hasattr(GlinerOnnx, "decide_many"), (
            "batched scoring came back on the ONNX backend — it was measured "
            "to change verdicts, so the calibrated threshold does not apply "
            "to a batched answer (see this file's docstring)"
        )

    def test_the_batched_entry_point_is_gone_from_the_engine(self):
        assert not hasattr(DecisionEngine, "decide_many"), (
            "batched scoring came back on the engine — re-adding it needs a "
            "NEW calibration for the batch shape, not a call site"
        )

    def test_the_removal_is_recorded_where_the_code_used_to_be(self):
        """A future reader must find WHY, in the file they are editing, not
        only in a spec or a graph."""
        for module in (backend_mod, engine_mod):
            src = inspect.getsource(module)
            assert "decide_many" in src, "the removal note vanished"
            assert "REMOVED 2026-09-26" in src, (
                f"{module.__name__}: the removal note lost its date, so the "
                "reason is no longer traceable to the decision"
            )

    def test_no_production_module_asks_for_a_batch(self):
        """The entry point is gone, so a call site would be a NameError at
        runtime — this catches one at test time instead."""
        for module in (backend_mod, engine_mod):
            src = inspect.getsource(module)
            code = "\n".join(
                ln for ln in src.splitlines() if not ln.strip().startswith("#")
            )
            assert "decide_many(" not in code, (
                f"{module.__name__}: a batch CALL site survived the removal"
            )
