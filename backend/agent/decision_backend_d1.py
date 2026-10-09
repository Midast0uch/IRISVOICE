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

HOW d1 SCORES (REQ-1, AC1.1-AC1.4): d1 is a typed DECISION model, not a chat
model. Its published API is `system_one(state, questions, images=None)`: a state
is read once and typed questions are answered over it in ONE forward pass with
zero output tokens, each answer a typed value with calibrated probabilities.
LiquidAI's native Decision Index shapes are served over
`/v1/chat/completions`:

    QUESTION:
    {instruction}

    Options:
    {name}: {description}
    ...

    Reply with the option name only.

...then ONE completion token with logprobs; each option scores its NAME token
(max-pool), softmax across options (prompt.py readout). The hand-rolled
BOS/im_start `/completion` prompt and the A/B/C LETTER menu are RETIRED from
scoring (AC1.4): the letter shape collapses to a constant answer when the
question text varies while reporting high confidence, and d1 is trained on
NAMED options. A failure to score returns None and the consumer fails closed.

The DECISION TYPE comes from the consumer's declaration (`declared_type`), never
from inference (AC4.3): `noul` renders the yes/no template and pools over the
yes/no forms; `choice` renders the criteria block and pools over the NAME
tokens; `score` renders ordered levels. An UNDECLARED consumer scores nothing
(AC1.6).

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

