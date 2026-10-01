"""Torch-free ONNX decision backend — the model behind ORACLE (REQ-21).

Oracle is the engine's display name; this module is its scoring backend. See
``decision_engine.py`` for the name-vs-key rule (the backend identity below
keys the calibrated threshold and must not be renamed as a label change).

Wraps the GLiNER2.5-Decide ONNX export behind the engine's UNCHANGED
``DecisionScore`` envelope (AC21.2): one schema ``Task`` per ``decide()`` call
whose labels are the caller's option set, ``onnxruntime``
``CPUExecutionProvider`` only (AC21.3 — zero VRAM), ``None`` on any failure
(AC21.4 — no fallback model; callers degrade to the legacy path).

Reference implementation ported from the vendored ``gliner_onnx.py`` runner
shipped with nishparadox/gliner2.5-decide-onnx (encode/logits/probabilities).

TASK SHAPE IS PINNED TO THE MEASURED BENCH SHAPE (calibration validity,
AC22.1/D13): ``Task(name="tool", labels={opt: None},
instruction="Which tool should handle this request?", exclusive=True)`` — the
exact shape ``scripts/bench_decision_models.py`` measured 71.7% @119 ms with,
and the shape the 0.40 threshold curve was derived at. Frame fields
(``option_descriptions`` and friends) are deliberately NOT rendered into the
prompt: an unmeasured prompt change would invalidate the threshold (the same
principle as AC25.5 — a threshold is only meaningful for the distribution it
was measured on).

Everything here is single-writer-of-nothing: read set is the args passed in;
write set is the return value and log lines. The engine is read-only w.r.t.
the memory/graph store (REQ-28 AC28.4).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from backend.agent.decision_engine import CandidateScore, DecisionScore

logger = logging.getLogger("decision_backend_onnx")

# ---------------------------------------------------------------------------
# Task shape (ported from the reference runner; pinned by CT-DEI-11)
# ---------------------------------------------------------------------------

_TASK_INSTRUCTION = "Which tool should handle this request?"


# ── REQ-19 (T25): per-consumer criteria, expressed as schema Tasks ──────────
#
# The LFM backend shared ONE tool-selection head across every consumer (a
# constant prompt with no criteria for `presentation` / `narration`), which is
# the likeliest cause of a parity failure the moment a new consumer appears.
# The GLiNER backend expresses the same intent natively: each consumer is its
# own `Task(name, labels, instruction, exclusive)`, and the runner builds the
# structure tokens per call. No prompt heads, no KV cache — the revision in
# REQ-19 replaced both with this.
#
# AC19.4 is the load-bearing constraint: `tool_choice`'s Task must remain
# BYTE-IDENTICAL to the measured bench shape, or the 0.40 threshold curve stops
# applying (a threshold is only meaningful for the distribution it was measured
# on). Its spec therefore pins task_name="tool" and the bench instruction.


@dataclass(frozen=True)
class ConsumerSpec:
    """One consumer's own scoring criteria (REQ-19 AC19.1).

    ``labels`` empty means the caller supplies the option set (menu-shaped
    consumers such as ``tool_choice``); a non-empty tuple is a FIXED label set
    (the bool consumers). ``criteria=False`` registers a consumer WITHOUT
    criteria — the engine refuses to score it rather than borrowing another
    consumer's head (REQ-19 edge case).
    """

    consumer_id: str
    task_name: str
    instruction: str
    exclusive: bool = True
    labels: Tuple[str, ...] = ()
    criteria: bool = True


CONSUMER_TASKS: Dict[str, ConsumerSpec] = {
    # Pinned to the measured bench shape (AC22.1 / AC19.4) — do not edit.
    "tool_choice": ConsumerSpec(
        consumer_id="tool_choice",
        task_name="tool",
        instruction=_TASK_INSTRUCTION,
        exclusive=True,
    ),
}


# The question used for a consumer that registers ITSELF (2026-09-27). A new
# decision point that never declared its question can still be MEASURED this
# way; the bar then decides whether it deserves a better question. Deliberately
# generic: an honest vague question beats no measurement, and an uncalibrated
# consumer can never enforce.
AUTO_INSTRUCTION = (
    "Choose the single best option for the goal below. The options are the "
    "candidate answers to one question about the current step."
)


def ensure_consumer_spec(
    consumer_id: str,
    options: Sequence[str],
    instruction: Optional[str] = None,
) -> Optional[ConsumerSpec]:
    """Return *consumer_id*'s criteria, REGISTERING them on first sight.

    WHY (2026-09-27): a new decision point could not be measured at all until
    someone hand-wrote a ``ConsumerSpec``, and ``DecisionEngine.decide`` refused
    any id outside the frozen CONSUMERS tuple - so the application could not
    evolve with use, and every new consumer needed manual creation. Measured
    consequence: `recovery_strategy` scored nothing for its whole life, and
    `narration` produced no row until a registration block was written by hand.

    The caller already passes the option set on EVERY call, so the labels need no
    declaration. ``instruction`` is taken from the caller when given (the best
    question), else a generic one is used so the consumer is still measured.

    SAFETY: REGISTERING IS NOT ENFORCING. An uncalibrated consumer has no
    threshold for the active backend, so it cannot steer anything. The report
    shows it fail-closed ("no threshold for the active backend") until a
    threshold is calibrated for it, and the bar still requires 100 rows,
    precision >= 0.90 and ECE <= 0.05 before a flip.
    """
    spec = CONSUMER_TASKS.get(consumer_id)
    if spec is not None:
        return spec
    labels = tuple(o for o in options if isinstance(o, str) and o)
    if not labels:
        return None
    logger.info(
        "decision_backend_onnx: auto-registered consumer=%s labels=%d "
        "(no declared criteria; measuring in shadow)",
        consumer_id,
        len(labels),
    )
    return register_consumer_spec(ConsumerSpec(
        consumer_id=consumer_id,
        task_name=consumer_id,
        instruction=instruction or AUTO_INSTRUCTION,
        # Menu-shaped: the caller's own options supply the labels.
        labels=(),
    ))


def register_consumer_spec(spec: ConsumerSpec) -> ConsumerSpec:
    """Register (or replace) a consumer's criteria (REQ-19 AC19.3)."""
    CONSUMER_TASKS[spec.consumer_id] = spec
    return spec


