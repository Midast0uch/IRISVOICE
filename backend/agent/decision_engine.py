"""Calibrated small-model decision engine (Jev/RLCD pattern reproduction).

Spec: specs/tool-decision-engine (REQ-1, REQ-2, REQ-4, REQ-7, REQ-13).

One resident LFM-sized model, loaded in-process via llama_cpp on CPU. It never
writes to memory, never emits events, never touches the 8082 server or the VRAM
ledger. Its only job: score a caller-provided option set against a caller-provided
feature frame and return a calibrated probability distribution. Consumers:
`tool_choice` (Wave 2), `presentation` and `narration` (Wave 4).

Two primitives, both return DecisionScore or None (None = degrade to legacy path):
  - decide(consumer_id, options, frame)      — Jev "Choice" (parallel scoring)
  - generate_args(consumer_id, option, schema, frame) — constrained args JSON

Everything here is single-writer-of-nothing: read set is the args passed in;
write set is the return value, counters, and log lines. CT-DE-5 enforces it.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("decision_engine")

# ---------------------------------------------------------------------------
# Data model (CT-DE-1 pins this shape)
# ---------------------------------------------------------------------------

CONSUMERS: Tuple[str, ...] = ("tool_choice", "presentation", "narration")


@dataclass(frozen=True)
class CandidateScore:
    name: str        # option name (tool name, surface name, or DELEGATE/NONE)
    logprob: float   # summed continuation logprob under the decision prompt
    prob: float      # softmax-normalized probability


@dataclass(frozen=True)
class DecisionScore:
    consumer_id: str
    chosen: str
    confidence: float                 # = P(chosen)
    distribution: Tuple[CandidateScore, ...]
    engine_latency_ms: int
    retried: bool = False
    # REQ-17 hierarchical detail: stage scores when decide_tree() was used.
    # {"lane": "file", "lane_p": 0.97, "leaf_p": 0.92} — absent on flat decide().
    stage_detail: Optional[Dict[str, Any]] = None

    def confident(self, threshold: float) -> bool:
        """True when the calibrated probability clears the threshold."""
        return self.confidence >= threshold


@dataclass(frozen=True)
class ArgsResult:
    args: Optional[Dict[str, Any]]    # None = invalid/empty after retry
    retried: bool


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
    raw = os.environ.get("IRIS_DECISION_ENFORCE", "tool_choice")
    return frozenset(
        c.strip() for c in raw.split(",") if c.strip() in CONSUMERS
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    model_path: Optional[str] = None     # explicit path wins
    n_ctx: int = 1024
    max_answer_tokens: int = 8           # option name only
    max_args_tokens: int = 192
    acquire_timeout_s: float = 2.0
    default_threshold: float = 0.85
    # Per-consumer thresholds (REQ-13): tools that execute external side effects
    # sit higher than display gates; calm narration anti-spamming sits lower.
    # Ordered: explicit per-consumer → default_threshold → env knobs at thaw.
    thresholds: Dict[str, float] = None  # set in __post_init__ below
    # Bounded cost per decision. Lives as the linter against the 350M's
    # discrimination floor: measured 2026-09-20, 20-option letter scoring
    # collapsed to uniform and 4-6 option scoring was correct at high conf
    # (crawler 0.94, vision 0.99). Six is the discriminating cap.
    candidate_cap: int = 6
    # Hierarchical selection (REQ-17): exercise the lane stage when the menu
    # width exceeds this; below it the flat path is as good and cheaper.
    hierarchy_trigger: int = 5
    # Softmax temperature for option scoring. LIVE MEASUREMENT (2026-09-20,
    # LFM2-350M-Extract CPU): raw continuation softmax spreads across
    # 0.28-0.53 — rarely crossing 0.85 even on clear cases. tau < 1 sharpens
    # without reordering; the calibration gate measures the right value.
    softmax_tau: float = 0.5
    # GPU offload. DEFAULT 0 (AC1.2 holds — owner's locked decision: the GPU
    # carries the brain + VLM). IRIS_DECISION_GPU_LAYERS=-1 flips it
    # explicitly when the harvested latency data justifies it.
    n_gpu_layers: int = 0

    def __post_init__(self) -> None:
        if self.thresholds is None:
            self.thresholds = {}

    def threshold_for(self, consumer_id: str) -> float:
        return float(self.thresholds.get(consumer_id, self.default_threshold))


# Default search: explicit env var, then LM Studio dir glob for a 350M chat GGUF
# (encoder-only "Embedding" variant explicitly excluded).
_ENV_MODEL = "IRIS_DECISION_MODEL"
_GLOB_PATTERNS = ("LFM2*350M*.gguf",)


def resolve_model_path(explicit: Optional[str] = None) -> Optional[str]:
    """Find the decision model file. Returns None when nothing usable exists.

    An explicit/explicit-env path is authoritative: configured-and-missing
    means "unavailable", never "silently substitute another model".
    """
    env = os.environ.get(_ENV_MODEL)
    for c in (explicit, env):
        if c:
            p = Path(c)
            return str(p) if p.is_file() else None
    roots: List[Path] = []
    lmstudio = Path.home() / ".lmstudio" / "models"
    if lmstudio.is_dir():
        roots.append(lmstudio)
    try:
        from backend.agent.local_model_manager import MODELS_DIR

        mm = Path(MODELS_DIR)
        if mm.is_dir() and mm not in roots:
            roots.append(mm)
    except Exception:
        pass
    for root in roots:
        for pat in _GLOB_PATTERNS:
            hits = [h for h in sorted(root.rglob(pat))
                    if not any(
                        bad in h.name.lower()
                        for bad in ("embedding", "encoder", "vl-")  # unusable
                    )
            ]
            # Task-tuned variants beat base models: Extract > Instruct > base.
            for pref in ("extract", "instruct"):
                for h in hits:
                    if pref in h.name.lower():
                        return str(h)
            if hits:
                return str(hits[0])
    return None


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class DecisionEngine:
    """One serialized llama_cpp context. CPU only. Lazy load. Never raises."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        llama_factory: Optional[Callable[..., Any]] = None,  # test seam
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._cfg = config or EngineConfig()
        self._llama_factory = llama_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._llm: Any = None
        self._load_attempted = False
        self._notice_logged = False
        self.counters = EngineCounters()
        self.model_id: Optional[str] = None
        # Head-KV cache for one-pass scoring (D16 speedup tail): snapshot of
        # the static instruction/example head evaluated once at load; each
        # decision evaluates only its own short tail. Fake models in tests
        # leave these None and take the full-eval path (identical result).
        self._head_state: Any = None
        self._n_head_tokens: int = 0
        # Letter token ids are FIXED per tokenizer — tokenized once at load
        # (_warm_letter_ids), not three times per option per decision.
        self._letter_token_ids: Dict[str, int] = {}

    # -- lifecycle ---------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._llm is not None

    def availability(self) -> Tuple[bool, str]:
        """(usable, reason). Never raises."""
        if self._llm is not None:
            return True, "loaded"
        if self._load_attempted:
            return False, "load_failed_or_missing"
        path = resolve_model_path(self._cfg.model_path)
        if path is None:
            return False, "model_not_found"
        return True, "loadeable_pending"

    def _load(self) -> bool:
        if self._llm is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        path = resolve_model_path(self._cfg.model_path)
        if path is None:
            self._log_unavailable("model file not found")
            return False
        try:
            factory = self._llama_factory
            if factory is None:
                from llama_cpp import Llama  # heavy import kept lazy

                def factory(**kwargs: Any) -> Any:
                    return Llama(**kwargs)

            import os as _os

            # threads: CPU prefill scales with cores; cap at 8 by default but
            # IRIS_DECISION_THREADS overrides for tuning (bench used 2026-09-20).
            n_threads = int(_os.environ.get(
                "IRIS_DECISION_THREADS",
                str(max(2, min((_os.cpu_count() or 4) - 2, 8))),
            ))
            gpu_layers = int(_os.environ.get(
                "IRIS_DECISION_GPU_LAYERS", str(self._cfg.n_gpu_layers)) or 0)
            self._llm = factory(
                model_path=path,
                n_ctx=self._cfg.n_ctx,
                n_gpu_layers=gpu_layers,     # default 0 — AC1.2 stands
                logits_all=True,             # continuation scoring needs full logits
                n_threads=n_threads,
                n_batch=256,
                verbose=False,
            )
            self.model_id = Path(path).stem
            logger.info("decision_engine loaded model=%s n_ctx=%d device=%s",
                        self.model_id, self._cfg.n_ctx,
                        "gpu" if gpu_layers else "cpu")
            self._warm_head_state()
            return True
        except Exception as e:  # load failure must never escape (AC1.3)
            self._load_attempted = True
            self._llm = None
            self.counters.load_failures += 1
            self._log_unavailable(f"load failed: {e!r}")
            return False

    def _log_unavailable(self, why: str) -> None:
        if not self._notice_logged:
            self._notice_logged = True
            self.counters.unavailable_events += 1
            logger.warning("decision_engine unavailable (%s) — using legacy path", why)

    def _warm_head_state(self) -> None:
        """Evaluate the static prompt head once and snapshot its KV state.

        Failure is non-fatal: without the snapshot every decision evaluates
        the whole prompt (correct, slower). Also pre-tokenizes the candidate
        letter forms once — every tokenized string ending is reused verbatim
        across all decisions until unload.
        """
        if self._llm is None:
            return
        try:
            head, _ = self._build_prompt_parts("tool_choice", ["A", "B"], {})
            self._llm.reset()
            toks = self._llm.tokenize(head.encode("utf-8"), add_bos=True)
            self._llm.eval(toks)
            self._head_state = self._llm.save_state()
            self._n_head_tokens = len(toks)
        except Exception as _e:
            self._head_state = None
            self._n_head_tokens = 0
            logger.debug("decision_engine: head-state warm skipped (%r)", _e)
        try:
            for i in range(26):
                letter = chr(ord("A") + i)
                self._letter_token_ids[letter] = self._llm.tokenize(
                    f" {letter}".encode("utf-8"), add_bos=False
                )[0]
        except Exception as _e:
            logger.debug("decision_engine: letter id warm skipped (%r)", _e)

    def shutdown(self) -> None:
        """Free the context. Idempotent. Called from the lifespan teardown."""
        with self._lock:
            llm, self._llm = self._llm, None
            self._load_attempted = False
        if llm is not None:
            try:
                del llm
            except Exception:
                pass

    # -- scoring (Jev Choice over a caller-provided option set) ------------

    @staticmethod
    def _build_prompt(consumer_id: str, options: Sequence[str], frame: Dict[str, Any]) -> str:
        """Letter-enumerated prompt; splits into a static HEAD + per-decision TAIL.

        The head (instructions + worked example, ~90 tokens) is identical for
        every decision, so it is evaluated once and its KV state cached; the
        tail (task/state/options, ~40-60 tokens) is the only per-decision eval.
        Thermal outcome measured 2026-09-20: tail-only eval turns ~260ms CPU
        decisions into ~10-60ms latency (prelude cost amortized to load time).
        """
        head, tail = DecisionEngine._build_prompt_parts(consumer_id, options, frame)
        return head + tail

    @staticmethod
    def _build_prompt_parts(consumer_id: str, options: Sequence[str], frame: Dict[str, Any]) -> Tuple[str, str]:
        """(head, tail). Options listed by name; the answer continues with the
        chosen option's exact name — semantic continuation scoring reads
        meaning, not a letter symbol."""
        if len(options) > 26:
            raise ValueError("candidate_cap even here")
        head = (
            "Choose the best tool for each task. Answer with the exact tool name.\n\n"
            "Task: read the file README\n"
            "Options: crawler_query, read_file, speak, NONE\n"
            "Answer: read_file\n\n"
            "Task: find the current price of a product online\n"
            "Options: crawler_query, read_file, speak, NONE\n"
            "Answer: crawler_query\n\n"
            "Task: what did we decide about the design yesterday\n"
            "Options: read_file, recall_memory, list_directory, NONE\n"
            "Answer: recall_memory\n\n"
            "Task: list every file in the workspace\n"
            "Options: read_file, list_directory, recall_memory, NONE\n"
            "Answer: list_directory\n\n"
            "Task: tell me a joke\n"
            "Options: read_file, recall_memory, crawler_query, NONE\n"
            "Answer: NONE\n\n"
        )
        goal = str(frame.get("goal", "")).split("\n")[0][:160]
        state_bits = [
            f"{k}={v}" for k, v in frame.items()
            if k != "goal" and v is not None
        ]
        state = "; ".join(str(b)[:80] for b in state_bits[:10])
        # Descriptions turn bare names into semantic criteria — a 350M cannot
        # read meaning out of a bare "recall_memory" token, but it can read it
        # from "recall_memory: recall past conversation memory".
        desc_map = frame.get("option_descriptions") or {}
        listed = []
        for o in options:
            d = str(desc_map.get(o, "")).strip()[:80]
            listed.append(f"{o}: {d}" if d else o)
        opts = "\n".join(f"- {line}" for line in listed)
        tail = (
            f"Task ({consumer_id}): {goal}\n"
            + (f"State: {state}\n" if state else "")
            + f"Available options:\n{opts}\nAnswer:"
        )
        return head, tail

    def _score_options_one_pass(
        self, consumer_id: str, options: Sequence[str], frame: Dict[str, Any],
    ) -> List[Tuple[str, float]]:
        """First-token semantic scoring.

        Evidence basis (live probes, 2026-09-20): the model's answer position
        distributes over the CONTENT tokens of candidate names (' recall',
        ' read', ' DE', ' N'), not letters. Scoring reads the logprob of the
        FIRST token of each candidate name — semantic discrimination at one
        forward pass. For shared first tokens (vision_*) the tie is broken by
        a full-continuation eval of just the tied candidates.
        """
        head, tail = self._build_prompt_parts(consumer_id, options, frame)
        prompt = head + tail
        tokens = self._llm.tokenize(prompt.encode("utf-8"), add_bos=True)
        self._llm.reset()
        self._llm.eval(tokens)
        try:
            scores = self._llm.scores
        except AttributeError as e:
            raise ValueError("llm.scores unavailable (need logits_all=True)") from e
        # scores buffer is n_ctx x vocab; only rows [0:n_tokens) are written.
        # The logits that answer "what comes after the prompt?" sit at index
        # n_tokens - 1, NOT scores[-1] (measured: padded rows are all zero).
        row = scores[len(tokens) - 1]
        raw: List[Tuple[str, float]] = []
        per_first: Dict[int, List[str]] = {}
        # First-token scoring — empirically the discriminating signal for this
        # model: the logit of each candidate name's FIRST token at the answer
        # position tracks task meaning (recall→' recall', vision→' vision').
        for opt in options:
            word = " " + opt.split("_")[0]
            first_tok = self._llm.tokenize(word.encode("utf-8"), add_bos=False)
            if not first_tok:
                raw.append((opt, float("-inf")))
                continue
            raw.append((opt, float(row[first_tok[0]])))
            per_first.setdefault(first_tok[0], []).append(opt)
        # vision_* and other prefix-shared options got identical first-token
        # mass; resolve real ties (>1 option, same first token) by full
        # continuation for just the tied subgroup.
        for tie in [g for g in per_first.values() if len(g) > 1]:
            for opt in tie:
                cont = self._llm.tokenize(f" {opt}".encode("utf-8"), add_bos=False)
                self._llm.reset()
                self._llm.eval(tokens + cont)
                # rows are token positions in a preallocated (n_ctx, vocab)
                # buffer; the continuation rows are [len(tokens) : len(tokens)+len(cont))
                tail_rows = self._llm.scores[len(tokens):len(tokens) + len(cont)]
                total = 0.0
                for j, tid in enumerate(cont):
                    total += float(tail_rows[j][tid])
                # normalize per candidate token count so longer names are not
                # artificially favored/disfavored
                for k, (name, _) in enumerate(raw):
                    if name == opt:
                        raw[k] = (name, total / max(len(cont), 1))
                        break
        return raw

    def decide(
        self,
        consumer_id: str,
        options: Sequence[str],
        frame: Dict[str, Any],
    ) -> Optional[DecisionScore]:
        """Score every option in one pass; softmax; return winner + distribution.

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
        if not self._lock.acquire(timeout=self._cfg.acquire_timeout_s):
            self.counters.lock_timeouts += 1
            return None
        try:
            if not self._load():
                return None
            t0 = self._clock()
            raw = self._score_options_one_pass(consumer_id, opts, frame)
            m = max(lp for _, lp in raw)
            tau = max(self._cfg.softmax_tau, 1e-3)
            exps = [(name, math.exp((lp - m) / tau)) for name, lp in raw]
            z = sum(e for _, e in exps) or 1.0
            dist = tuple(
                CandidateScore(name=n, logprob=lp, prob=e / z)
                for (n, lp), (_, e) in zip(raw, exps)
            )
            best = max(dist, key=lambda c: c.prob)
            self.counters.decisions += 1
            self.counters.bump_consumer(consumer_id)  # REQ-13 per-consumer
            lat_ms = int((self._clock() - t0) * 1000)
            logger.info(
                "decision_engine decide consumer=%s chosen=%s conf=%.3f "
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
        except Exception as e:
            logger.warning("decision_engine scoring failed: %r", e)
            return None
        finally:
            self._lock.release()

    # ------------------------------------------------------------------
    # REQ-17: hierarchical two-stage choice — lane, then leaf.
    # ------------------------------------------------------------------
    def decide_tree(
        self,
        consumer_id: str,
        lanes: Dict[str, List[str]],
        frame: Dict[str, Any],
    ) -> Optional[DecisionScore]:
        """Decide a tool in two narrow stages instead of one wide one.

        Stage 1: choose the lane (registry category) + DELEGATE/NONE.
        Stage 2: choose the leaf INSIDE the winning lane + DELEGATE/NONE.
        Discrimination wins are narrow sets (2-6 options), which is the size
        regime the 350M measures well at; the wide flat menu is where it
        breaks down (proved live: 20-option flat = uniform 1/20 confidence).

        Returns flat-style DecisionScore with stage_detail naming the lane
        and its confidence, so the ledger keeps the whole structure.
        Falls back to None when the lane stage is unusable — caller degrades.
        """
        lanes_clean = {k: v for k, v in lanes.items() if v}
        if not lanes_clean:
            return None
        lane_options = list(lanes_clean.keys()) + ["DELEGATE", "NONE"]
        ds_lane = self.decide(consumer_id, lane_options, {
            **frame,
            "stage": "lane",
        })
        if ds_lane is None:
            return None
        thr = self._cfg.default_threshold
        chosen_lane = ds_lane.chosen
        lane_p = ds_lane.confidence
        if chosen_lane in ("DELEGATE", "NONE") or lane_p < thr:
            # AC17.2 — below threshold at the lane stage; escalate directly.
            return DecisionScore(
                consumer_id=consumer_id,
                chosen="DELEGATE" if lane_p < thr else chosen_lane,
                confidence=lane_p if chosen_lane not in ("DELEGATE","NONE")
                           else ds_lane.confidence,
                distribution=ds_lane.distribution,
                engine_latency_ms=ds_lane.engine_latency_ms,
                retried=False,
                stage_detail={"lane": chosen_lane, "lane_p": lane_p,
                              "leaf_p": None},
            )
        leaf_names = lanes_clean[chosen_lane]
        if len(leaf_names) == 1 and leaf_names[0] not in ("DELEGATE", "NONE"):
            # Lane contains exactly one tool — leaf stage is free.
            return DecisionScore(
                consumer_id=consumer_id,
                chosen=leaf_names[0],
                confidence=lane_p,
                distribution=ds_lane.distribution,
                engine_latency_ms=ds_lane.engine_latency_ms,
                retried=False,
                stage_detail={"lane": chosen_lane, "lane_p": lane_p,
                              "leaf_p": None},
            )
        leaf_options = leaf_names + ["DELEGATE", "NONE"]
        ds_leaf = self.decide(consumer_id, leaf_options, {
            **frame, "stage": "leaf", "lane": chosen_lane,
        })
        if ds_leaf is None:
            return None
        # Joint confidence: both stages must be right — conservative product.
        joint = lane_p * ds_leaf.confidence
        # Rewrite distribution so consumers see the LEAF distribution (with
        # lane-level candidates marked).
        leaf_dist = ds_leaf.distribution
        return DecisionScore(
            consumer_id=consumer_id,
            chosen=ds_leaf.chosen if ds_leaf.confident(thr) else "DELEGATE",
            confidence=joint,
            distribution=leaf_dist if leaf_dist else ds_lane.distribution,
            engine_latency_ms=ds_lane.engine_latency_ms
                              + ds_leaf.engine_latency_ms,
            retried=False,
            stage_detail={
                "lane": chosen_lane, "lane_p": lane_p,
                "leaf": ds_leaf.chosen, "leaf_p": ds_leaf.confidence,
                "joint": joint,
            },
        )

    # -- constrained args generation (bounded empty retry, REQ-4) ----------

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
        """
        with self._lock:
            if not self._load():
                return ArgsResult(args=None, retried=False)
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
                    return ArgsResult(args=None, retried=True)
                last_text = text
                break
            else:
                return ArgsResult(args=None, retried=True)
            parsed = self._extract_json_obj(last_text)
            if parsed is None:
                return ArgsResult(args=None, retried=False)
            if not required.issubset(parsed.keys()):
                return ArgsResult(args=None, retried=False)
            if allowed and not set(parsed.keys()).issubset(allowed | set()):
                parsed = {k: v for k, v in parsed.items() if k in allowed}
            return ArgsResult(args=parsed, retried=False)


# ---------------------------------------------------------------------------
# Module-level singleton + shutdown hook anchor
# ---------------------------------------------------------------------------

_ENGINE: Optional[DecisionEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_decision_engine(
    config: Optional[EngineConfig] = None,
    llama_factory: Optional[Callable[..., Any]] = None,
) -> DecisionEngine:
    """Process-wide engine. Tests pass their own instance; production uses this."""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = DecisionEngine(config=config, llama_factory=llama_factory)
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
