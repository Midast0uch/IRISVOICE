"""d1-3B decision backend — the Oracle's scoring engine via llama.cpp.

Wave 3 (specs/phonon2-d1-model-swap, T3.1/T3.2). Replaces GLiNER2.5-Decide
ONNX as the resident decision backend (the ONNX module is retired with the
rest of GLiNER at T5.3 — deleted 2026-10-08; the spec registry it hosted moved into decision_engine).

CONTRACT (unchanged from decision_backend_onnx.GlinerOnnx — the engine
calls the same shape): ``decide(consumer_id, options, frame, instruction)``
-> ``DecisionScore`` or None (None = degrade to the legacy path, AC1.3).
One question per run; no batching (REQ-20 retired 2026-09-26 — the guard
test test_batch_single_encode.py must stay green); never writes text; never
calls a hosted provider.

HOW d1 SCORES (verified live, Wave 0 VERIFY.md V1): d1 is a JEV-style
decision model — the answer is read from the LM logits at the ONE answer
slot after a Decision Index prompt (LiquidAI/d1-3B prompt.py + runner.py,
ported verbatim in spirit):

    <|startoftext|><|im_start|>user
    {state as JSON}
    QUESTION:
    {instruction}

    Options:
    A {option a}
    B {option b}
    ...

    Reply with the option code only.<|im_end|>
    <|im_start|>assistant

...then ONE completion token with logprobs; each option scores its best
letter-token form (max-pool), softmax across options (prompt.py readout).

SERVING (borrow-only, specs/vision-single-server): the shared llama-server
(LocalModelManager.PORT, default 8082) must ALREADY host the d1 GGUF —
the same server vision uses. This module never spawns or restarts
anything. The truthful identity check is /v1/models naming the d1 build
(the tool server's adoption rule): a server hosting anything else means
the Oracle is UNAVAILABLE (oracle.md §9 — no fallback model), and every
consumer fail-closes to its incumbent. The check is cached for
_D1_CHECK_TTL_S; a model swap mid-session is caught within one TTL.

IDENTITY (T3.2, oracle.md §5/§16): the backend identity is variant-derived
from the served GGUF filename — the quant IS the identity (AD-Q4_K_M is
not bf16). It keys backend_thresholds; GLiNER-era rows and curves become
``other_backend`` history the moment this identity goes live.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.agent.decision_engine import CandidateScore, DecisionScore

logger = logging.getLogger("decision_backend_d1")

# The shared llama-server (LocalModelManager.PORT). Import lazily to keep
# this module importable without the manager's dependency chain.
def _server_port() -> int:
    try:
        from backend.agent.local_model_manager import LocalModelManager

        return int(LocalModelManager.PORT)
    except Exception:
        return int(os.environ.get("IRIS_LOCAL_MODEL_PORT", "8082"))


# The d1 build this backend scores with. The identity is derived from the
# SERVED filename (below), so a different d1 build is a different identity.
_D1_TOKEN = "d1-3b"
_D1_CHECK_TTL_S = float(os.environ.get("IRIS_D1_CHECK_TTL_S", "300"))
_N_PROBS = int(os.environ.get("IRIS_D1_N_PROBS", "512"))
_TIMEOUT_S = float(os.environ.get("IRIS_D1_TIMEOUT_S", "20"))

_IM_START, _IM_END, _BOS = "<|im_start|>", "<|im_end|>", "<|startoftext|>"

# Readout forms per option code (prompt.py readout_ids): the bare letter and
# its space-prefixed form, max-pooled. Positional A..Z per option_codes().
_LETTERS = [chr(ord("A") + i) for i in range(26)]
# The NOUL readout vocabulary (prompt.py YES_FORMS/NO_FORMS): d1 was TRAINED
# on yes/no questions in this exact shape ("Reply with yes or no only."),
# not as a 2-option letter menu. Binary consumers (done/sufficient/depth_met/
# escalate_incomplete/web_intent/mode...) arrive as ["yes","no"] — render the
# native noul template for them (V1 probe: 98.8%/96.5% polarity-correct).
_YES_FORMS = ("yes", "Yes", "YES")
_NO_FORMS = ("no", "No", "NO")
_YES_NO_LOWER = frozenset({"yes", "no"})


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


class D1Backend:
    """One resident decision backend: d1-3B on the shared llama-server."""

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
        self._letter_ids: Optional[Dict[str, List[int]]] = None
        self._lock = threading.Lock()
        self._clock = time.monotonic
        self._latency_ms: Optional[int] = None

    # ── identity ─────────────────────────────────────────────────────────
    @property
    def backend_id(self) -> str:
        """Variant-derived identity from the SERVED model filename.

        e.g. 'd1-3B-AD-Q4_K_M.gguf' -> 'd1-3b-ad-q4_k_m'. Unknown serving
        state keeps the declared build name so config keys stay stable.
        """
        base = Path(self._served_id or "").stem or "d1-3B-AD-Q4_K_M"
        return base.lower()

    @property
    def model_id(self) -> str:  # engine reads this as a fallback name
        return self.backend_id

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
            self._ensure_letter_ids()
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
        """(True, '') when the shared server's served model is the d1 build.

        Cached for _D1_CHECK_TTL_S: the check is one HTTP GET per TTL, not
        per decision. A model swap mid-session is caught within one TTL and
        every later decide() fail-closes rather than scoring on the wrong
        model under a stale identity.
        """
        now = self._clock()
        if not force and self._served_id and (now - self._checked_at) < _D1_CHECK_TTL_S:
            return True, ""
        try:
            r = _pooled().get(
                f"http://127.0.0.1:{_server_port()}/v1/models", timeout=5.0
            )
            if r.status_code != 200:
                return False, f"/v1/models answered {r.status_code}"
            data = r.json().get("data") or []
            ids = [str((m or {}).get("id", "")) for m in data]
            d1 = [i for i in ids if _D1_TOKEN in Path(i).name.lower()]
            if not d1:
                return False, f"shared server hosts {ids[:1] or 'nothing'}, not d1"
            self._served_id = d1[0]
            self._checked_at = now
            return True, ""
        except Exception as e:
            return False, f"shared server unreachable: {e}"

    def _ensure_letter_ids(self) -> None:
        """Single-token ids for the option letters AND the yes/no forms, from
        the server's own tokenizer — the readout vocabulary (prompt.py
        aliases). Cached for the process; the tokenizer does not change with
        the model file's quant."""
        if self._letter_ids is not None:
            return
        try:
            ids: Dict[str, List[int]] = {}
            forms: Dict[str, Sequence[str]] = {
                **{letter: (letter, f" {letter}") for letter in _LETTERS},
                "yes": _YES_FORMS, "no": _NO_FORMS,
            }
            for key, variants in forms.items():
                for form in variants:
                    r = _pooled().post(
                        f"http://127.0.0.1:{_server_port()}/tokenize",
                        json={"content": form, "add_special": False},
                        timeout=5.0,
                    )
                    toks = r.json().get("tokens", [])
                    toks = [t["id"] if isinstance(t, dict) else int(t) for t in toks]
                    if len(toks) == 1:
                        ids.setdefault(key, []).append(toks[0])
            if "yes" not in ids or "no" not in ids:
                raise RuntimeError("no single-token yes/no from the tokenizer")
            if not any(k in ids for k in _LETTERS):
                raise RuntimeError("no single-token letters from the tokenizer")
            self._letter_ids = ids
        except Exception as e:
            logger.warning("decision_backend_d1 letter ids failed: %r", e)
            self._letter_ids = None
            raise

    # ── prompt rendering (port of LiquidAI/d1-3B prompt.py) ──────────────
    @staticmethod
    def _state_block(state: Any) -> str:
        """json_only style: a string renders as itself; anything else as
        indented JSON (prompt.py state_block)."""
        if isinstance(state, str):
            return f"{state}\n\n"
        return json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n\n"

    @classmethod
    def _render(cls, state: Any, instruction: str, options: Sequence[str]) -> str:
        lines = "\n".join(
            f"{_LETTERS[i]} {opt}" for i, opt in enumerate(options)
        )
        question = (
            f"{instruction}\n\nOptions:\n{lines}\n\n"
            "Reply with the option code only."
        )
        return (
            f"{_BOS}{_IM_START}user\n{cls._state_block(state)}\nQUESTION:\n"
            f"{question}{_IM_END}\n{_IM_START}assistant\n"
        )

    @classmethod
    def _render_noul(cls, state: Any, instruction: str) -> str:
        """The NOUL template (prompt.py question_block for Noul): d1's native
        calibrated shape for yes/no questions — NOT a 2-option letter menu.
        V1 probe: 98.8% / 96.5% polarity-correct on this exact shape."""
        question = f"{instruction}\n\nReply with yes or no only."
        return (
            f"{_BOS}{_IM_START}user\n{cls._state_block(state)}\nQUESTION:\n"
            f"{question}{_IM_END}\n{_IM_START}assistant\n"
        )

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
        """Score the option set in ONE forward pass; softmax over the option
        letters at the answer slot. Returns None on any failure — never
        raises (AC1.3). One question per run; no batching (REQ-20)."""
        try:
            if not self._loaded and not self.load():
                return None
            ok, why = self._serves_d1()
            if not ok:
                logger.info(
                    "decision_backend_d1: refusing to score consumer=%s (%s)",
                    consumer_id, why,
                )
                return None  # fail-closed: never score on a wrong model
            opts = [o for o in options if isinstance(o, str) and o]
            if not opts or len(opts) > len(_LETTERS):
                return None
            # REQ-19 (the GLiNER contract, carried over): auto-register the
            # consumer's criteria on first sight — a new decision point
            # measures itself from its first run (ensure_consumer_spec),
            # and the registered instruction is what _spec_instruction
            # reads. Without this an unregistered consumer never registers
            # and silently loses the generic-question path (found by the
            # rewritten CT-DEI-9, 2026-10-08).
            try:
                from backend.agent.decision_engine import ensure_consumer_spec

                ensure_consumer_spec(consumer_id, opts, instruction)
            except Exception:
                pass
            # THE JOB TEXT + BUDGET (decision_engine.job_input): the engine
            # renders the job's fields into ONE text and attaches the job's
            # token budget — the backend APPLIES it. Found live 2026-10-08:
            # rendering the raw frame ignored the budget, a long goal/step
            # turned into 800-1500 tokens of prefill through the 3B, and the
            # measured p50 was 630 ms (owner: "incredibly slow"). The budget
            # is a CAP: ~4 chars per token is conservative for English, and
            # a trimmed state is logged, never silent.
            state = str((frame or {}).get("goal", ""))
            budget = (frame or {}).get("_max_text_ids")
            if budget:
                cap = max(64, int(budget)) * 4
                if len(state) > cap:
                    logger.info(
                        "decision_backend_d1: state trimmed to the job budget "
                        "(%d chars ~ %s ids) consumer=%s",
                        cap, budget, consumer_id,
                    )
                    state = state[:cap]
            # d1's NATIVE question shapes (Decision Index schema): a yes/no
            # consumer gets the NOUL template + yes/no token readout (what the
            # model was calibrated on), everything else the choice template +
            # letter readout. The DecisionScore envelope is identical either
            # way, so the engine's noul() unwrapping is unchanged.
            _is_noul = (
                len(opts) == 2
                and {o.strip().lower() for o in opts} <= _YES_NO_LOWER
            )
            if _is_noul:
                instruction = instruction or self._spec_instruction(
                    consumer_id, "Is this statement true?"
                )
                prompt = self._render_noul(state, instruction)
                readout_keys = ["yes", "no"]
                names = [o.strip().lower() for o in opts]
                # Normalise: the true label first, whatever order the caller
                # used (the engine reads P(true) by NAME, order is ours).
                if names[0] != "yes":
                    names = ["no", "yes"]
            else:
                instruction = instruction or self._spec_instruction(
                    consumer_id, f"Choose the best option for {consumer_id}."
                )
                prompt = self._render(state, instruction, opts)
                readout_keys = [_LETTERS[i] for i in range(len(opts))]
                names = list(opts)
            t0 = self._clock()
            r = _pooled().post(
                f"http://127.0.0.1:{_server_port()}/completion",
                json={
                    "prompt": prompt,
                    "n_predict": 1,
                    "temperature": 0.0,
                    "n_probs": _N_PROBS,
                    "add_special": False,
                    "cache_prompt": False,
                },
                timeout=_TIMEOUT_S,
            )
            r.raise_for_status()
            comps = r.json().get("completion_probabilities") or []
            if not comps:
                return None
            top = comps[0].get("top_logprobs") or comps[0].get("top_probs") or []
            # logprob by token id (the server returns ids alongside strings).
            logz: Dict[int, float] = {}
            for e in top:
                tid = e.get("id")
                if tid is not None and e.get("logprob") is not None:
                    logz[int(tid)] = float(e["logprob"])
            if not logz:
                return None
            # Readout (prompt.py): max-pool per option group, softmax.
            scores: List[float] = []
            for key in readout_keys:
                group = (self._letter_ids or {}).get(key, [])
                vals = [logz[t] for t in group if t in logz]
                scores.append(max(vals) if vals else float("-inf"))
            m = max(scores)
            exps = [math.exp(s - m) if s > float("-inf") else 0.0 for s in scores]
            tot = sum(exps)
            if tot <= 0:
                return None
            probs = [e / tot for e in exps]
            dist = tuple(
                CandidateScore(name=names[i], logprob=scores[i], prob=probs[i])
                for i in range(len(names))
            )
            best = max(dist, key=lambda c: c.prob)
            self._latency_ms = int((self._clock() - t0) * 1000)
            logger.info(
                "decision_backend_d1 decide consumer=%s chosen=%s conf=%.3f "
                "candidates=%d latency_ms=%d",
                consumer_id, best.name, best.prob, len(dist), self._latency_ms,
            )
            return DecisionScore(
                consumer_id=consumer_id,
                chosen=best.name,
                confidence=best.prob,
                distribution=dist,
                engine_latency_ms=self._latency_ms,
            )
        except Exception as e:  # scoring failure must never escape
            logger.warning("decision_backend_d1 scoring failed: %r", e)
            return None