def get_consumer_spec(consumer_id: str) -> Optional[ConsumerSpec]:
    """The registered criteria for *consumer_id*, or None."""
    return CONSUMER_TASKS.get(consumer_id)


def build_task(
    consumer_id: str, options: Sequence[str]
) -> Optional["Task"]:
    """The schema ``Task`` for *consumer_id* (REQ-19 AC19.1/AC19.3).

    Returns None when the consumer has no registered criteria — the caller
    DEGRADES to the legacy path rather than scoring under another consumer's
    head (REQ-19 edge case). ``options`` supplies the labels for a menu-shaped
    consumer; a fixed-label spec ignores them.
    """
    spec = CONSUMER_TASKS.get(consumer_id)
    if spec is None or not spec.criteria:
        return None
    labels = list(spec.labels) if spec.labels else [
        o for o in options if isinstance(o, str) and o
    ]
    if not labels:
        return None  # never a fabricated uniform distribution
    return Task(
        name=spec.task_name,
        labels={t: None for t in labels},
        instruction=spec.instruction,
        exclusive=spec.exclusive,
    )

_WORDS = re.compile(
    r"""(?:https?://[^\s]+|www\.[^\s]+)
    |[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}
    |@[a-z0-9_]+
    |\w+(?:[-_]\w+)*
    |\S""",
    re.VERBOSE | re.IGNORECASE,
)


