"""Behavioural tests: one encode, one session run per batch (REQ-30 AC30.3, T40).

AC30.3 — WHEN multiple consumers are batched THEN THE SYSTEM SHALL perform ONE
encode and ONE session run for the batch, VERIFIED rather than assumed.

REQ-20 claims this natively; the reference runner builds structure tokens per
`Task`, so the claim needed counting. The runner now records `encode_calls` and
`run_calls`, and this suite is what makes the numbers mean something.
"""

from __future__ import annotations

from backend.agent.decision_backend_onnx import (
    ConsumerSpec,
    build_task,
    register_consumer_spec,
)


def _register(consumer_id: str) -> None:
    register_consumer_spec(ConsumerSpec(
        consumer_id=consumer_id,
        task_name=consumer_id,
        instruction="Pick one.",
        labels=("yes", "no"),
    ))


class TestOneEncodeOneSessionRun:
    def test_one_encode_one_session_run(self, onnx_backend):
        """AC30.3: N consumers → ONE encode, ONE session run."""
        consumers = ("bench_t40_a", "bench_t40_b", "bench_t40_c")
        for cid in consumers:
            _register(cid)

        runner = onnx_backend._runner
        runner.encode_calls = 0
        runner.run_calls = 0

        out = onnx_backend.decide_many(
            [(cid, ["yes", "no"]) for cid in consumers],
            {"goal": "is this statement true"},
        )

        assert set(out) == set(consumers), out
        assert all(v is not None for v in out.values()), (
            f"a batched consumer returned no verdict: {out}"
        )
        assert runner.encode_calls == 1, (
            f"the batch encoded {runner.encode_calls} times — REQ-20/AC30.3 "
            "claims ONE encode for the batch"
        )
        assert runner.run_calls == 1, (
            f"the batch ran the session {runner.run_calls} times — AC30.3 "
            "claims ONE session run for the batch"
        )

    def test_batch_returns_the_same_envelope_as_per_consumer(self, onnx_backend):
        """AC20.4: batching is a latency optimisation, not a different answer."""
        cid = "bench_t40_solo"
        _register(cid)

        batched = onnx_backend.decide_many(
            [(cid, ["yes", "no"])], {"goal": "is this statement true"})
        single = onnx_backend.decide(
            cid, ["yes", "no"], {"goal": "is this statement true"})

        assert batched[cid] is not None and single is not None
        assert batched[cid].chosen == single.chosen
        assert abs(batched[cid].confidence - single.confidence) < 1e-6

    def test_a_consumer_without_criteria_does_not_break_the_batch(
        self, onnx_backend,
    ):
        """AC20.4: per-question isolation — one un-scorable consumer is None
        and the OTHERS still score in the same single run."""
        good = "bench_t40_good"
        _register(good)

        runner = onnx_backend._runner
        runner.encode_calls = 0
        runner.run_calls = 0

        out = onnx_backend.decide_many(
            [(good, ["yes", "no"]), ("no_such_consumer_t40", ["yes", "no"])],
            {"goal": "is this statement true"},
        )

        assert out["no_such_consumer_t40"] is None, (
            "a criteria-less consumer was scored instead of refused (REQ-19)"
        )
        assert out[good] is not None, "the scorable consumer was lost with it"
        assert runner.run_calls == 1, (
            "the un-scorable consumer forced an extra session run"
        )

    def test_a_single_decide_encodes_and_runs_once(self, onnx_backend):
        """The per-consumer path is one encode + one run, as before."""
        runner = onnx_backend._runner
        runner.encode_calls = 0
        runner.run_calls = 0

        assert onnx_backend.decide(
            "tool_choice", ["alpha", "beta"], {"goal": "pick"}) is not None
        assert (runner.encode_calls, runner.run_calls) == (1, 1)

    def test_a_multi_consumer_batch_matches_its_single_runs(self, onnx_backend):
        """T40 / BT-DEI-13 — the case that can invalidate the threshold.

        Batching is a latency optimisation ONLY IF each question's verdict is
        unchanged. `test_batch_returns_the_same_envelope_as_per_consumer` above
        pins a batch of ONE. This pins a batch of THREE, where a single
        encoder pass sees several questions at once — attention over the joint
        input is exactly the mechanism that could shift a distribution and
        silently invalidate the 0.40 threshold (AC20.2, AC30.3 edge).

        Measured, not assumed: this is the answer to "can we score every
        consumer in one run and still trust the mark?"
        """
        cids = ("bench_t40_m1", "bench_t40_m2", "bench_t40_m3")
        for i, cid in enumerate(cids):
            # DISTINCT questions, as production has: each consumer asks its own
            # thing with its own labels. Three identical questions would only
            # prove that a confused input is confused.
            register_consumer_spec(ConsumerSpec(
                consumer_id=cid, task_name=cid,
                instruction=f"Question number {i + 1} for this state?",
                labels=("yes", "no"),
            ))
        state = {"goal": "is this statement true"}

        batched = onnx_backend.decide_many(
            [(cid, ["yes", "no"]) for cid in cids], state)

        for cid in cids:
            single = onnx_backend.decide(cid, ["yes", "no"], state)
            assert batched[cid] is not None and single is not None, cid
            assert batched[cid].chosen == single.chosen, (
                f"{cid}: the batch picked a different option than the solo run"
            )
            assert abs(batched[cid].confidence - single.confidence) < 1e-6, (
                f"{cid}: batch confidence {batched[cid].confidence} != solo "
                f"{single.confidence} — batching MOVES the distribution, so "
                "the calibrated threshold does not transfer to a batch"
            )


class TestBatchSharesOneStructure:
    def test_distinct_label_sets_share_one_encoder_pass(self, onnx_runner):
        """AC30.3 edge: two DIFFERENT label sets still share one encode — the
        structure cache makes the second task's assembly cheap, and the batch
        does not fall back to N encodes."""
        t1 = build_task("tool_choice", ["alpha", "beta"])
        t2 = build_task("tool_choice", ["one", "two", "three"])
        assert t1 is not None and t2 is not None

        onnx_runner.encode_calls = 0
        ids, positions = onnx_runner.encode("a goal", [t1, t2])

        assert onnx_runner.encode_calls == 1
        assert len(ids) > 0 and len(positions) >= 2
