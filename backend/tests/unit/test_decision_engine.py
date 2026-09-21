"""Unit tests for backend/agent/decision_engine.py.

Covers REQ-1 (lazy CPU lifecycle, degrade), REQ-2 (parallel candidate scoring,
softmax, args stage), REQ-4 (bounded empty retry), REQ-7 (shutdown frees,
notice-once), REQ-13 (consumer registry invariants: one context, one lock).

The llama reality is faked by FakeLlama via the llama_factory seam; the engine's
own logic (locking, softmax, validation, retry, degradation) is the real thing.
"""

from __future__ import annotations

import threading

import pytest

from backend.agent.decision_engine import (
    CONSUMERS,
    DecisionEngine,
    EngineConfig,
    shutdown_decision_engine,
    get_decision_engine,
)


# ---------------------------------------------------------------------------
# Fake llama_cpp surface
# ---------------------------------------------------------------------------


class FakeLlama:
    """Deterministic stand-in for the one-pass scoring protocol.

    `letter_logits` maps "A"/"B"/â€¦ to a logit value; option N gets letter
    N (options order == enumeration order, by engine design).
    """

    instances = 0
    _vocab_map: dict = {}
    _next_id: int = 10
    VOCAB_SIZE = 4096

    def __init__(self, **kwargs):
        type(self).instances += 1
        self.kwargs = kwargs
        self.letter_logits = {}
        self.args_replies = []
        self.completion_calls = []
        self._scores = None

    @classmethod
    def _id(cls, piece: str) -> int:
        if piece not in cls._vocab_map:
            if cls._next_id >= cls.VOCAB_SIZE:
                raise ValueError("fake vocab exhausted")
            cls._vocab_map[piece] = cls._next_id
            cls._next_id += 1
        return cls._vocab_map[piece]

    def tokenize(self, data: bytes, add_bos: bool = True):
        s = data.decode("utf-8")
        if len(s) <= 4:
            return [self._id(s)]          # short variants = single tokens
        ids = [self._id(p) for p in s.split()]
        return ([self._id("<bos>")] if add_bos else []) + ids

    def eval(self, tokens):
        n = len(tokens)
        empty_row = [-15.0] * self.VOCAB_SIZE
        rows = [list(empty_row) for _ in range(n)]
        final = rows[-1]
        # name-first-TOKEN scoring: engine scores the FIRST TOKEN of the
        # first word of the option name (identifier before the first "_").
        for name, val in self.letter_logits.items():
            word = " " + name.split("_")[0]
            first_tok = self.tokenize(word.encode("utf-8"), add_bos=False)
            for i in first_tok:
                final[i] = float(val)
        self._scores = rows

    @property
    def scores(self):
        return self._scores

    def reset(self):
        pass

    def create_completion(self, prompt, max_tokens=512, echo=False,
                          logprobs=0, temperature=0.0, stop=None, **kw):
        self.completion_calls.append(
            {"max_tokens": max_tokens, "echo": echo})
        text = self.args_replies.pop(0) if self.args_replies else ""
        return {"choices": [{"text": text}]}


def make_engine(tmp_path=None, **over):
    model = tmp_path / "LFM2-350M-Q4_K_M.gguf" if tmp_path else "x.gguf"
    if tmp_path:
        model.write_bytes(b"gguf")
    cfg = EngineConfig(model_path=str(model), **{
        k: v for k, v in over.items() if k in EngineConfig.__dataclass_fields__})
    fac = over.pop("llama_factory", None) or (lambda **kw: FakeLlama(**kw))
    e = DecisionEngine(config=cfg, llama_factory=fac)
    return e


FRAME = {"goal": "find RTX 5090 price", "turn": 1}