@dataclass
class Task:
    name: str
    labels: dict[str, str | None]  # label -> description
    instruction: str | None = None
    exclusive: bool = True  # softmax over labels; False = independent sigmoids
    examples: list[tuple[str, str]] = field(default_factory=list)

    def tokens(self) -> list[str]:
        prompt = f"{self.name}: {self.instruction}" if self.instruction else self.name
        for label, desc in self.labels.items():
            if desc:
                prompt += f" [DESCRIPTION] {label}: {desc}"
        for text, out in self.examples:
            if out in self.labels:
                prompt += f" [EXAMPLE] {text} [OUTPUT] {out}"
        toks = ["(", "[P]", prompt, "("]
        for label in self.labels:
            toks += ["[L]", label]
        return toks + [")", ")"]


# ---------------------------------------------------------------------------
# Model directory resolution (REQ-21 AC21.5)
# ---------------------------------------------------------------------------

_ENV_MODEL_DIR = "IRIS_DECISION_MODEL_DIR"
_DEFAULT_VARIANT = "model_int8.onnx"
# Shippable install location: repo-relative, content gitignored (651 MB).
_REPO_DIR = Path(__file__).resolve().parent.parent / "models" / "gliner2.5-decide-onnx"
# Dev-machine fallback: the pre-download location used by the 2026-09-25 bench.
_DEV_DIR = Path(r"C:\temp\gliner-onnx")
# Model-file sha256 cache (see GlinerOnnx._hash_model_file). Machine-local.
_HASH_CACHE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "oracle_model_hash.json"
)

_VARIANT_IDS = {
    "model_int8.onnx": "int8",
    "model_fp16.onnx": "fp16",
    "model.onnx": "fp32",
}


def _is_complete_dir(d: Any) -> bool:
    """A usable ONNX dir holds tokenizer.json plus at least one model*.onnx."""
    p = Path(d)
    if not p.is_dir():
        return False
    if not (p / "tokenizer.json").is_file():
        return False
    return any(p.glob("model*.onnx"))


def resolve_model_dir(explicit: Optional[str] = None) -> Optional[str]:
    """Find the ONNX model directory. Returns None when nothing usable exists.

    An explicit/explicit-env path is authoritative: configured-and-missing
    means "unavailable", never "silently substitute another model" (AC21.4).
    """
    env = os.environ.get(_ENV_MODEL_DIR)
    for c in (explicit, env):
        if c:
            return str(c) if _is_complete_dir(c) else None
    for d in (_REPO_DIR, _DEV_DIR):
        if _is_complete_dir(d):
            return str(d)
    return None


# ---------------------------------------------------------------------------
# The vendored runner (ported verbatim from the reference gliner_onnx.py)
# ---------------------------------------------------------------------------


# ── AC30.1 (T38): explicit, host-sized ORT session options ─────────────────
#
# These are SET rather than left to onnxruntime's defaults, so the effective
# values are a recorded decision that a future ORT release cannot silently
# change under us. `intra_op` is where the parallelism win is; a second axis of
# `inter_op` threads on a single-request-at-a-time workload only oversubscribes.
_INTER_OP_THREADS = 1

# Several runs may be in flight on the one session (IRIS_ORACLE_PHASE; see
# decision_engine._decide_phase), so the per-call telemetry must not be shared
# mutable state. The run counters bump under a MODULE-level lock (a stand-in
# runner built without __init__ still works), and the per-call stage timers live
# in thread-local state: encode() and logits() of one call run on one thread.
_STATS_LOCK = threading.Lock()
_TL = threading.local()

# Input length cap (label structure + text). The encoder is DeBERTa-v3 with 512
# positions and GLiNER trains on ~384 words; nothing capped the text, so the
# `done` monitor - which passes the whole planner prompt, every step output
# included - ran ~5k-token inputs through one quadratic-attention pass: 28.6 s
# for one call, 65.7 s over four in one eval turn (2026-09-29), while every
# other consumer queued behind it on the single inference thread and six gave
# up at the 9 s budget. The head of the text (the objective) is kept.
_MAX_INPUT_IDS = 512
_GRAPH_OPT_LEVEL_NAME = "ORT_ENABLE_ALL"
_EXECUTION_MODE_NAME = "ORT_SEQUENTIAL"


