"""Calibrated small-model decision engine — ORACLE (Jev/RLCD pattern reproduction).

Spec: specs/tool-decision-engine-improvements (REQ-21, REQ-22, REQ-25, REQ-26).

NAME vs KEY (read this before renaming anything). ``Oracle`` is the engine's
DISPLAY name — what a human reads in logs, telemetry and the UI. The technical
keys stay exactly as they are, because they carry meaning that a rename would
destroy:
  * the config block id ``oracle`` (agent_config.yaml) is what
    ``load_engine_config`` looks up; and
  * the backend identity ``gliner25-decide-onnx-int8`` KEYS THE CALIBRATED
    THRESHOLD (``backend_thresholds``, REQ-22 AC22.1 / REQ-25 AC25.8). Renaming
    that key marks every measured curve unaddressable and enforcement
    fail-closes — a rename there is a configuration migration, not a label
    change.

One resident decision backend, loaded in-process: GLiNER2.5-Decide via its
torch-free ONNX export (REQ-21/D12 — replaced LFM2-350M-Extract; measured
71.7% @119 ms vs 60.0% @1172 ms, with all errors <= 0.352 confidence). It
never writes to memory, never emits events, never touches the 8082 server or
the VRAM ledger. Its only job: score a caller-provided option set against a
caller-provided feature frame and return a probability distribution.
Consumers: `tool_choice` (Wave 2), `presentation` and `narration` (Wave 4).

Two primitives, both return DecisionScore/ArgsResult or None (None = degrade
to legacy path):
  - decide(consumer_id, options, frame)      — Jev "Choice" (schema scoring)
  - generate_args(consumer_id, option, schema, frame) — constrained args JSON

The ONNX backend scores labels; it does not generate arguments (D12), so
``generate_args`` has no generative backend in production and degrades to
``ArgsResult(args=None)`` — the box then escalates to the legacy ladder, where
the Brain does schema-constrained generation via function-calling (AC2.4).
The generative path stays behind the ``llama_factory`` test seam so the args
stage stays testable.

Everything here is single-writer-of-nothing: read set is the args passed in;
write set is the return value, counters, and log lines. CT-DE-5 enforces it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

logger = logging.getLogger("decision_engine")

# The engine's DISPLAY name. Logs, telemetry and the UI read THIS; the config
# block id and the backend identity stay untouched (see the module docstring:
# the backend identity keys the calibrated threshold).
ENGINE_NAME = "Oracle"

# ---------------------------------------------------------------------------
# Data model (CT-DE-1 pins this shape)
# ---------------------------------------------------------------------------

CONSUMERS: Tuple[str, ...] = (
    "tool_choice",
    "presentation",
    "narration",
    # REQ-11 AC11.3 (T15): the graft-recovery triage consumer. Consulted BEFORE
    # Brain planning spend — the Brain plans only on DELEGATE / below threshold.
    # REQ-13 AC13.1 (T17): the per-step Reviewer verdict consumer, SHADOW only
    # (the Brain verdict still decides until AC13.3's measured bar is met).
    # NOTE: this grows the pinned consumer set; the two CT-DE-7 enumerations
    # were updated as a STALE-BY-SPEC change (the spec mandates the consumers).
    "recovery_strategy",
    "review_verdict",
    # REQ-14 AC14.1 (T18): the three loop-monitor bool consumers, answered with
    # a `Noul` (P(statement true)) rather than a two-option Choice (AC14.6).
    "sufficient",
    "done",
    "on_track",
    # REQ-15 AC15.1 (T19): mode + web_intent shadow the ModeDetector keyword
    # branch and the duplicated web-trigger lists.
    "mode",
    "web_intent",
    # REQ-17 AC17.1 (T21): the retry_same triage extension.
    "retry_same",
    # REQ-29 (T46–T49): the remaining decision surface — four choice-shaped
    # Brain decisions scored in shadow. `has_gaps` is the highest-value miss
    # (an 800-token Brain call per completed step). `tier0_classify` is a
    # recorded NON-FIT and is deliberately absent (AC29.5).
    "has_gaps",
    "use_thinking",
    "escalate_incomplete",
    "needs_action",
)


@dataclass(frozen=True)
class CandidateScore:
    name: str        # option name (tool name, surface name, or DELEGATE/NONE)
    logprob: float   # raw label logit under the schema prompt (ONNX backend)
    prob: float      # softmax-normalized probability


@dataclass(frozen=True)
class DecisionScore:
    consumer_id: str
    chosen: str
    confidence: float                 # = P(chosen)
    distribution: Tuple[CandidateScore, ...]
    engine_latency_ms: int
    retried: bool = False
    # REQ-17 hierarchical detail: stage scores when a two-stage tree was used.
    # The tree is retired (REQ-22 AC22.3 — flat scoring is the only path), so
    # this is always None today; the field stays because the envelope shape is
    # pinned unchanged (AC21.2).
    stage_detail: Optional[Dict[str, Any]] = None

    def confident(self, threshold: float) -> bool:
        """True when the calibrated probability clears the threshold."""
        return self.confidence >= threshold


@dataclass(frozen=True)
class Noul:
    """REQ-14 AC14.6 (T18): a single calibrated probability of TRUTH.

    Deliberately NOT a two-option ``DecisionScore``. JEV's ``Noul`` returns
    P(statement true) with no separate confidence field, and REQ-14 AC14.4's
    fail-closed advisory gate depends on that probability meaning exactly what
    it claims: "is the statement true", not "which of two labels won".

    The measurement may be a two-label softmax (the schema backend scores
    ``yes``/``no`` and we take P(yes)) — the ENVELOPE is what changes: one
    probability, no winner, no confidence, so a caller cannot mistake a
    2-way choice for a calibrated belief.
    """

    consumer_id: str
    probability: float                # P(statement is true), in [0, 1]
    engine_latency_ms: int

    def true(self, threshold: float = 0.5) -> bool:
        """The boolean judgment at *threshold*."""
        return self.probability >= threshold

    def confident(self, threshold: float) -> bool:
        """True when the belief is decisively on ONE side of the flip point.

        ``threshold`` is a probability margin, and the test is TWO-SIDED:
        ``p >= threshold`` (confidently true) or ``p <= 1 - threshold``
        (confidently false). A one-sided ``p >= threshold`` would let the
        engine assert "true" but never "false" — an asymmetry that would leave
        a fail-closed gate permanently open.
        """
        return self.probability >= threshold or self.probability <= (1.0 - threshold)


@dataclass(frozen=True)
class ArgsResult:
    args: Optional[Dict[str, Any]]    # None = invalid/empty after retry
    retried: bool
    # REQ-10 AC10.3 (T13): which deterministic pattern filled the args, when a
    # fast path was taken ("" = the LLM/generation path). ADDITIVE field — the
    # envelope shape is otherwise unchanged (AC21.2). It is the calibration
    # join key, so a pattern id is a STABLE name, never a re-worded one.
    fast_path: str = ""


@dataclass
class EngineCounters:
    decisions: int = 0
    escalations: int = 0              # filled in by the box (kept here for one read site)
    memory_fallbacks: int = 0
    retries: int = 0
    unavailable_events: int = 0
    load_failures: int = 0
    lock_timeouts: int = 0
    # REQ-13 AC13.3: per-consumer accounting so calibration reads them apart.
    by_consumer: Dict[str, int] = field(default_factory=dict)

    def bump_consumer(self, consumer_id: str) -> None:
        self.by_consumer[consumer_id] = self.by_consumer.get(consumer_id, 0) + 1


# Gate enforcement modes (D10): tool_choice enforces at birth; the two visible
# consumers (presentation cards, narration speech) start shadow — recorded but
# non-binding — and flip to enforce only after the calibration gate. Override
# with IRIS_DECISION_ENFORCE="tool_choice,presentation,narration".
def enforced_consumers() -> frozenset:
    """The consumers currently enforced (REQ-13..17, REQ-31 AC31.4).

    FAIL-CLOSED ON A STALE CONFIGURATION. `EngineConfig.threshold_for` already
    refuses to hand out a threshold when the deployed cap differs from the
    calibrated width, but that only makes an enforcing caller see `None` — a
    caller that forgets to check would still steer. This closes the hole at the
    SOURCE: when the deployed configuration differs from the calibrated one, NO
    consumer is enforced, so no flip measured at a superseded configuration can
    stand (AC31.4/AC31.6). A match is the normal case and enforcement proceeds
    exactly as before.
    """
    raw = os.environ.get("IRIS_DECISION_ENFORCE", "tool_choice")
    wanted = frozenset(
        c.strip() for c in raw.split(",") if c.strip() in CONSUMERS
    )
    if not wanted:
        return frozenset()
    # Reading staleness must NEVER be able to break the reply path. A config
    # object without the attribute (a stub, a partially-built engine) means
    # "not stale" — and the real fail-closed guarantee is unaffected, because
    # `threshold_for` independently returns None on a stale configuration, so
    # an enforcing caller still cannot steer on a superseded curve.
    try:
        cfg = getattr(get_decision_engine(), "_cfg", None)
        _stale_attr = (
            getattr(cfg, "threshold_stale", None) if cfg is not None else None
        )
        stale = bool(_stale_attr() if callable(_stale_attr) else _stale_attr)
    except Exception as e:  # noqa: BLE001 — an unreadable config changes nothing
        logger.debug("decision_engine: staleness unreadable (%r)", e)
        return wanted
    if stale:
        logger.warning(
            "decision_engine: deployed configuration differs from the "
            "calibrated one (candidate_cap=%s, calibrated_cap=%s) — thresholds "
            "are STALE, refusing enforcement for %s (AC31.4)",
            getattr(cfg, "candidate_cap", None),
            getattr(cfg, "calibrated_cap", None),
            sorted(wanted),
        )
        return frozenset()
    return wanted


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    model_dir: Optional[str] = None      # explicit ONNX model dir wins
    max_args_tokens: int = 192
    acquire_timeout_s: float = 2.0
    # The ACTIVE backend identity (AC25.8). Set from the loaded backend at
    # load time; thresholds resolve against it.
    backend_id: Optional[str] = None
    # THRESHOLDS ARE KEYED BY BACKEND IDENTITY (REQ-22 AC22.1, REQ-25 AC25.8).
    # A probability threshold is only meaningful for the distribution it was
    # measured on: 0.85 suits LFM's sharpened softmax, 0.40 suits GLiNER's
    # menu-wide softmax. Keyed by backend, a model swap degrades to SHADOW
    # (no entry for the new backend = fail-closed) instead of silently
    # enforcing on the previous model's curve.
    backend_thresholds: Dict[str, float] = None  # set in __post_init__ below
    # Per-consumer thresholds (REQ-13): tools that execute external side effects
    # sit higher than display gates; calm narration anti-spamming sits lower.
    # Ordered: explicit per-consumer → backend threshold (by active identity).
    thresholds: Dict[str, float] = None  # set in __post_init__ below
    # Bounded cost per decision. Ships at 6 — the menu width the 0.40
    # accuracy/coverage curve was derived at (Decision C, REQ-25 AC25.7).
    # Changing it marks the calibrated threshold STALE (AC25.5).
    candidate_cap: int = 6
    # The menu width the current threshold curve was derived at (AC25.7).
    # A candidate_cap that differs from this marks the threshold STALE
    # (AC25.5): enforcement is refused until the curve is re-derived.
    calibrated_cap: int = 6

    def __post_init__(self) -> None:
        if self.backend_thresholds is None:
            self.backend_thresholds = {}
        if self.thresholds is None:
            self.thresholds = {}

    def threshold_stale(self) -> bool:
        """AC25.5: True when the deployed cap differs from the calibrated
        width — the threshold is stale and enforcement is refused until the
        curve is re-derived (REQ-31 AC31.4)."""
        return self.candidate_cap != self.calibrated_cap

    def threshold_for(self, consumer_id: str) -> Optional[float]:
        """Threshold for one consumer, keyed by ACTIVE BACKEND IDENTITY.

        Resolution (AC22.1/AC25.8): explicit per-consumer override → the
        active backend's ``backend_thresholds`` entry. Returns None when the
        active backend has no entry, or when the deployed cap differs from
        the calibrated width (AC25.5 stale → fail-closed) — callers REFUSE
        ENFORCEMENT: the consumer stays shadow rather than enforcing on an
        unknown curve.
        """
        if self.threshold_stale():
            return None
        if consumer_id in (self.thresholds or {}):
            return float(self.thresholds[consumer_id])
        bt = self.backend_thresholds or {}
        if self.backend_id in bt:
            return float(bt[self.backend_id])
        return None


# ---------------------------------------------------------------------------
# Config authority (REQ-25): the oracle block parsed into EngineConfig
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = "./backend/agent/agent_config.yaml"
_config_fallback_logged = False


def _log_config_fallback(why: str) -> None:
    global _config_fallback_logged
    if not _config_fallback_logged:
        _config_fallback_logged = True
        logger.warning(
            "oracle config fallback (%s) — code defaults apply", why
        )


def load_engine_config(
    config_path: str = _DEFAULT_CONFIG_PATH,
) -> EngineConfig:
    """Parse the ``oracle`` block into EngineConfig (REQ-25 AC25.1).

    Every documented key is parsed or removed (AC25.6). A missing or malformed
    key falls back to the code default and logs the fallback ONCE (AC25.3) —
    never crashes, never silently accepts a partial config. The block is
    located by id, not by position. Never raises.
    """
    global _config_fallback_logged
    cfg = EngineConfig()
    try:
        import yaml  # lazy — config parsing is not on the decision hot path

        p = Path(config_path)
        if not p.is_file():
            if config_path == _DEFAULT_CONFIG_PATH:
                # The default path is CWD-relative; try the module-relative
                # location before giving up (robustness, not substitution).
                p = Path(__file__).resolve().parent / "agent_config.yaml"
            if not p.is_file():
                _log_config_fallback("config file not found")
                return cfg
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        block = None
        for m in data.get("models", []) or []:
            if isinstance(m, dict) and m.get("id") == "oracle":
                block = m
                break
        if block is None:
            _log_config_fallback("oracle block not found")
            return cfg
        constraints = block.get("constraints")
        if not isinstance(constraints, dict):
            _log_config_fallback("constraints malformed")
            constraints = {}
        path = block.get("path")
        if path:
            cfg.model_dir = str(path)
        cap = constraints.get("candidate_cap")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0:
            cfg.candidate_cap = cap
        elif cap is not None:
            _log_config_fallback(f"candidate_cap malformed: {cap!r}")
        ato = constraints.get("acquire_timeout_s")
        if isinstance(ato, (int, float)) and not isinstance(ato, bool) and ato > 0:
            cfg.acquire_timeout_s = float(ato)
        elif ato is not None:
            _log_config_fallback(f"acquire_timeout_s malformed: {ato!r}")
        bt = constraints.get("backend_thresholds")
        if isinstance(bt, dict) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in bt.values()
        ):
            cfg.backend_thresholds = {str(k): float(v) for k, v in bt.items()}
        elif bt is not None:
            _log_config_fallback("backend_thresholds malformed")
        th = constraints.get("thresholds")
        if isinstance(th, dict) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in th.values()
        ):
            cfg.thresholds = {str(k): float(v) for k, v in th.items()}
        elif th is not None:
            _log_config_fallback("thresholds malformed")
        return cfg
    except Exception as e:
        _log_config_fallback(f"parse failed: {e!r}")
        return cfg


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


# AC30.5 (T42): the name every dedicated-inference worker carries. The engine
# detects "already on the inference thread" by this prefix, so it must stay in
# sync with the pool's `thread_name_prefix`.
_INFER_THREAD_PREFIX = "iris-decision-inference"


class DecisionEngine:
    """One serialized ONNX scoring backend. CPU only. Lazy load. Never raises."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        backend_factory: Optional[Callable[..., Any]] = None,  # test seam
        llama_factory: Optional[Callable[..., Any]] = None,    # args test seam
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._cfg = config or EngineConfig()
        self._backend_factory = backend_factory
        self._llama_factory = llama_factory
        self._clock = clock
        self._lock = threading.Lock()
        # AC30.5 (T42): ONE dedicated inference thread. Step execution already
        # runs on a shared pool (`agent_kernel.py:9421`, `:15690`); letting
        # each of those threads drive ONNX directly made the engine's intra-op
        # threads contend with step scheduling and oversubscribed the CPU when
        # several steps resolved at once. Lazily created, so an engine that
        # never scores pays nothing.
        self._infer_pool: Any = None
        self._infer_pool_lock = threading.Lock()
        # The ONNX scoring backend (lazy; the only scorer — no fallback model).
        self._backend: Any = None
        # Generative args model. Test seam ONLY: production injects no factory
        # (the ONNX backend scores labels, it does not generate arguments),
        # so this stays None and generate_args degrades (AC2.4 escalates).
        self._llm: Any = None
        self._load_attempted = False
        self._notice_logged = False
        self.counters = EngineCounters()
        self.model_id: Optional[str] = None

    # -- dedicated inference thread (AC30.5 / T42) -------------------------

    def _get_infer_pool(self) -> Any:
        """The single-worker pool that owns model inference, or None.

        Created once, lazily. Returns None when the pool cannot be built, so
        the caller can fall back to an inline call rather than lose a decision.
        Never raises.
        """
        if self._infer_pool is not None:
            return self._infer_pool
        with self._infer_pool_lock:
            if self._infer_pool is None:
                try:
                    from concurrent.futures import ThreadPoolExecutor

                    self._infer_pool = ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix=_INFER_THREAD_PREFIX,
                    )
                except Exception as e:  # noqa: BLE001 — plumbing, not the work
                    logger.debug(
                        "decision_engine: inference pool unavailable (%r)", e
                    )
                    return None
        return self._infer_pool

    def _run_inference(self, fn: Callable[[], Any]) -> Any:
        """AC30.5 (T42): run backend inference on the dedicated engine thread.

        Serialises the model work (which the engine lock already did) while
        keeping ONNX's intra-op threads off the step scheduler's CPU budget and
        out of a step thread's stack.

        Degradation is deliberate and total: an unusable pool runs the work
        inline (today's behaviour), while a pool that accepted the work but
        overran its budget returns None — the same "no verdict, use the legacy
        path" contract every other engine failure uses (AC26.1). The work is
        NEVER retried after submission, because a retry would score twice.
        Runs inline when already on the inference thread, so a nested call
        cannot deadlock. Never raises.
        """
        if threading.current_thread().name.startswith(_INFER_THREAD_PREFIX):
            return fn()
        pool = self._get_infer_pool()
        if pool is None:
            return fn()
        try:
            return pool.submit(fn).result(
                timeout=float(self._cfg.acquire_timeout_s) * 2.0 + 5.0
            )
        except Exception as e:  # noqa: BLE001 — never lose a decision to plumbing
            from concurrent.futures import TimeoutError as _FuturesTimeout

            if isinstance(e, _FuturesTimeout):
                self.counters.lock_timeouts += 1
                logger.warning(
                    "decision_engine: inference overran its budget on the "
                    "dedicated thread — returning no verdict"
                )
            else:
                logger.warning(
                    "decision_engine: inference on the dedicated thread "
                    "failed: %r", e,
                )
            return None

    # -- lifecycle ---------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    @property
    def model_hash(self) -> Optional[str]:
        """The deployed model file's sha256 (AC6.5/AC22.5 attribution) —
        delegated to the backend; None before load."""
        backend = self._backend
        if backend is None:
            return None
        return getattr(backend, "model_hash", None)

    def availability(self) -> Tuple[bool, str]:
        """(usable, reason). Never raises."""
        if self._backend is not None:
            return True, "loaded"
        if self._load_attempted:
            return False, "load_failed_or_missing"
        try:
            from backend.agent.decision_backend_onnx import resolve_model_dir

            if resolve_model_dir(self._cfg.model_dir) is None:
                return False, "model_dir_not_found"
        except Exception:
            pass
        return True, "loadable_pending"

    def _load(self) -> bool:
        """Load the ONNX scoring backend. Lazy, once. Never raises.

        Also creates the generative args model from an injected factory
        (test seam only — production has none).
        """
        if self._backend is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        if self._llama_factory is not None and self._llm is None:
            try:
                self._llm = self._llama_factory()
            except Exception as e:
                self.counters.load_failures += 1
                self._log_unavailable(f"args model load failed: {e!r}")
        try:
            factory = self._backend_factory
            if factory is None:
                from backend.agent.decision_backend_onnx import (
                    GlinerOnnx,  # heavy import kept lazy
                )

                def factory(**kwargs: Any) -> Any:
                    return GlinerOnnx(**kwargs)

            backend = factory(model_dir=self._cfg.model_dir)
            if backend is None or not backend.load():
                self._log_unavailable(
                    "onnx model dir not found or incomplete — no fallback model"
                )
                return False
            self._backend = backend
            self.model_id = getattr(backend, "backend_id", None) or getattr(
                backend, "model_id", None
            )
            self._cfg.backend_id = self.model_id  # AC25.8: active identity
            logger.info(
                "%s loaded backend=%s", ENGINE_NAME, self.model_id
            )
            return True
        except Exception as e:  # load failure must never escape (AC1.3)
            self._backend = None
            self.counters.load_failures += 1
            self._log_unavailable(f"backend load failed: {e!r}")
            return False

    def _log_unavailable(self, why: str) -> None:
        if not self._notice_logged:
            self._notice_logged = True
            self.counters.unavailable_events += 1
            logger.warning("decision_engine unavailable (%s) — using legacy path", why)

    @property
    def name(self) -> str:
        """The engine's DISPLAY name (telemetry, logs, UI).

        Deliberately separate from ``model_id``: this is a label, while
        ``model_id`` is the backend identity that KEYS the calibrated
        threshold. Renaming this changes nothing about enforcement.
        """
        return ENGINE_NAME

    def effective_config(self) -> Dict[str, Any]:
        """AC25.2: the effective configuration, observable.

        Returns the resolved engine config as a plain dict — backend identity
        included — so a config round-trip can prove a non-default value
        actually takes effect. Never raises.
        """
        return {
            "name": ENGINE_NAME,
            "model_dir": self._cfg.model_dir,
            "backend_id": self.model_id or self._cfg.backend_id,
            "candidate_cap": self._cfg.candidate_cap,
            "acquire_timeout_s": self._cfg.acquire_timeout_s,
            "backend_thresholds": dict(self._cfg.backend_thresholds or {}),
            "thresholds": dict(self._cfg.thresholds or {}),
        }

    def shutdown(self) -> None:
        """Free the backend. Idempotent. Called from the lifespan teardown."""
        with self._lock:
            backend, self._backend = self._backend, None
            self._llm = None
            self._load_attempted = False
        # AC30.5 (T42): the dedicated inference thread is engine-owned, so it
        # must not outlive the engine.
        pool, self._infer_pool = self._infer_pool, None
        if pool is not None:
            try:
                pool.shutdown(wait=False)
            except Exception:
                pass
        if backend is not None:
            try:
                shutdown = getattr(backend, "shutdown", None)
                if callable(shutdown):
                    shutdown()
            except Exception:
                pass

    # -- scoring (Jev Choice over a caller-provided option set) ------------

    def decide(
        self,
        consumer_id: str,
        options: Sequence[str],
        frame: Dict[str, Any],
    ) -> Optional[DecisionScore]:
        """Score every option in one schema pass; softmax; return winner +
        distribution.

        Returns None when the engine is unavailable, the lock times out, or
        scoring fails — callers treat None as "degrade to legacy path" (AC1.3,
        AC2.4). Never raises.
        """
        if consumer_id not in CONSUMERS:
            logger.error("decision_engine: unknown consumer %r", consumer_id)
            return None
        opts = [o for o in options if isinstance(o, str) and o][
            : self._cfg.candidate_cap
        ]
        if not opts:
            return None
        t_start = self._clock()  # REQ-26: lock-wait separated from compute
        if not self._lock.acquire(timeout=self._cfg.acquire_timeout_s):
            self.counters.lock_timeouts += 1
            return None
        lock_wait_ms = int((self._clock() - t_start) * 1000)
        try:
            if not self._load():
                return None
            backend = self._backend
            t0 = self._clock()
            # AC30.5 (T42): the model work runs on the dedicated inference
            # thread, never on the caller's step thread.
            ds = self._run_inference(
                lambda: backend.decide(consumer_id, opts, frame))
            scoring_ms = int((self._clock() - t0) * 1000)
            if ds is None:
                return None
            self.counters.decisions += 1
            self.counters.bump_consumer(consumer_id)  # REQ-13 per-consumer
            total_ms = int((self._clock() - t_start) * 1000)
            logger.info(
                "%s decide consumer=%s chosen=%s conf=%.3f "
                "candidates=%d scoring_latency_ms=%d lock_wait_ms=%d "
                "decision_latency_ms=%d backend=%s",
                ENGINE_NAME, consumer_id, ds.chosen, ds.confidence,
                len(ds.distribution),
                scoring_ms, lock_wait_ms, total_ms, self.model_id,
            )
            return ds
        except Exception as e:
            logger.warning("decision_engine scoring failed: %r", e)
            return None
        finally:
            self._lock.release()

    def noul(
        self,
        consumer_id: str,
        statement: str,
        frame: Optional[Dict[str, Any]] = None,
        *,
        true_label: str = "yes",
        false_label: str = "no",
    ) -> Optional[Noul]:
        """REQ-14 AC14.6 (T18): score a STATEMENT and return P(true).

        The bool monitor consumers (``sufficient`` / ``done`` / ``on_track``)
        ask "is this statement true", so they are answered with a ``Noul`` — a
        single calibrated probability — rather than a two-option Choice.

        Returns None when the engine is unavailable, the consumer has no
        criteria, or scoring fails. Callers MUST treat None as fail-closed
        (REQ-14 AC14.4) rather than as "true". Never raises.
        """
        try:
            ds = self.decide(
                consumer_id, [true_label, false_label],
                frame if frame is not None else {"goal": statement},
            )
            if ds is None:
                return None
            prob = 0.0
            for c in (ds.distribution or ()):
                if c.name == true_label:
                    prob = float(c.prob)
                    break
            else:
                return None  # the true label was not scored — refuse to guess
            return Noul(
                consumer_id=consumer_id,
                probability=prob,
                engine_latency_ms=ds.engine_latency_ms,
            )
        except Exception as e:  # noqa: BLE001 — fail-closed, never raises
            logger.warning("decision_engine noul failed: %r", e)
            return None

    # ── REQ-20 BATCHED SCORING — REMOVED 2026-09-26 (owner decision) ───────
    # `decide_many` used to live here. It is deleted, not disabled, so the
    # mistake cannot be repeated by calling it:
    #   * MEASURED with the real model: a batch of three distinct questions
    #     CHANGED a verdict (batch "no" where the same question scored alone
    #     answered "yes"). So the calibrated threshold, measured on solo runs,
    #     does not transfer to a batched verdict.
    #   * JEV's fan-out property is INDEPENDENCE ("one answer is never hidden
    #     context for another"). This export cannot provide it: one session run
    #     carries one question's context, so sharing the read while isolating
    #     the questions is impossible without changing the model.
    #   * The owner's rule: no parallelism without no-regression benefit.
    # The speed this promised is therefore unavailable, and the honest levers
    # left are: score fewer consumers, reuse the same-question cache, tune ORT
    # threads, keep the engine warm. Re-adding a batch requires a NEW
    # calibration for the batch shape, not a call site.

    # -- constrained args generation (bounded empty retry, REQ-4) ----------
    # REQ-2: single-parameter query tools — the goal text maps directly to
    # the 'query' parameter in 0ms, bypassing generate_args token generation
    # (+500-1,500ms of autoregressive generation saved).
    _SINGLE_PARAM_QUERY_TOOLS = frozenset({"search", "crawler_query"})

    # ── REQ-10 (T13): vision target fast path ──────────────────────────────
    # Pattern ids are STABLE calibration join keys (AC10.3) — renaming one
    # splits the historical rows into a different pattern.
    _VISION_TARGET_TOOL = "vision_detect_element"
    _VISION_TARGET_PARAM = "description"
    _CLICK_VERB = re.compile(r"\b(?:click|tap|press)\b", re.IGNORECASE)
    # Straight quotes (either style) and curly quotes (either orientation).
    _QUOTED_TARGET = re.compile(
        r'"([^"]+)"'
        r"|'([^']+)'"
        r"|\u201c([^\u201c\u201d]+)\u201d"
        r"|\u201e([^\u201e\u201c]+)\u201c"
    )
    _THE_X_BUTTON = re.compile(
        r"\bthe\s+([A-Za-z0-9][A-Za-z0-9 _\-]{0,60}?)\s+button\b", re.IGNORECASE
    )
    _MAX_TARGET_LEN = 120

    def fast_path_args(
        self,
        option: str,
        schema: Dict[str, Any],
        frame: Dict[str, Any],
    ) -> Optional[ArgsResult]:
        """REQ-2 + REQ-10: deterministic fast-path slot filling.

        REQ-2 — single-parameter query tools (search, crawler_query): the user
        goal text maps directly to the 'query' parameter in 0ms.
        REQ-10 (T13) — ``vision_detect_element``: a click/tap/press goal whose
        target is quoted, or written as "the X button", fills the element
        target in 0ms with zero LLM tokens.

        Returns None when no fast path applies (a different tool, a multi-arg
        schema, an empty goal, or no pattern match) — the caller falls back to
        generate_args / the legacy ladder (AC2.4, AC10.2). Never raises.
        """
        try:
            if option == self._VISION_TARGET_TOOL:
                props = (schema.get("properties") or {})
                if self._VISION_TARGET_PARAM not in props:
                    return None  # never fabricate a param the schema lacks
                return self._vision_target_fast_path(frame)
            if option not in self._SINGLE_PARAM_QUERY_TOOLS:
                return None
            required = [
                k for k, v in (schema.get("properties") or {}).items()
                if not (v or {}).get("optional", False)
            ]
            if required != ["query"]:
                return None  # multi-arg schema → AC2.4's generation path
            goal = str(frame.get("goal", "")).strip()
            if not goal:
                return None  # empty/invalid goal → fallback
            return ArgsResult(args={"query": goal}, retried=False,
                              fast_path="goal_to_query")
        except Exception:
            return None

    def _vision_target_fast_path(
        self, frame: Dict[str, Any]
    ) -> Optional[ArgsResult]:
        """REQ-10 (T13): deterministic vision target extraction.

        AC10.1 — a click/tap/press goal with a quoted target (or "the X
        button") fills the element target with 0 LLM tokens.
        AC10.2 — no pattern → None, so the caller's LLM resolution runs
        unchanged.
        Edge — a target that is empty or longer than 120 chars is NOT a fast
        path: we never dispatch an empty or absurd target.
        """
        goal = str(frame.get("goal", "")).strip()
        if not goal or not self._CLICK_VERB.search(goal):
            return None  # not a click-shaped goal → LLM resolution unchanged

        target, pattern = "", ""
        _m = self._QUOTED_TARGET.search(goal)
        if _m:
            target = next((g for g in _m.groups() if g), "")
            pattern = "quoted_target"
        else:
            _m = self._THE_X_BUTTON.search(goal)
            if _m:
                target, pattern = _m.group(1), "the_x_button"

        target = (target or "").strip()
        if not target or len(target) > self._MAX_TARGET_LEN:
            return None  # edge: empty / over-long → fallback, never empty dispatch
        return ArgsResult(
            args={self._VISION_TARGET_PARAM: target},
            retried=False,
            fast_path=pattern,
        )

    @staticmethod
    def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
        if not text or not text.strip():
            return None
        try:
            v = json.loads(text)
            return v if isinstance(v, dict) else None
        except Exception:
            pass
        # balanced-brace salvage (mirrors tool_decision._extract_json style)
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(text[start : i + 1])
                        return v if isinstance(v, dict) else None
                    except Exception:
                        return None
        return None

    def generate_args(
        self,
        consumer_id: str,
        option: str,
        schema: Dict[str, Any],
        frame: Dict[str, Any],
    ) -> ArgsResult:
        """Generate args JSON for the chosen option, validated against its schema.

        Retry rule (REQ-4): empty/whitespace output is retried exactly once;
        invalid JSON or schema-violating args are NOT retried (escalates).

        REQ-21/D12: the ONNX backend scores labels, it does not generate
        arguments — production injects no generative factory, so this
        degrades to ``ArgsResult(args=None, retried=False)`` and the box
        escalates to the legacy ladder (the Brain does schema-constrained
        generation there via function-calling, AC2.4). The generative path
        stays behind the ``llama_factory`` test seam so the args stage stays
        testable.
        """
        if not self._lock.acquire(timeout=self._cfg.acquire_timeout_s):
            self.counters.lock_timeouts += 1
            return ArgsResult(args=None, retried=False)
        t_start = self._clock()  # REQ-26: lock-wait separated from compute
        lock_wait_ms = int((self._clock() - t_start) * 1000)
        result = ArgsResult(args=None, retried=False)
        try:
            if self._llm is None:
                if self._llama_factory is None:
                    # No generative backend (production): degrade — the box
                    # escalates to the legacy ladder (AC2.4).
                    return result
                try:
                    self._llm = self._llama_factory()
                except Exception as e:
                    self.counters.load_failures += 1
                    logger.warning(
                        "decision_engine args model load failed: %r", e
                    )
                    return result
            allowed = set(schema.get("properties", {}).keys())
            required = set(schema.get("required", []))
            prompt = (
                f"You fill arguments for the function {option}.\n"
                f"State: {json.dumps(frame, default=str)[:400]}\n"
                f"Parameters (JSON schema): {json.dumps(schema)[:600]}\n"
                "Output ONLY one JSON object with the arguments. No prose.\n"
            )
            last_text = ""
            for attempt in (0, 1):
                out = self._llm.create_completion(
                    prompt,
                    max_tokens=self._cfg.max_args_tokens,
                    temperature=0.0,
                    stop=["\n\n"],
                )
                text = (out.get("choices", [{}])[0].get("text") or "").strip()
                if not text:
                    if attempt == 0:
                        self.counters.retries += 1
                        continue  # bounded empty retry (AC4.1)
                    result = ArgsResult(args=None, retried=True)
                    return result
                last_text = text
                break
            else:
                result = ArgsResult(args=None, retried=True)
                return result
            parsed = self._extract_json_obj(last_text)
            if parsed is None:
                return result
            if not required.issubset(parsed.keys()):
                return result
            if allowed and not set(parsed.keys()).issubset(allowed | set()):
                parsed = {k: v for k, v in parsed.items() if k in allowed}
            result = ArgsResult(args=parsed, retried=False)
            return result
        finally:
            # REQ-26 AC26.2: the args latency breakdown, emitted on every path.
            args_ms = int((self._clock() - t_start) * 1000)
            logger.info(
                "decision_engine generate_args consumer=%s option=%s "
                "args_latency_ms=%d lock_wait_ms=%d args_valid=%s retried=%s",
                consumer_id, option, args_ms, lock_wait_ms,
                result.args is not None, result.retried,
            )
            self._lock.release()


