"""Contract tests: inference off the shared step threads (REQ-30 AC30.5, T42).

AC30.5 — THE ENGINE SHALL run inference off the shared step threads, so step
scheduling cannot contend with it.

Step execution already runs on a shared pool (`agent_kernel.py:9421`,
`:15690`). Before T42 each of those threads drove ONNX directly, so the
engine's intra-op threads competed with step scheduling and the CPU was
oversubscribed whenever several steps resolved at once. The engine now owns ONE
dedicated inference thread.
"""

from __future__ import annotations

import threading

from backend.agent.decision_engine import (
    _INFER_THREAD_PREFIX,
    DecisionEngine,
    EngineConfig,
)
from backend.agent.decision_engine import CandidateScore, DecisionScore


class _ThreadRecordingBackend:
    """Records WHICH thread ran the scoring."""

    def __init__(self):
        self.threads: list = []
        self.model_id = "thread-stub"

    def load(self) -> bool:
        return True

    def decide(self, consumer_id, options, frame):
        self.threads.append(threading.current_thread().name)
        return DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.9,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == options[0] else 0.1)
                for o in options
            ),
            engine_latency_ms=1,
        )

    def shutdown(self) -> None:
        pass


def _engine(backend):
    eng = DecisionEngine(EngineConfig(), backend_factory=lambda **kw: backend)
    # Pre-load: the subject is the THREAD, not the load path.
    eng._backend = backend
    eng._load_attempted = True
    return eng


class TestInferenceOffSharedStepThreads:
    def test_inference_off_shared_step_threads(self):
        """AC30.5: scoring happens on the dedicated engine thread, never on the
        caller's step thread."""
        backend = _ThreadRecordingBackend()
        eng = _engine(backend)
        result = {}

        def _call_from_a_step_thread():
            result["d"] = eng.decide("tool_choice", ["alpha", "beta"],
                                     {"goal": "pick one"})

        worker = threading.Thread(
            target=_call_from_a_step_thread, name="step-pool-1")
        worker.start()
        worker.join(timeout=30)

        assert result.get("d") is not None, "the decision was lost"
        assert backend.threads, "the backend was never asked to score"
        assert backend.threads[0].startswith(_INFER_THREAD_PREFIX), (
            f"inference ran on {backend.threads[0]!r} — the caller's step "
            f"thread. It must run on the dedicated {_INFER_THREAD_PREFIX}* "
            "thread (AC30.5)"
        )
        assert backend.threads[0] != "step-pool-1"
        eng.shutdown()

    # `test_batch_also_runs_on_the_dedicated_thread` was DELETED 2026-09-26:
    # it exercised `decide_many`, which the owner retired (it was measured to
    # change verdicts, so the calibrated threshold does not transfer to a
    # batched answer). The isolation it checked is still covered by the solo
    # test above — and by the nested-call test below.

    def test_nested_call_does_not_deadlock(self):
        """A call made FROM the inference thread must run inline, not queue
        behind itself."""
        backend = _ThreadRecordingBackend()
        eng = _engine(backend)
        done = {}

        def _reentrant():
            # Already on the inference thread: this must not deadlock.
            done["d"] = eng.decide("tool_choice", ["a", "b"], {"goal": "g"})

        eng._get_infer_pool().submit(_reentrant).result(timeout=30)

        assert done.get("d") is not None, "the nested call deadlocked"
        assert backend.threads[0].startswith(_INFER_THREAD_PREFIX)
        eng.shutdown()

    def test_pool_failure_degrades_inline(self, monkeypatch):
        """A pool that cannot be built must not lose the decision — the work
        runs inline (today's behaviour) instead."""
        backend = _ThreadRecordingBackend()
        eng = _engine(backend)
        monkeypatch.setattr(eng, "_get_infer_pool", lambda: None)

        d = eng.decide("tool_choice", ["a", "b"], {"goal": "g"})

        assert d is not None, "a missing pool lost the decision"
        assert backend.threads == ["MainThread"] or not backend.threads[0].startswith(
            _INFER_THREAD_PREFIX
        )
        eng.shutdown()

    def test_shutdown_releases_the_inference_thread(self):
        """The pool is engine-owned and must not outlive the engine."""
        backend = _ThreadRecordingBackend()
        eng = _engine(backend)
        eng.decide("tool_choice", ["a", "b"], {"goal": "g"})
        pool = eng._infer_pool
        assert pool is not None

        eng.shutdown()

        assert eng._infer_pool is None, (
            "shutdown left the dedicated inference pool alive"
        )