class _OnnxRunner:
    """onnxruntime + tokenizers + numpy. One session, one run per call."""

    def __init__(self, model_path: str, tokenizer_path: str,
                 threads: Optional[int] = None):
        import onnxruntime as ort  # heavy import kept lazy

        opts = ort.SessionOptions()
        # AC30.1 (T38): sized to the HOST. An explicit request is honoured but
        # clamped to the machine's actual core count (REQ-30 edge case: fewer
        # cores than configured → clamp, logged).
        #
        # MEASURED OPTIMUM (session 357, 8 logical cores, 6-label menu):
        #   intra=1 → p50 279ms   intra=2 → p50 240ms
        #   intra=4 → p50 181ms   intra=8 → p50 277ms / p95 419ms
        # `os.cpu_count()` reports LOGICAL processors while ORT's intra-op pool
        # wants PHYSICAL cores, so `cpu // 2` is the estimate — and the naive
        # "use every core" oversubscribes, costing ~50% on this model. This is
        # the AC30.8 case in the wild: the first cut used all 8 threads, the
        # bench caught the regression, and the choice was reverted to the
        # measured optimum rather than kept.
        cpu = os.cpu_count() or 1
        _default_intra = max(1, cpu // 2)
        requested = int(threads) if threads else _default_intra
        intra = max(1, min(requested, cpu))
        opts.intra_op_num_threads = intra
        opts.inter_op_num_threads = _INTER_OP_THREADS
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            model_path, opts, providers=["CPUExecutionProvider"]
        )
        # The EFFECTIVE values, recorded so AC30.1 is verifiable rather than
        # assumed (the option objects do not read back reliably).
        self.session_options: Dict[str, Any] = {
            "intra_op_num_threads": intra,
            "inter_op_num_threads": _INTER_OP_THREADS,
            "graph_optimization_level": _GRAPH_OPT_LEVEL_NAME,
            "execution_mode": _EXECUTION_MODE_NAME,
            "providers": ["CPUExecutionProvider"],
            "host_cpu_count": cpu,
            "clamped": requested != intra,
        }
        if requested != intra:
            logger.info(
                "decision_backend_onnx: intra_op_num_threads %d clamped to %d "
                "(host cores=%d)", requested, intra, cpu,
            )
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(tokenizer_path)
        self._cache: dict[str, list[int]] = {}
        # AC30.2 (T39): the label-set STRUCTURE (token ids + relative label
        # positions), keyed on the token tuple. Re-tokenizing the same menu on
        # every call was pure repeated work.
        self._structure_cache: dict[tuple, tuple[list[int], list[int]]] = {}
        # AC30.3 (T40): measured, not assumed — the batch claim is only worth
        # anything if the encode/run counts are actually recorded.
        self.encode_calls = 0
        self.run_calls = 0
        # AC30.6 (T38): per-stage attribution for the LAST call, so a tuning
        # change can be blamed on a stage instead of on "the engine". Cheap:
        # perf_counter is ~50ns against a ~117ms inference. The in-progress
        # timers are thread-local (_TL); `stage_ms` is the last COMPLETED call.
        self.stage_ms: Dict[str, float] = {
            "tokenize_ms": 0.0, "encode_ms": 0.0,
            "session_ms": 0.0, "post_ms": 0.0,
        }

    def _ids(self, piece: str) -> list[int]:
        _t = time.perf_counter()
        ids = self._cache.get(piece)
        if ids is None:
            ids = self._cache[piece] = self.tok.encode(
                piece, add_special_tokens=False
            ).ids
        _TL.tok_s = getattr(_TL, "tok_s", 0.0) + (time.perf_counter() - _t)
        return ids

    def _structure(self, task: Task) -> tuple[list[int], list[int]]:
        """AC30.2 (T39): this label set's token ids and RELATIVE label positions.

        Relative offsets are made absolute by :meth:`encode` at the current
        base, so one cached structure is reusable at any position in a batch.
        A changed label set misses the key and recomputes — correctness is
        unaffected (REQ-30 edge case).
        """
        key = tuple(task.tokens())
        hit = self._structure_cache.get(key)
        if hit is None:
            ids: list[int] = []
            positions: list[int] = []
            toks = list(key)
            for i, piece in enumerate(toks):
                if piece == "[L]" and i >= 4 and i % 2 == 0 and i < len(toks) - 2:
                    positions.append(len(ids))
                ids += self._ids(piece)
            hit = self._structure_cache[key] = (ids, positions)
        return hit

    def encode(self, text: str, tasks: list[Task],
               max_text_ids: Optional[int] = None) -> tuple[list[int], list[int]]:
        with _STATS_LOCK:
            self.encode_calls += 1
        _t0 = time.perf_counter()
        _tok_before = getattr(_TL, "tok_s", 0.0)
        if not text.endswith((".", "!", "?")):
            text = (text + ".") if text else "."
        ids: list[int] = []
        positions: list[int] = []
        for t_idx, task in enumerate(tasks):
            if t_idx:
                ids += self._ids("[SEP_STRUCT]")
            base = len(ids)
            rel_ids, rel_positions = self._structure(task)
            ids += rel_ids
            positions += [base + p for p in rel_positions]
        ids += self._ids("[SEP_TEXT]")
        # The job's text budget (Oracle jobs, decision_engine.ORACLE_JOBS):
        # latency follows length, so the text is cut at the budget; the label
        # structure is never cut. _MAX_INPUT_IDS stays the absolute ceiling.
        _text_cap = len(ids) + (int(max_text_ids) if max_text_ids else _MAX_INPUT_IDS)
        _cap = min(_MAX_INPUT_IDS, _text_cap)
        for m in _WORDS.finditer(text):
            piece = self._ids(m.group().lower())
            if len(ids) + len(piece) > _cap:
                break
            ids += piece
        # AC30.6: tokenizer work separated from structure assembly.
        _TL.encode_ms = (time.perf_counter() - _t0) * 1000.0
        _TL.tokenize_ms = (getattr(_TL, "tok_s", 0.0) - _tok_before) * 1000.0
        return ids, positions

    def logits(self, text: str, tasks: list[Task],
               max_text_ids: Optional[int] = None) -> dict[str, dict[str, float]]:
        ids, positions = self.encode(text, tasks, max_text_ids)
        with _STATS_LOCK:
            self.run_calls += 1
        _t_run = time.perf_counter()
        (out,) = self.session.run(["logits"], {
            "input_ids": np.asarray([ids], dtype=np.int64),
            "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
            "label_positions": np.asarray([positions], dtype=np.int64),
        })
        _t_post = time.perf_counter()
        flat = iter(out[0].tolist())
        result = {t.name: {label: next(flat) for label in t.labels} for t in tasks}
        _t_end = time.perf_counter()
        # AC30.6 (T38): the breakdown the bench reports.
        self.stage_ms = {
            "tokenize_ms": round(_TL.tokenize_ms, 3),
            "encode_ms": round(_TL.encode_ms - _TL.tokenize_ms, 3),
            "session_ms": round((_t_post - _t_run) * 1000.0, 3),
            "post_ms": round((_t_end - _t_post) * 1000.0, 3),
        }
        return result


