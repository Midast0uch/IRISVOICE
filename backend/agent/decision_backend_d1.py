"""d1 decision backend — the Oracle's scoring engine via llama.cpp.

Wave 3 (specs/phonon2-d1-model-swap, T3.1/T3.2). Replaces GLiNER2.5-Decide
ONNX as the resident decision backend (the ONNX module is retired with the
rest of GLiNER at T5.3 — deleted 2026-10-08; the spec registry it hosted moved into decision_engine).

CONTRACT (unchanged from decision_backend_onnx.GlinerOnnx — the engine
calls the same shape): ``decide(consumer_id, options, frame, instruction)``
-> ``DecisionScore`` or None (None = degrade to the legacy path, AC1.3).
One question per run; no batching (REQ-20 retired 2026-09-26 — the guard
test test_batch_single_encode.py must stay green); never writes text; never
calls a hosted provider.

HOW d1 SCORES (native Decision Index API, 2026-11-01): d1 is a typed DECISION
model, not a chat model. A state is read once and typed questions are answered
over it in ONE forward pass with zero output tokens, each answer a typed value
with calibrated probabilities.

d1-3B had no server support for that API, so this backend rebuilt the prompt by
hand (liquid prompt.py) and read the answer from the logits at the answer slot
through ``/completion``. d1-2B ships the API itself: llama.cpp implements
``POST /v1/systemone`` from the GGUF's own ``tokenizer.chat_template.systemone``
and applies the model's per-type logit temperature (``lfm3.decision.temperature``).
The hand-built prompt is RETIRED: it missed d1-2B's trailing ``<think></think>``
and its temperature, so its confidence was not the model's calibrated
confidence. The native endpoint is the trained shape, so it is the only readout.

     POST /v1/systemone
     {"state": "<the rendered job state>",
      "questions": {"q": {"type": "choice" | "noul" | "score",
                          "instructions": "<the consumer's instruction>",
                          "criteria": {"<label>": "<description>", ...}}},
      "images": ["data:image/png;base64,..."]}          # guard job only

The answer carries the chosen label and its calibrated confidence
(``choice`` / ``confidence`` / ``probabilities`` for choice, ``noul`` for
P(true), ``score`` / ``legend`` / ``probabilities`` for an ordered level).
A failure to score returns None and the consumer fails closed.

The DECISION TYPE comes from the consumer's declaration (`declared_type`), never
from inference (AC4.3). Only the ``guard`` job declares an image. An UNDECLARED
consumer scores nothing (AC1.6).

SERVING (borrow-only, specs/vision-single-server): the shared llama-server
(LocalModelManager.PORT, default 8082) must ALREADY host the d1 GGUF —
the same server vision uses. This module never spawns or restarts
anything. The truthful identity check is /v1/models naming the d1 build
(the tool server's adoption rule): a server hosting anything else means
the Oracle is UNAVAILABLE (oracle.md §9 — no fallback model), and every
consumer fail-closes to its incumbent. The check is cached for
_D1_CHECK_TTL_S; a model swap mid-session is caught within one TTL.

The endpoint itself is checked on the first call: a server that lacks
``/v1/systemone`` (404/501) means the Oracle is unavailable. The build must be
llama.cpp v0.8.0 (b11960) or newer, because older builds do not know the
``lfm3`` architecture at all.

IDENTITY (T3.2, oracle.md §5/§16): the backend identity is variant-derived
from the served GGUF filename — the quant IS the identity (Q4_K_M is
not bf16). It keys backend_thresholds; rows measured on the previous model
become ``other_backend`` history the moment this identity goes live.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.agent.decision_engine import (
    DECISION_TYPES,
    CandidateScore,
    DecisionScore,
    OracleState,
    declared_criteria,
    declared_type,
)

logger = logging.getLogger("decision_backend_d1")

# The shared llama-server (LocalModelManager.PORT). Import lazily to keep
# this module importable without the manager's dependency chain.
def _server_port() -> int:
    try:
        from backend.agent.local_model_manager import LocalModelManager

        return int(LocalModelManager.PORT)
    except Exception:
        return int(os.environ.get("IRIS_LOCAL_MODEL_PORT", "8082"))


# The d1 builds this backend scores with. The identity is derived from the
# SERVED filename (below), so a different d1 build is a different identity.
# d1-2B joined 2026-11-01 (lfm3, native Decision Index API). d1-3B stays
# listed so a server that still hosts it is recognised — it then refuses at
# the native call (501) instead of being mistaken for a foreign model.
_D1_BUILD_TOKENS = ("d1-2b", "d1-3b")


def is_d1_build(name: Any) -> bool:
    """True when *name* (a path or a served id) names a d1 build.

    ONE rule for every call site that must recognise the Oracle/vision model:
    the boot load, the serving check, the server flags and the eval verifier.
    """
    return any(t in Path(str(name or "")).name.lower() for t in _D1_BUILD_TOKENS)


_D1_CHECK_TTL_S = float(os.environ.get("IRIS_D1_CHECK_TTL_S", "300"))
_TIMEOUT_S = float(os.environ.get("IRIS_D1_TIMEOUT_S", "20"))

# The readout tag rides the row's engine field (see model_id) so a readout
# change re-identifies the backend: rows scored under the retired hand-built
# letter readout never blend with native-API rows (fail-closed, AC25.8). Keep
# in sync with decision_engine.CURRENT_READOUT_MODE.
_READOUT_TAG = "systemone"

# The option text the model reads (characters). The native API generates no
# tokens, so the prompt prefill IS the latency: 1615 tokens / 177 ms with the
# full tool documentation, 699 tokens / 82 ms capped (measured 2026-11-01).
_OPTION_TEXT_CAP = 120

# The native answer vocabulary (the two labels ``DecisionEngine.noul`` reads
# by name). P(true) is the endpoint's own calibrated probability.
_TRUE_LABEL = "yes"
_FALSE_LABEL = "no"
_YES_NO = frozenset({_TRUE_LABEL, _FALSE_LABEL})


def _strip_yes_no(text: Any) -> str:
    """Drop a leading "Yes:" / "No:" the declaration text already carries.

    The d1-2B template adds those prefixes itself, so passing the declaration
    verbatim would render "Yes: Yes: ...". Only the trained prefix is removed;
    the description behind it is kept.
    """
    s = str(text or "").strip()
    low = s.lower()
    for prefix in ("yes:", "no:"):
        if low.startswith(prefix):
            return s[len(prefix):].strip()
    return s


def _cap_text(text: Any, limit: int = _OPTION_TEXT_CAP) -> str:
    """Shorten one option's description to the model's useful part.

    The native Decision Index API generates ZERO tokens, so a decision costs
    the PREFILL of the prompt the server renders. The criteria block is the
    bulk of that prompt: the 27-tool menu was 1615 tokens and 177 ms, while
    the same menu with each option's text capped was 699 tokens and 82 ms
    (measured 2026-11-01, RTX 3070). The tool descriptions are long
    documentation; the model needs the tool's identity and one line of what
    it does.

    The cap is on the TEXT only: the option NAME is never shortened, so the
    answer still names a real option.
    """
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


# POOLED keep-alive client (owner: "incredibly slow", found 2026-10-08): a
# FRESH connection per decision cost ~400 ms of Windows TCP setup
# (Nagle/delayed-ACK on localhost — measured: fresh /health p50 397 ms vs
# pooled 1 ms; a full decision 456-546 ms vs 58 ms pooled). One client for
# the process; llama-server keeps the connection alive. Thread-safe
# (httpx.Client is). Never raises at import — a client construction failure
# surfaces per-call as a normal scoring failure.
_client = None
_client_lock = threading.Lock()


def _pooled() -> "httpx.Client":
    global _client
    with _client_lock:
        if _client is None:
            import httpx

            _client = httpx.Client(timeout=_TIMEOUT_S)
        return _client


def _data_uri(raw: bytes) -> str:
    """A base64 data URI for the native ``images`` field.

    llama.cpp sniffs the bytes; the header only has to name a type it knows.
    Unknown bytes default to PNG (the only producer today: screenshots).
    """
    mime = "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


class D1Backend:
    """One resident decision backend: d1 on the shared llama-server."""

    # The engine's load failure is STICKY by default (a missing model dir
    # does not appear later). This backend is BORROW-ONLY: the shared server
    # can host d1 minutes after the first failed probe (the user loads it,
    # or a boot script does), so a miss is TRANSIENT — the engine retries
    # the load on every decide while d1 is absent (found live 2026-10-08:
    # the boot-time miss disabled the Oracle for the whole process and the
    # eval turns scored zero rows).
    retry_load = True

    def __init__(self, model_dir: Optional[str] = None, **_ignored: Any) -> None:
        # `model_dir` is accepted for factory-signature compatibility with
        # GlinerOnnx; the d1 weights live with the shared server, not here.
        self._model_dir = model_dir
        self._loaded = False
        self._served_id: Optional[str] = None
        self._checked_at = 0.0
        self._native_missing = False
        self._lock = threading.Lock()
        self._clock = time.monotonic
        self._latency_ms: Optional[int] = None

    # ── identity ─────────────────────────────────────────────────────────
    @property
    def backend_id(self) -> str:
        """Variant-derived identity from the SERVED model filename.

        e.g. 'd1-2B-Q4_K_M.gguf' -> 'd1-2b-q4_k_m'. Unknown serving
        state keeps the declared build name so config keys stay stable.
        """
        base = Path(self._served_id or "").stem or "d1-2B-Q4_K_M"
        return base.lower()

    @property
    def model_id(self) -> str:
        """The row-level engine identity: the served variant PLUS the readout
        tag. The report scopes rows by this string, so a readout change
        re-identifies the backend and rows scored under the retired name
        readout fail closed into other_backend instead of blending (AC25.8:
        a threshold belongs to the distribution it was measured on)."""
        return f"{self.backend_id}+{_READOUT_TAG}"

    @property
    def model_hash(self) -> Optional[str]:
        """Cheap content fingerprint of the served GGUF: path size + mtime."""
        try:
            p = Path(self._served_id)
            if p.exists():
                return f"{p.stat().st_size}:{int(p.stat().st_mtime)}"
        except Exception:
            pass
        return None

    @property
    def loaded(self) -> bool:
        return self._loaded

    def availability(self) -> Tuple[bool, str]:
        if self._loaded:
            return True, "loaded"
        ok, why = self._serves_d1(force=True)
        return (True, "shared-server-ready") if ok else (False, why)

    # ── load / serving check ─────────────────────────────────────────────
    def load(self) -> bool:
        """True when the shared server hosts the d1 build. Never raises.

        BORROW-ONLY: no spawn, no restart. A miss means the Oracle is
        unavailable and every consumer fail-closes (§9 no fallback model).
        """
        try:
            ok, why = self._serves_d1(force=True)
            if not ok:
                logger.info(
                    "decision_backend_d1: shared server not serving d1 (%s) — "
                    "Oracle unavailable, consumers fail-closed", why,
                )
                return False
            self._loaded = True
            logger.info(
                "decision_backend_d1: ready on :%d serving %s (identity=%s)",
                _server_port(), self._served_id, self.backend_id,
            )
            return True
        except Exception as e:  # load failure must never escape
            logger.warning("decision_backend_d1 load failed: %r", e)
            return False

    def _serves_d1(self, force: bool = False) -> Tuple[bool, str]:
        """True when /v1/models names a d1 build. Cached for one TTL.

        A DECLARED decision modality ("decisions" in the model's
        output_modalities) is required when the server reports it: a d1 GGUF
        without the Decision Index metadata (d1-3B) cannot answer
        ``/v1/systemone``, and pretending it is available would hide the real
        cause. A server that reports no modality at all is left to the call
        (fail-closed there).
        """
        now = self._clock()
        if (
            not force
            and self._served_id
            and (now - self._checked_at) < _D1_CHECK_TTL_S
        ):
            return True, ""
        try:
            r = _pooled().get(
                f"http://127.0.0.1:{_server_port()}/v1/models", timeout=5.0
            )
            if r.status_code != 200:
                return False, f"/v1/models answered {r.status_code}"
            data = r.json().get("data") or []
            ids = [str((m or {}).get("id", "")) for m in data]
            d1 = [i for i in ids if is_d1_build(i)]
            if not d1:
                return False, f"shared server hosts {ids[:1] or 'nothing'}, not d1"
            served = d1[0]
            modalities = None
            for m in data:
                if str((m or {}).get("id", "")) == served:
                    modalities = (m.get("architecture") or {}).get(
                        "output_modalities"
                    )
                    break
            if isinstance(modalities, list) and "decisions" not in modalities:
                return False, (
                    f"{Path(served).name} declares {modalities}, not decisions — "
                    "it has no Decision Index metadata (use a d1-2B build)"
                )
            self._served_id = served
            self._checked_at = now
            return True, ""
        except Exception as e:
            return False, f"shared server unreachable: {e}"

    # ── the native Decision Index transport ──────────────────────────────
    def _systemone(
        self,
        state: Any,
        questions: Dict[str, Dict[str, Any]],
        images: Sequence[bytes] = (),
    ) -> Optional[Dict[str, Any]]:
        """One forward pass over one state; ``answers`` keyed by question id.

        Returns None on any failure — never raises. 404/501 means the server
        build does not implement the native API (llama.cpp older than v0.8.0,
        or a GGUF without Decision Index metadata); that is logged once.
        """
        payload: Dict[str, Any] = {
            "state": "" if state is None else str(state),
            "questions": questions,
        }
        if images:
            payload["images"] = [_data_uri(img) for img in images]
        try:
            r = _pooled().post(
                f"http://127.0.0.1:{_server_port()}/v1/systemone",
                json=payload,
                timeout=_TIMEOUT_S,
            )
            if r.status_code in (404, 501):
                if not self._native_missing:
                    self._native_missing = True
                    logger.warning(
                        "decision_backend_d1: /v1/systemone answered %s — the "
                        "server build does not implement the native Decision "
                        "Index API (needs llama.cpp >= v0.8.0 / b11960); the "
                        "Oracle is unavailable",
                        r.status_code,
                    )
                return None
            r.raise_for_status()
            body = r.json()
            answers = body.get("answers")
            return answers if isinstance(answers, dict) else None
        except Exception as e:
            logger.info("decision_backend_d1: native call failed: %r", e)
            return None

    @staticmethod
    def _native_question(
        dtype: str,
        instruction: Optional[str],
        names: Sequence[str],
        criteria: Any,
    ) -> Dict[str, Any]:
        """The Decision Index question block for one declared type.

        ``criteria`` IS the option text: a choice maps label -> description,
        noul maps its true/false descriptions to the trained Yes:/No: lines,
        and score lists the ordered level labels lowest first.
        """
        q: Dict[str, Any] = {
            "type": dtype,
            "instructions": str(instruction or ""),
        }
        if dtype == "noul":
            if isinstance(criteria, dict):
                # The declaration's text already carries the trained prefix
                # ("Yes: it needs the browser ..."); the server's template
                # ADDS "Yes: " / "No: ". Strip ours or the line doubles.
                true_text = _strip_yes_no(criteria.get("true"))
                false_text = _strip_yes_no(criteria.get("false"))
                if true_text or false_text:
                    q["criteria"] = {"true": true_text, "false": false_text}
            return q
        if dtype == "score":
            q["criteria"] = [str(n) for n in names]
            return q
        if isinstance(criteria, dict):
            q["criteria"] = {
                str(n): _cap_text(criteria.get(n) or str(n).replace("_", " "))
                for n in names
            }
        else:
            q["criteria"] = {str(n): str(n).replace("_", " ") for n in names}
        return q

    @staticmethod
    def _score_from_answer(
        consumer_id: str,
        dtype: str,
        names: Sequence[str],
        answer: Dict[str, Any],
        latency_ms: int,
    ) -> Optional[DecisionScore]:
        """Map a native answer to the engine's DecisionScore envelope."""
        if dtype == "noul":
            try:
                prob = float(answer["noul"])
            except (KeyError, TypeError, ValueError):
                return None
            prob = min(1.0, max(0.0, prob))
            dist = (
                CandidateScore(
                    name=_TRUE_LABEL,
                    logprob=math.log(max(prob, 1e-12)),
                    prob=prob,
                ),
                CandidateScore(
                    name=_FALSE_LABEL,
                    logprob=math.log(max(1.0 - prob, 1e-12)),
                    prob=1.0 - prob,
                ),
            )
            return DecisionScore(
                consumer_id=consumer_id,
                chosen=_TRUE_LABEL if prob >= 0.5 else _FALSE_LABEL,
                confidence=max(prob, 1.0 - prob),
                distribution=dist,
                engine_latency_ms=latency_ms,
            )
        probs = answer.get("probabilities")
        order: List[str]
        values: List[float]
        if dtype == "score" and isinstance(probs, dict):
            # The native score answer keys the levels by digit string
            # ("0".."N-1") and returns the MEDIAN level as ``score``.
            order = [str(n) for n in names]
            values = [float(probs.get(str(i), 0.0) or 0.0) for i in range(len(order))]
            if not order:
                return None
            best = max(range(len(values)), key=lambda i: values[i])
            try:
                idx = int(round(float(answer.get("score"))))
            except (TypeError, ValueError):
                idx = -1
            chosen = order[idx] if 0 <= idx < len(order) else order[best]
        elif isinstance(probs, dict):
            order = [str(n) for n in names] or [str(k) for k in probs]
            values = [float(probs.get(n, 0.0) or 0.0) for n in order]
            best = max(range(len(values)), key=lambda i: values[i])
            chosen = str(answer.get("choice") or "")
            if chosen not in order:
                chosen = order[best]
        elif isinstance(probs, (list, tuple)):
            legend = answer.get("legend") or list(names)
            order = [str(x) for x in legend]
            values = [float(x) for x in probs]
            best = max(range(len(values)), key=lambda i: values[i])
            chosen = str(answer.get("choice") or answer.get("score") or "")
            if chosen not in order:
                chosen = order[best]
        else:
            return None
        if not order or len(order) != len(values):
            return None
        try:
            confidence = float(answer.get("confidence"))
        except (TypeError, ValueError):
            confidence = values[order.index(chosen)] if chosen in order else values[best]
        dist = tuple(
            CandidateScore(
                name=name,
                logprob=math.log(max(value, 1e-12)),
                prob=value,
            )
            for name, value in zip(order, values)
        )
        return DecisionScore(
            consumer_id=consumer_id,
            chosen=chosen,
            confidence=min(1.0, max(0.0, confidence)),
            distribution=dist,
            engine_latency_ms=latency_ms,
        )

    @staticmethod
    def _read_frame(
        frame: Any,
    ) -> Tuple[Any, Optional[int], Tuple[bytes, ...], Optional[Dict[str, str]]]:
        """``(state, budget_ids, images, dynamic option criteria)``.

        The engine usually passes an OracleState (REQ-3). A raw mapping is
        still accepted for callers written before the structure existed; it
        reads the goal text + budget and carries no images.
        """
        if isinstance(frame, OracleState):
            criteria = dict(frame.option_criteria) if frame.option_criteria else None
            return frame.text, frame.budget_ids, frame.images, criteria
        blob = frame or {}
        state = str(blob.get("goal", ""))
        budget = blob.get("_max_text_ids")
        raw = blob.get("option_criteria")
        criteria = (
            {str(k): str(v) for k, v in raw.items()}
            if isinstance(raw, dict) and raw
            else None
        )
        return state, budget, (), criteria

    @staticmethod
    def _spec_instruction(consumer_id: str, fallback: str) -> str:
        """The consumer's REGISTERED instruction (ConsumerSpec) when one
        exists — the Decision Index `instructions` field is core to d1's
        training; a generic fallback is the last resort."""
        try:
            from backend.agent.decision_engine import get_consumer_spec

            spec = get_consumer_spec(consumer_id)
            if spec is not None and getattr(spec, "instruction", None):
                return str(spec.instruction)
        except Exception:
            pass
        return fallback

    # ── the contract ─────────────────────────────────────────────────────
    def decide(
        self,
        consumer_id: str,
        options: Sequence[str],
        frame: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Optional[DecisionScore]:
        """Answer ONE question over the frame's state in one forward pass.

        Returns None on any failure — never raises (AC1.3). One question per
        run; no batching (REQ-20).
        """
        try:
            if not self._loaded and not self.load():
                return None
            ok, why = self._serves_d1()
            if not ok:
                logger.info(
                    "decision_backend_d1: refusing consumer=%s (%s)",
                    consumer_id, why,
                )
                return None
            opts = [str(o).strip() for o in (options or []) if str(o).strip()]
            if not opts:
                return None
            try:
                from backend.agent.decision_engine import ensure_consumer_spec

                ensure_consumer_spec(consumer_id, opts, instruction)
            except Exception:
                pass

            state, budget, images, dyn_criteria = self._read_frame(frame)
            if budget:
                cap = max(64, int(budget)) * 4
                if len(state) > cap:
                    logger.info(
                        "decision_backend_d1: state trimmed to the job budget "
                        "(%d chars ~ %s ids) consumer=%s",
                        cap, budget, consumer_id,
                    )
                    state = state[:cap]

            # AC4.3: the type is DECLARED on the consumer, never inferred. A
            # consumer with no declared type must score NOTHING (AC1.6)
            # rather than borrow a shape.
            dtype = declared_type(consumer_id)
            if dtype not in DECISION_TYPES:
                logger.info(
                    "decision_backend_d1: refusing consumer=%s - no declared "
                    "decision type (AC1.6: an undeclared consumer scores "
                    "nothing and borrows no shape)",
                    consumer_id,
                )
                return None

            if dtype == "noul":
                # A noul consumer's options ARE the true/false pair. A caller
                # that passes anything else is a declaration mismatch: refuse
                # (fail-closed) rather than silently render another shape.
                if not {o.lower() for o in opts} <= _YES_NO:
                    logger.info(
                        "decision_backend_d1: consumer=%s is declared noul but "
                        "its options are not the yes/no pair - refusing",
                        consumer_id,
                    )
                    return None
                names = [_TRUE_LABEL, _FALSE_LABEL]
                instruction = instruction or self._spec_instruction(
                    consumer_id, "Is this statement true?"
                )
                criteria = declared_criteria(consumer_id)
            else:
                names = opts
                instruction = instruction or self._spec_instruction(
                    consumer_id, f"Choose the best option for {consumer_id}."
                )
                criteria = dyn_criteria or declared_criteria(consumer_id)

            question = self._native_question(dtype, instruction, names, criteria)
            t0 = self._clock()
            answers = self._systemone(state, {"q": question}, images)
            latency_ms = int((self._clock() - t0) * 1000)
            answer = (answers or {}).get("q")
            if not isinstance(answer, dict):
                return None
            score = self._score_from_answer(consumer_id, dtype, names, answer,
                                            latency_ms)
            if score is not None:
                self._latency_ms = latency_ms
            return score
        except Exception as e:  # scoring failure must never escape
            logger.warning("decision_backend_d1.decide failed: %r", e)
            return None

    def decide_batch(
        self,
        state: Any,
        consults: Sequence[Tuple[str, Sequence[str], Optional[str]]],
    ) -> List[Optional[DecisionScore]]:
        """REQ-7 (AC7.1/AC7.2): ONE forward pass over ONE shared state,
        answering each question at its own native answer slot.

        Aligned with `consults`, None where a member could not be declared or
        scored. Never raises. No production caller today (one question per run
        is the rule); kept because the envelope is part of the engine API.
        """
        try:
            if not self._loaded and not self.load():
                return [None] * len(consults)
            ok, why = self._serves_d1()
            if not ok:
                logger.info("decision_backend_d1: refusing batch (%s)", why)
                return [None] * len(consults)
            try:
                from backend.agent.decision_engine import ensure_consumer_spec

                for consumer_id, opts, instruction in consults:
                    ensure_consumer_spec(consumer_id, list(opts), instruction)
            except Exception:
                pass

            out: List[Optional[DecisionScore]] = [None] * len(consults)
            questions: Dict[str, Dict[str, Any]] = {}
            plans: List[Tuple[int, str, List[str], str]] = []
            for i, (consumer_id, opts, instruction) in enumerate(consults):
                cleaned = [str(o).strip() for o in (opts or []) if str(o).strip()]
                if not cleaned:
                    continue
                dtype = declared_type(consumer_id)
                if dtype not in DECISION_TYPES:
                    continue
                if dtype == "noul":
                    if not {o.lower() for o in cleaned} <= _YES_NO:
                        continue
                    names = [_TRUE_LABEL, _FALSE_LABEL]
                    instruction = instruction or self._spec_instruction(
                        consumer_id, "Is this statement true?"
                    )
                    criteria = declared_criteria(consumer_id)
                else:
                    names = cleaned
                    instruction = instruction or self._spec_instruction(
                        consumer_id, f"Choose the best option for {consumer_id}."
                    )
                    criteria = declared_criteria(consumer_id)
                qid = f"q{i}"
                questions[qid] = self._native_question(
                    dtype, instruction, names, criteria)
                plans.append((i, qid, names, dtype))
            if not plans:
                return out

            t0 = self._clock()
            answers = self._systemone(state, questions)
            latency_ms = int((self._clock() - t0) * 1000)
            if not answers:
                return out
            for i, qid, names, dtype in plans:
                answer = answers.get(qid)
                if not isinstance(answer, dict):
                    continue
                consumer_id = consults[i][0]
                out[i] = self._score_from_answer(
                    consumer_id, dtype, names, answer, latency_ms)
            return out
        except Exception as e:  # scoring failure must never escape
            logger.warning("decision_backend_d1 batch failed: %r", e)
            return [None] * len(consults)