from backend.agent.decision_engine import (
    DECISION_TYPES,
    CandidateScore,
    DecisionScore,
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


# The d1 build this backend scores with. The identity is derived from the
# SERVED filename (below), so a different d1 build is a different identity.
_D1_TOKEN = "d1-3b"
_D1_CHECK_TTL_S = float(os.environ.get("IRIS_D1_CHECK_TTL_S", "300"))
_N_PROBS = int(os.environ.get("IRIS_D1_N_PROBS", "512"))
_TIMEOUT_S = float(os.environ.get("IRIS_D1_TIMEOUT_S", "20"))

# The NOUL readout vocabulary (prompt.py YES_FORMS/NO_FORMS): d1 was TRAINED
# on yes/no questions in this exact shape ("Reply with yes or no only."),
# not as a 2-option letter menu. Binary consumers (done/sufficient/depth_met/
# escalate_incomplete/web_intent/use_thinking/needs_action/call_closing) arrive
# as ["yes","no"] — render the native noul template for them (V1 probe:
# 98.8%/96.5% polarity-correct).
#
# The LETTER readout vocabulary is GONE (AC1.4): a choice now pools over the
# option NAME tokens (AC1.2), and no fallback scores through letters.
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


def _extract_logprobs_all(payload: Dict[str, Any]) -> List[Dict[int, float]]:
    """PER-POSITION token id -> logprob, from EITHER llama.cpp shape (AC0.3).

    Position 0 is what ``_extract_logprobs`` returns; later positions exist only
    when more than one token was generated. The NAME readout uses them to match
    a multi-token option name across positions.
    """
    def _collect(entries: Any) -> Dict[int, float]:
        out: Dict[int, float] = {}
        for e in entries or []:
            tid = e.get("id")          # `id` is the token id; bytes[0] is NOT
            lp = e.get("logprob")
            if tid is not None and lp is not None:
                out[int(tid)] = float(lp)
        return out

    positions: List[Dict[int, float]] = []
    # Shape 1: llama.cpp native (/completion), top-level, one entry per token.
    for comp in payload.get("completion_probabilities") or []:
        got = _collect(comp.get("top_logprobs") or comp.get("top_probs"))
        if got:
            positions.append(got)
    if positions:
        return positions
    # Shape 2: OpenAI (/v1/chat/completions), nested under choices[].
    for choice in payload.get("choices") or []:
        for tok in ((choice.get("logprobs") or {}).get("content") or []):
            got = _collect(tok.get("top_logprobs"))
            if got:
                positions.append(got)
    return positions


def _extract_logprobs(payload: Dict[str, Any]) -> Dict[int, float]:
    """The ANSWER SLOT's token id -> logprob from EITHER llama.cpp shape (AC0.3).

    llama.cpp answers two shapes depending on the route:
      * ``/completion``          -> top-level ``completion_probabilities``
      * ``/v1/chat/completions`` -> OpenAI ``choices[0].logprobs.content[]``
                                    ``.top_logprobs``

    In BOTH, each entry carries ``id`` (the token id) AND ``bytes`` (the
    utf-8 byte list). **``bytes[0]`` is a CHARACTER CODE, never an id** -
    reading it yields 116 for "t" and silently mismatches every readout
    token. That defect voided two probe runs on 2026-10-08 and is the reason
    AC0.3 exists. ``id`` is authoritative; ``bytes`` is never consulted.

    Returns ``{}`` when neither shape carries logprobs.
    """
    positions = _extract_logprobs_all(payload)
    return positions[0] if positions else {}



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
        self._yesno_ids: Optional[Dict[str, List[int]]] = None
        self._name_ids: Dict[str, List[int]] = {}
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
            self._ensure_yes_no_ids()
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

    def _tokenize_first(self, form: str) -> Optional[int]:
        """The FIRST token id of *form* from the server's own tokenizer, or None."""
        try:
            r = _pooled().post(
                f"http://127.0.0.1:{_server_port()}/tokenize",
                json={"content": form, "add_special": False},
                timeout=5.0,
            )
            toks = r.json().get("tokens", [])
            ids = [t["id"] if isinstance(t, dict) else int(t) for t in toks]
            return ids[0] if ids else None
        except Exception:  # noqa: BLE001 - a failed lookup is a missing id
            return None

    def _ensure_yes_no_ids(self) -> Dict[str, List[int]]:
        """Single-token ids for every yes/no form - the NOUL readout (AC1.3).
        Cached for the process; the tokenizer does not change with the quant."""
        if self._yesno_ids is not None:
            return self._yesno_ids
        ids: Dict[str, List[int]] = {}
        for key, forms in (("yes", _YES_FORMS), ("no", _NO_FORMS)):
            for form in forms:
                tid = self._tokenize_first(form)
                if tid is not None:
                    ids.setdefault(key, []).append(tid)
        if "yes" not in ids or "no" not in ids:
            raise RuntimeError("no single-token yes/no from the tokenizer")
        self._yesno_ids = ids
        return ids

    def _name_tokens(self, name: str) -> List[int]:
        """The option NAME's token ids, in the BARE form.

        Measured live 2026-10-08: the criteria block renders each name at the
        start of a line, so d1 emits the BARE form (`pass`, id 9358) - the
        space-prefixed form (` pass`) is not in the answer-slot distribution at
        all. The bare form IS the readout. Cached per name.
        """
        cached = self._name_ids.get(name)
        if cached is None:
            try:
                r = _pooled().post(
                    f"http://127.0.0.1:{_server_port()}/tokenize",
                    json={"content": name, "add_special": False},
                    timeout=5.0,
                )
                toks = r.json().get("tokens", [])
                cached = [t["id"] if isinstance(t, dict) else int(t) for t in toks]
            except Exception:  # noqa: BLE001 - a failed lookup is a missing id
                cached = []
            self._name_ids[name] = cached
        return list(cached)

    def _name_readout(
        self, names: Sequence[str]
    ) -> Optional[Tuple[Dict[str, Tuple[Tuple[int, ...], ...]], int]]:
        """``(name -> per-position acceptable token ids, positions needed)`` -
        the CHOICE readout (AC1.2), or None when the options cannot be
        separated.

        The answer slot holds ONE token, so the fast path reads each name's
        FIRST token. Two options can share that token (`speak_all` and
        `speak_first_only` both begin `speak`; `unsafe` and `unsure` both begin
        `uns`): a max-pool would then hand them EQUAL probability - a coin flip
        reported as a calibrated probability. When that happens the readout
        widens to the FULL name sequence and matches it across positions, so the
        options separate again and no consumer loses its scoring (REQ-9 AC9.5).

        Returns None only when two options are truly inseparable (identical
        token sequences) or a name has no tokenizer form at all.
        """
        firsts: Dict[str, int] = {}
        for name in names:
            toks = self._name_tokens(name)
            if not toks:
                logger.warning(
                    "decision_backend_d1: option %r has no tokenizer form - the "
                    "native readout cannot score it", name,
                )
                return None
            firsts[name] = toks[0]

        seen: Dict[int, str] = {}
        collide = False
        for name, tid in firsts.items():
            other = seen.get(tid)
            if other is not None and other != name:
                collide = True
                logger.info(
                    "decision_backend_d1: options %r and %r share first token id "
                    "%d - reading the full NAME sequence instead (AC1.2)",
                    other, name, tid,
                )
            seen[tid] = name
        if not collide:
            return {n: ((t,),) for n, t in firsts.items()}, 1

        seqs = {n: self._name_tokens(n) for n in names}
        used: Dict[Tuple[int, ...], str] = {}
        for name, seq in seqs.items():
            key = tuple(seq)
            other = used.get(key)
            if other is not None and other != name:
                logger.warning(
                    "decision_backend_d1: options %r and %r have IDENTICAL token "
                    "sequences - the native readout cannot separate them; "
                    "refusing to score (AC1.4)", other, name,
                )
                return None
            used[key] = name
        return {n: tuple((t,) for t in seq) for n, seq in seqs.items()}, \
            max(len(s) for s in seqs.values())

    # ── prompt rendering (LiquidAI/d1-3B native Decision Index shapes) ────
    #
    # REQ-1 (AC1.1-AC1.4): the native named-criteria shapes, transported over
    # /v1/chat/completions. The renderers return the QUESTION TEXT; the chat
    # template is applied by the server, so the hand-rolled BOS/im_start prompt
    # of the retired /completion path is gone.
    @staticmethod
    def _state_block(state: Any) -> str:
        """json_only style: a string renders as itself; anything else as
        indented JSON (prompt.py state_block)."""
        if isinstance(state, str):
            return f"{state}\n\n"
        return json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n\n"

    @classmethod
    def _question_choice(cls, state: Any, instruction: str,
                         criteria: Any, names: Sequence[str]) -> str:
        """The native CHOICE question (AC1.2).

        The criteria block is a mapping of ``name -> description`` and the
        answer IS the name - d1 is trained on named options, not on A/B/C
        letters. A name with no declared description renders as the bare name.
        """
        lines = []
        for n in names:
            desc = ""
            if isinstance(criteria, dict):
                desc = str(criteria.get(n) or "")
            lines.append(f"{n}: {desc}".rstrip() if desc else str(n))
        return (
            f"{cls._state_block(state)}\nQUESTION:\n{instruction}\n\n"
            f"Options:\n" + "\n".join(lines) + "\n\n"
            "Reply with the option name only."
        )

    @classmethod
    def _question_noul(cls, state: Any, instruction: str) -> str:
        """The NOUL template: d1's native calibrated shape for yes/no questions.
        V1 probe: 98.8% / 96.5% polarity-correct on this exact shape."""
        return (
            f"{cls._state_block(state)}\nQUESTION:\n{instruction}\n\n"
            "Reply with yes or no only."
        )

    @classmethod
    def _question_score(cls, state: Any, instruction: str,
                        levels: Sequence[str]) -> str:
        """The SCORE question: an ORDERED level answer, lowest first (AC4.5).

        Schema-only in this spec - no consumer is promoted to `score` yet - but
        the type must exist in the renderer so an ordered-level question has a
        home instead of being forced into a `choice`."""
        body = "\n".join(str(lv) for lv in levels)
        return (
            f"{cls._state_block(state)}\nQUESTION:\n{instruction}\n\n"
            f"Levels, lowest first:\n{body}\n\n"
            "Reply with the level name only."
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
            if not opts:
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
            #
            # REQ-4 (AC4.3): the type is DECLARED on the consumer, never
            # inferred. The `len(opts) == 2 and opts <= {yes,no}` heuristic that
            # used to live here is DELETED - it misreads a genuine two-option
            # choice, and a consumer with no declared type must score NOTHING
            # (AC1.6) rather than borrow a shape. `declared_type` resolves
            # through the registry that `ensure_consumer_spec` just populated.
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
                if not {o.strip().lower() for o in opts} <= _YES_NO_LOWER:
                    logger.info(
                        "decision_backend_d1: consumer=%s is declared noul but "
                        "its options are not the yes/no pair - refusing",
                        consumer_id,
                    )
                    return None
                instruction = instruction or self._spec_instruction(
                    consumer_id, "Is this statement true?"
                )
                text = self._question_noul(state, instruction)
                # The yes/no readout max-pools over the FORMS (yes/Yes/YES) at
                # the single answer slot - the alternatives live in position 0.
                readout = {
                    k: (tuple(ids),) for k, ids in self._ensure_yes_no_ids().items()
                }
                width = 1
                names = [o.strip().lower() for o in opts]
                # Normalise: the true label first, whatever order the caller
                # used (the engine reads P(true) by NAME, order is ours).
                if names[0] != "yes":
                    names = ["no", "yes"]
            else:
                instruction = instruction or self._spec_instruction(
                    consumer_id, f"Choose the best option for {consumer_id}."
                )
                # AC4.5: `score` is an ORDERED level answer. Schema-only in this
                # spec - no consumer is promoted to it yet - but the type exists
                # in the renderer so a level question has a home rather than
                # being forced into a `choice`.
                if dtype == "score":
                    text = self._question_score(state, instruction, opts)
                else:
                    text = self._question_choice(
                        state, instruction, declared_criteria(consumer_id), opts,
                    )
                # AC1.2: the readout pools over the NAME tokens. A consumer
                # whose option names cannot be separated at the answer slot
                # widens to the full name sequence; one that is truly
                # inseparable fails closed here, with the pair named in the log.
                got = self._name_readout(opts)
                if got is None:
                    return None
                readout, width = got
                names = list(opts)
            # REQ-1 (AC1.1): ONE forward pass over /v1/chat/completions with the
            # image-capable message shape. The retired /completion letter path is
            # GONE (AC1.4) - a failure to score returns None and the consumer
            # fails closed, exactly as before.
            t0 = self._clock()
            r = _pooled().post(
                f"http://127.0.0.1:{_server_port()}/v1/chat/completions",
                json={
                    "messages": [{
                        "role": "user",
                        "content": [{"type": "text", "text": text}],
                    }],
                    "max_tokens": max(1, int(width)),
                    "temperature": 0.0,
                    "n_probs": _N_PROBS,
                },
                timeout=_TIMEOUT_S,
            )
            r.raise_for_status()
            # Both llama.cpp logprob shapes, `id` authoritative (AC0.3).
            positions = _extract_logprobs_all(r.json())
            if not positions:
                return None
            # Readout: for each position take the best accepted form, then
            # average across the option's positions, so a longer name is not
            # penalised by summing more terms.
            scores: List[float] = []
            for key in names:
                plan = (readout or {}).get(key, ())
                vals: List[float] = []
                for i, accepted in enumerate(plan):
                    if i >= len(positions):
                        vals = []
                        break
                    present = [positions[i][t] for t in accepted
                               if t in positions[i]]
                    if not present:
                        vals = []
                        break
                    vals.append(max(present))
                scores.append(sum(vals) / len(vals) if vals else float("-inf"))
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