# ---------------------------------------------------------------------------
# The engine-compatible wrapper
# ---------------------------------------------------------------------------


class GlinerOnnx:
    """Engine-compatible ONNX decision backend.

    Returns the UNCHANGED ``DecisionScore`` envelope (AC21.2). One schema
    ``Task`` per ``decide()`` call whose labels are the caller's option set.
    ``CPUExecutionProvider`` only (AC21.3). ``None`` on any failure — never
    raises (AC21.4); callers degrade to the legacy path.
    """

    def __init__(
        self,
        model_dir: Optional[str] = None,
        variant: str = _DEFAULT_VARIANT,
        threads: Optional[int] = None,
        clock: Any = time.perf_counter,
    ) -> None:
        self._model_dir = model_dir
        self._variant = variant
        self._threads = threads
        self._clock = clock
        self._runner: Optional[_OnnxRunner] = None
        self._load_attempted = False
        self._notice_logged = False
        self._model_hash: Optional[str] = None
        self.model_id: str = self.backend_id

    # -- identity (AC21.7 / AC22.5: variant-derived backend identity) -------

    @property
    def backend_id(self) -> str:
        """Backend identity keyed to the deployed variant (AC22.5)."""
        v = _VARIANT_IDS.get(self._variant, self._variant)
        return f"gliner25-decide-onnx-{v}" if v else "gliner25-decide-onnx"

    # -- lifecycle -----------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._runner is not None

    def availability(self) -> Tuple[bool, str]:
        """(usable, reason). Never raises."""
        if self._runner is not None:
            return True, "loaded"
        if self._load_attempted:
            return False, "load_failed_or_missing"
        if resolve_model_dir(self._model_dir) is None:
            return False, "model_dir_not_found"
        return True, "loadable_pending"

    def _log_unavailable(self, why: str) -> None:
        # DEBUG, not WARNING: the ENGINE owns the notice-once contract
        # (test_unavailable_notice_logged_once asserts exactly one warning);
        # this line is diagnostics only for standalone backend use.
        if not self._notice_logged:
            self._notice_logged = True
            logger.debug(
                "decision_backend_onnx unavailable (%s) — using legacy path", why
            )

    def load(self) -> bool:
        """Create the ONNX session. Lazy, once. Never raises."""
        if self._runner is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        model_dir = resolve_model_dir(self._model_dir)
        if model_dir is None:
            self._log_unavailable("onnx model dir not found or incomplete")
            return False
        try:
            self._runner = _OnnxRunner(
                os.path.join(model_dir, self._variant),
                os.path.join(model_dir, "tokenizer.json"),
                threads=self._threads,
            )
            self._model_hash = self._hash_model_file(
                os.path.join(model_dir, self._variant)
            )
            logger.info(
                "decision_backend_onnx loaded backend=%s dir=%s hash=%s",
                self.backend_id, model_dir, (self._model_hash or "")[:12],
            )
            return True
        except Exception as e:  # load failure must never escape (AC21.4)
            self._runner = None
            self._log_unavailable(f"onnx load failed: {e!r}")
            return False

    @staticmethod
    def _hash_model_file(path: str) -> Optional[str]:
        """sha256 of the deployed model file (AC6.5/AC22.5 attribution) —
        a model swap is detectable instead of silently invalidating
        thresholds.

        Cached in ``_HASH_CACHE_PATH`` keyed by (abs path, st_size,
        st_mtime_ns): a hit returns the stored digest with no file read. The
        full read was a second pass over the 642 MB file right after the ORT
        session read it — ~16 s at startup on this machine's C: hard disk,
        competing with the TTS worker load (2026-09-30). Any cache failure
        (missing, corrupt, unwritable) falls back to hashing; it never fails
        the load and never changes the digest.
        """
        try:
            import hashlib
            import json

            st = os.stat(path)
            key = {
                "path": os.path.abspath(path),
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
            }
            try:
                cached = json.loads(_HASH_CACHE_PATH.read_text(encoding="utf-8"))
                if (
                    isinstance(cached, dict)
                    and all(cached.get(k) == v for k, v in key.items())
                    and re.fullmatch(r"[0-9a-f]{64}", str(cached.get("sha256")))
                ):
                    return cached["sha256"]
            except Exception:  # noqa: BLE001 — a cache miss, never a failure
                pass

            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            digest = h.hexdigest()

            try:
                tmp = _HASH_CACHE_PATH.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps({**key, "sha256": digest}), encoding="utf-8")
                os.replace(tmp, _HASH_CACHE_PATH)
            except Exception as e:  # noqa: BLE001 — next load re-hashes
                logger.debug("decision_backend_onnx hash cache not written: %r", e)
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
            return digest
        except Exception:
            return None

    @property
    def model_hash(self) -> Optional[str]:
        """The deployed model file's sha256 (None before load)."""
        return self._model_hash

    @property
    def session_options(self) -> Optional[Dict[str, Any]]:
        """AC30.1 (T38): the EFFECTIVE ORT session options, or None pre-load.

        Exposed so the tuning is verifiable rather than assumed — the ORT
        option objects do not read back reliably.
        """
        return getattr(self._runner, "session_options", None)

    @property
    def stage_ms(self) -> Dict[str, float]:
        """AC30.6 (T38): the LAST call's per-stage latency breakdown."""
        return dict(getattr(self._runner, "stage_ms", None) or {})

    def shutdown(self) -> None:
        """Free the session. Idempotent."""
        self._runner = None

    # -- scoring (one schema Task per call) ----------------------------------

    def decide(
        self,
        consumer_id: str,
        options: Sequence[str],
        frame: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Optional[DecisionScore]:
        """Score the option set via one exclusive schema Task; softmax over
        labels — the menu-wide softmax the 0.40 curve was derived at (D13).

        Task shape pinned to the measured bench shape (AC22.1 calibration
        validity): labels carry no descriptions, the instruction is the bench
        instruction. Returns None on any failure — never raises.
        """
        try:
            if not self.load():
                return None
            # REQ-19 (T25): the Task comes from the consumer's OWN registered
            # criteria. No criteria → refuse (None) and let the caller degrade
            # rather than scoring under another consumer's head.
            # Auto-register on first sight (2026-09-27): a NEW decision point
            # measures itself from its first run. See ensure_consumer_spec.
            ensure_consumer_spec(consumer_id, options, instruction)
            task = build_task(consumer_id, options)
            if task is None:
                logger.info(
                    "decision_backend_onnx: no criteria for consumer=%s — "
                    "refusing to score (legacy path)", consumer_id,
                )
                return None
            t0 = self._clock()
            _text = str(frame.get("goal", ""))
            _budget = frame.get("_max_text_ids")  # set by the engine's job input
            lg = (
                self._runner.logits(_text, [task], _budget) if _budget
                else self._runner.logits(_text, [task])
            )[task.name]
            # Softmax over labels (exclusive Task) — NO sharpening; natively
            # calibrated (D13). Duplicate labels would collapse in the dict —
            # guarded at menu composition (AC21.8).
            x = np.array(list(lg.values()), dtype=np.float64)
            p = np.exp(x - x.max()) / np.exp(x - x.max()).sum()
            dist = tuple(
                CandidateScore(name=n, logprob=float(l), prob=float(pp))
                for n, l, pp in zip(lg.keys(), lg.values(), p)
            )
            best = max(dist, key=lambda c: c.prob)
            lat_ms = int((self._clock() - t0) * 1000)
            logger.info(
                "decision_backend_onnx decide consumer=%s chosen=%s conf=%.3f "
                "candidates=%d latency_ms=%d",
                consumer_id, best.name, best.prob, len(dist), lat_ms,
            )
            return DecisionScore(
                consumer_id=consumer_id,
                chosen=best.name,
                confidence=best.prob,
                distribution=dist,
                engine_latency_ms=lat_ms,
            )
        except Exception as e:  # scoring failure must never escape
            logger.warning("decision_backend_onnx scoring failed: %r", e)
            return None

    # ── decide_many REMOVED 2026-09-26 (REQ-20 retired by owner decision) ───
    # The batched entry point used to live here. It is deleted rather than left
    # in place, because the temptation is the danger: a caller wiring it up for
    # speed would judge consumers on a distribution the threshold was never
    # measured on. Measured with this model: three distinct questions in one
    # session run changed a verdict (batch "no" vs solo "yes"), and JEV's
    # fan-out guarantee ("one answer is never hidden context for another") is
    # not reachable with an export where one run carries one question's
    # context. See `decision_engine.py` (same note) and the pin
    # `Decision: no batched scoring — enforcement stays on solo runs`.
    # `decide()` (one consumer, one run) is the only scoring path.