# ---------------------------------------------------------------------------
# REQ-1 lifecycle / degrade
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_lazy_load_only_on_first_decision(self, tmp_path):
        FakeLlama.instances = 0
        e = make_engine(tmp_path)
        assert not e.loaded
        e.decide("tool_choice", ["read_file", "NONE"], FRAME)
        assert FakeLlama.instances == 1  # loaded once, lazily

    def test_cpu_only_n_gpu_layers_zero(self, tmp_path):
        seen = {}
        def cap(**kw):
            seen.update(kw)
            return FakeLlama(**kw)
        e = make_engine(tmp_path, llama_factory=cap)
        e.decide("tool_choice", ["a", "b"], FRAME)
        assert seen["n_gpu_layers"] == 0

    def test_missing_model_degrades_none(self):
        e = DecisionEngine(config=EngineConfig(model_path="C:/no/such.gguf"),
                           llama_factory=lambda **kw: FakeLlama(**kw))
        assert e.decide("tool_choice", ["a"], FRAME) is None
        assert e.counters.unavailable_events == 1

    def test_unavailable_notice_logged_once(self, caplog):
        e = DecisionEngine(config=EngineConfig(model_path="C:/no/such.gguf"),
                           llama_factory=lambda **kw: None)
        with caplog.at_level("WARNING"):
            e.decide("tool_choice", ["a"], FRAME)
            e.decide("tool_choice", ["a"], FRAME)
        notices = [r for r in caplog.records if "unavailable" in r.message]
        assert len(notices) == 1  # AC7.3: notice once per session

    def test_load_exception_degrades_and_counts(self):
        def boom(**kw):
            raise RuntimeError("bad gguf")
        e = DecisionEngine(config=EngineConfig(model_path="x.gguf"),
                           llama_factory=boom)
        e._cfg.model_path = __file__  # any existing file so the path check passes
        assert e.decide("tool_choice", ["a"], FRAME) is None
        assert e.counters.load_failures == 1

    def test_lock_timeout_degrades(self, tmp_path):
        slow = make_engine(tmp_path)
        slow._cfg = EngineConfig(model_path=__file__, acquire_timeout_s=0.05)
        slow._llm = FakeLlama()
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

    def test_shutdown_frees_and_allows_reload(self, tmp_path):
        FakeLlama.instances = 0
        e = make_engine(tmp_path)
        e.decide("tool_choice", ["a", "b"], FRAME)
        assert e.loaded
        e.shutdown()
        assert not e.loaded
        e.decide("tool_choice", ["a", "b"], FRAME)
        assert e.loaded and FakeLlama.instances == 2  # clean reload after free


# ---------------------------------------------------------------------------
# REQ-2 scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_distribution_is_softmax_over_all_candidates(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.letter_logits = {"crawler_query": -1.0, "read_file": -4.0,
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

    def test_unknown_consumer_refused(self, tmp_path):
        e = make_engine(tmp_path)
        assert e.decide("not_a_consumer", ["a"], FRAME) is None

    def test_all_three_registered_consumers(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.letter_logits = {"x": -1.0, "y": -2.0}
        for cid in CONSUMERS:
            assert e.decide(cid, ["x", "y"], FRAME) is not None

    def test_scoring_error_degrades(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()

        class Bad:
            @staticmethod
            def tokenize(b, add_bos=True):
                return b.split()

            def eval(self, tokens):
                pass

            def reset(self):
                pass

            @property
            def scores(self):
                raise AttributeError("no logits in this build")

        e._llm = Bad()
        assert e.decide("tool_choice", ["a"], FRAME) is None  # AC2.4

    def test_candidate_cap_bounded(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        cap = e._cfg.candidate_cap
        e._llm.letter_logits = {f"t{i}": -float(i) for i in range(cap)}
        d = e.decide("tool_choice", [f"t{i}" for i in range(40)], FRAME)
        assert len(d.distribution) == cap
        assert d.distribution[0].name == "t0"


# ---------------------------------------------------------------------------
# REQ-2 args stage + REQ-4 bounded retry
# ---------------------------------------------------------------------------

SCHEMA = {"properties": {"url": {"type": "string"}, "limit": {"type": "integer"}},
          "required": ["url"]}


class TestArgs:
    def test_valid_args(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.args_replies = ['{"url": "https://x.test", "limit": 5}']
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args == {"url": "https://x.test", "limit": 5}

    def test_missing_required_escalates_none(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.args_replies = ['{"limit": 5}']
        assert e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME).args is None

    def test_extra_keys_dropped(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.args_replies = ['{"url": "u", "evil": true}']
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args == {"url": "u"}

    def test_empty_retried_once_then_none(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.args_replies = ["", ""]          # both attempts empty
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args is None and r.retried is True
        assert len(e._llm.completion_calls) == 2  # exactly one retry (AC4.3)

    def test_empty_then_valid_succeeds_with_retry_flag(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.args_replies = ["", '{"url": "ok"}']
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args == {"url": "ok"}

    def test_invalid_json_not_retried(self, tmp_path):
        e = make_engine(tmp_path)
        e._load()
        e._llm.args_replies = ["not json at all"]
        r = e.generate_args("tool_choice", "crawler_query", SCHEMA, FRAME)
        assert r.args is None
        assert len(e._llm.completion_calls) == 1  # no retry on non-empty garbage


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_module_singleton_and_shutdown(self, tmp_path):
        import backend.agent.decision_engine as mod
        mod._ENGINE = None
        e = get_decision_engine(
            EngineConfig(model_path=str(tmp_path / "m.gguf")),
            llama_factory=lambda **kw: FakeLlama(**kw))
        assert get_decision_engine() is e
        shutdown_decision_engine()
        assert mod._ENGINE is None  # re-created on next ask
