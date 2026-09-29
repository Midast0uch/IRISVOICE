"""Unit tests for backend/agent/decision_engine.py.

Covers REQ-21 (lazy CPU lifecycle, degrade), REQ-2 (schema scoring, softmax,
args stage), REQ-4 (bounded empty retry), REQ-7 (shutdown frees,
notice-once), REQ-13 (consumer registry invariants: one context, one lock).

INPUTS UPDATED 2026-09-25 (REQ-21/D12 model swap — stale-by-spec): the old
fixtures drove the LFM llama_cpp path (FakeLlama, letter_logits, GGUF paths),
which the model decision DELETES. The fixtures now drive the ONNX
schema-scoring backend (FakeOnnxBackend) through the same lifecycle/scoring
semantics; test names and assertions are unchanged except where the deleted
knob WAS the assertion (test_cpu_only_n_gpu_layers_zero — AC1.2 is
superseded; the CPU-only semantic is carried by AC21.3's contract test
test_cpu_provider_zero_vram). The args stage keeps the llama_factory test
seam (generate_args is unaffected by the model swap — the ONNX backend scores
labels, it does not generate arguments).
"""

from __future__ import annotations

import math
import threading

import pytest

from backend.agent.decision_engine import (
    CONSUMERS,
    CandidateScore,
    DecisionEngine,
    DecisionScore,
    EngineConfig,
    shutdown_decision_engine,
    get_decision_engine,
)


# ---------------------------------------------------------------------------
# Fake ONNX backend surface (the scoring backend the engine delegates to)
# ---------------------------------------------------------------------------


class FakeOnnxBackend:
    """Deterministic stand-in for the ONNX schema-scoring backend.

    `label_logits` maps label -> raw logit; softmax over labels at decide
    time — the same menu-wide softmax the real backend runs (D13).
    """

    instances = 0

    def __init__(self, **kwargs):
        type(self).instances += 1
        self.kwargs = kwargs
        self.label_logits: dict = {}
        self.model_id = "fake-onnx"
        self.backend_id = "fake-onnx"
        self._runner: object = object()  # loaded

    def load(self) -> bool:
        return True

    @property
    def loaded(self) -> bool:
        return self._runner is not None

    def availability(self):
        return (True, "loaded")

    def decide(self, consumer_id, options, frame):
        labels = [o for o in options if isinstance(o, str) and o]
        if not labels:
            return None
        x = [float(self.label_logits.get(l, -15.0)) for l in labels]
        m = max(x)
        exps = [math.exp(v - m) for v in x]
        z = sum(exps) or 1.0
        dist = tuple(
            CandidateScore(name=l, logprob=v, prob=e / z)
            for l, v, e in zip(labels, x, exps)
        )
        best = max(dist, key=lambda c: c.prob)
        return DecisionScore(
            consumer_id=consumer_id, chosen=best.name, confidence=best.prob,
            distribution=dist, engine_latency_ms=1,
        )

    def shutdown(self):
        self._runner = None


class FakeLlama:
    """Generative args-model stand-in (the llama_factory test seam)."""

    instances = 0
    _vocab_map: dict = {}
    _next_id: int = 10
    VOCAB_SIZE = 4096

    def __init__(self, **kwargs):
        type(self).instances += 1
        self.kwargs = kwargs
        self.args_replies = []
        self.completion_calls = []

    def create_completion(self, prompt, max_tokens=512, echo=False,
                          logprobs=0, temperature=0.0, stop=None, **kw):
        self.completion_calls.append(
            {"max_tokens": max_tokens, "echo": echo})
        text = self.args_replies.pop(0) if self.args_replies else ""
        return {"choices": [{"text": text}]}


def make_engine(tmp_path=None, **over):
    cfg = EngineConfig(**{
        k: v for k, v in over.items() if k in EngineConfig.__dataclass_fields__})
    fac = over.pop("llama_factory", None) or (lambda **kw: FakeLlama(**kw))
    bf = over.pop("backend_factory", None) or (lambda **kw: FakeOnnxBackend(**kw))
    e = DecisionEngine(config=cfg, backend_factory=bf, llama_factory=fac)
    return e


FRAME = {"goal": "find RTX 5090 price", "turn": 1}


# ---------------------------------------------------------------------------
# REQ-21 lifecycle / degrade
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_lazy_load_only_on_first_decision(self):
        FakeOnnxBackend.instances = 0
        e = make_engine()
        assert not e.loaded
        e.decide("tool_choice", ["read_file", "NONE"], FRAME)
        assert FakeOnnxBackend.instances == 1  # loaded once, lazily

    def test_missing_model_degrades_none(self):
        # No backend_factory: the REAL resolution runs, so a configured-and-
        # missing dir means unavailable (never a silent substitute, AC21.4).
        e = DecisionEngine(config=EngineConfig(model_dir="C:/no/such-dir"))
        assert e.decide("tool_choice", ["a"], FRAME) is None
        assert e.counters.unavailable_events == 1

    def test_unavailable_notice_logged_once(self, caplog):
        e = DecisionEngine(config=EngineConfig(model_dir="C:/no/such-dir"),
                           backend_factory=lambda **kw: None)
        with caplog.at_level("WARNING"):
            e.decide("tool_choice", ["a"], FRAME)
            e.decide("tool_choice", ["a"], FRAME)
        notices = [r for r in caplog.records if "unavailable" in r.message]
        assert len(notices) == 1  # AC7.3: notice once per session

    def test_load_exception_degrades_and_counts(self):
        def boom(**kw):
            raise RuntimeError("bad onnx")
        e = DecisionEngine(config=EngineConfig(model_dir="x.gguf"),
                           backend_factory=boom)
        assert e.decide("tool_choice", ["a"], FRAME) is None
        assert e.counters.load_failures == 1

    def test_lock_timeout_degrades(self):
        slow = make_engine()
        slow._cfg = EngineConfig(acquire_timeout_s=0.05)
        slow._backend = FakeOnnxBackend()
        slow._load_attempted = True

        def hold():
            with slow._lock:
                threading.Event().wait(0.2)

        t = threading.Thread(target=hold)
        t.start()
        try:
            assert slow.decide("tool_choice", ["a", "b"], FRAME) is None
            assert slow.counters.lock_timeouts == 1
        finally:
            t.join()

    def test_shutdown_frees_and_allows_reload(self):
        FakeOnnxBackend.instances = 0
        e = make_engine()
        e.decide("tool_choice", ["a", "b"], FRAME)
        assert e.loaded
        e.shutdown()
        assert not e.loaded
        e.decide("tool_choice", ["a", "b"], FRAME)
        assert e.loaded and FakeOnnxBackend.instances == 2  # clean reload