# ---------------------------------------------------------------------------
# Module-level singleton + shutdown hook anchor
# ---------------------------------------------------------------------------

_ENGINE: Optional[DecisionEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_decision_engine(
    config: Optional[EngineConfig] = None,
    backend_factory: Optional[Callable[..., Any]] = None,
    llama_factory: Optional[Callable[..., Any]] = None,
) -> DecisionEngine:
    """Process-wide engine. Tests pass their own instance; production uses this.

    With no config passed (production), the ``oracle`` block is
    parsed into EngineConfig (REQ-25 AC25.1) — the block is LIVE, not
    decorative.
    """
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            if config is None:
                config = load_engine_config()
            _ENGINE = DecisionEngine(
                config=config, backend_factory=backend_factory,
                llama_factory=llama_factory,
            )
        return _ENGINE


def shutdown_decision_engine() -> None:
    """Lifespan teardown hook (backend/main.py shutdown block)."""
    global _ENGINE
    with _ENGINE_LOCK:
        eng, _ENGINE = _ENGINE, None
    if eng is not None:
        try:
            eng.shutdown()
        except Exception:
            pass


def gate(
    consumer_id: str, options: Sequence[str], frame: Dict[str, Any]
) -> Tuple[Optional[DecisionScore], bool]:
    """The gate primitive for visible-surface consumers (REQ-11/12/13).

    Returns (score, enforced). score is None on any engine failure —
    callers then take their legacy heuristic path. enforced=False means
    shadow mode: record the decision but let the heuristics decide.
    Never raises.
    """
    try:
        eng = get_decision_engine()
        ds = eng.decide(consumer_id, options, frame)
        if ds is None:
            return None, False
        return ds, consumer_id in enforced_consumers()
    except Exception as _e:
        logger.debug("decision_engine gate failed: %r", _e)
        return None, False