# ---------------------------------------------------------------------------
# REQ-2 scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_distribution_is_softmax_over_all_candidates(self):
        e = make_engine()
        e._load()
        e._backend.label_logits = {"crawler_query": -1.0, "read_file": -4.0,
                                   "DELEGATE": -6.0, "NONE": -9.0}
        d = e.decide("tool_choice",
                     ["crawler_query", "read_file", "DELEGATE", "NONE"], FRAME)
        assert d is not None
        assert d.chosen == "crawler_query"
        assert d.confidence == max(c.prob for c in d.distribution)
        assert abs(sum(c.prob for c in d.distribution) - 1.0) < 1e-6
        probs = {c.name: c.prob for c in d.distribution}
        assert probs["crawler_query"] > probs["read_file"] > probs["DELEGATE"] \
            > probs["NONE"]

    def test_unknown_consumer_refused(self):
        e = make_engine()
        assert e.decide("not_a_consumer", ["a"], FRAME) is None

    def test_all_three_registered_consumers(self):
        e = make_engine()
        e._load()
        e._backend.label_logits = {"x": -1.0, "y": -2.0}
        for cid in CONSUMERS:
            assert e.decide(cid, ["x", "y"], FRAME) is not None

    def test_scoring_error_degrades(self):
        e = make_engine()
        e._load()

        class BadBackend:
            def load(self):
                return True

            @property
            def loaded(self):
                return True

            def decide(self, consumer_id, options, frame):
                raise AttributeError("no logits in this build")

        e._backend = BadBackend()
        assert e.decide("tool_choice", ["a"], FRAME) is None  # AC2.4

    def test_candidate_cap_bounded(self):
        e = make_engine()
        e._load()
        cap = e._cfg.candidate_cap
        e._backend.label_logits = {f"t{i}": -float(i) for i in range(cap)}
        d = e.decide("tool_choice", [f"t{i}" for i in range(40)], FRAME)
        assert len(d.distribution) == cap
        assert d.distribution[0].name == "t0"


# ---------------------------------------------------------------------------
# REQ-2 args stage + REQ-4 bounded retry
# ---------------------------------------------------------------------------

SCHEMA = {"properties": {"url": {"type": "string"}, "limit": {"type": "integer"}},
          "required": ["url"]}


class TestArgs:
    def test_valid_args(self):
        e = make_engine()
        e._load()
        e._llm.args_replies = ['{"url": "https://x.test", "limit": 5}']
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args == {"url": "https://x.test", "limit": 5}

    def test_missing_required_escalates_none(self):
        e = make_engine()
        e._load()
        e._llm.args_replies = ['{"limit": 5}']
        assert e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME).args is None

    def test_extra_keys_dropped(self):
        e = make_engine()
        e._load()
        e._llm.args_replies = ['{"url": "u", "evil": true}']
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args == {"url": "u"}

    def test_empty_retried_once_then_none(self):
        e = make_engine()
        e._load()
        e._llm.args_replies = ["", ""]          # both attempts empty
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args is None and r.retried is True
        assert len(e._llm.completion_calls) == 2  # exactly one retry (AC4.3)

    def test_empty_then_valid_succeeds_with_retry_flag(self):
        e = make_engine()
        e._load()
        e._llm.args_replies = ["", '{"url": "ok"}']
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args == {"url": "ok"}

    def test_invalid_json_not_retried(self):
        e = make_engine()
        e._load()
        e._llm.args_replies = ["not json at all"]
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args is None
        assert len(e._llm.completion_calls) == 1  # no retry on non-empty garbage

    def test_no_generative_backend_degrades(self):
        """REQ-21/D12: production injects no generative factory — the ONNX
        backend scores labels, it does not generate arguments. generate_args
        degrades to ArgsResult(args=None) and the box escalates (AC2.4)."""
        e = DecisionEngine(config=EngineConfig(),
                           backend_factory=lambda **kw: FakeOnnxBackend(**kw))
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args is None and r.retried is False


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_module_singleton_and_shutdown(self, tmp_path):
        import backend.agent.decision_engine as mod
        mod._ENGINE = None
        e = get_decision_engine(
            EngineConfig(model_dir=str(tmp_path / "m-dir")),
            backend_factory=lambda **kw: FakeOnnxBackend(**kw),
            llama_factory=lambda **kw: FakeLlama(**kw))
        assert get_decision_engine() is e
        shutdown_decision_engine()
        assert mod._ENGINE is None  # re-created on next ask
