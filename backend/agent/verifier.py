"""
SemanticVerifier — injectable semantic entailment scorer for DER step verification
(Phase 4, LFM2.5 Encoder Integration).

Provides:
- ``verified_fraction(expected, result) -> (float, scorer_tag)``
  The scorer_tag is ``"semantic"`` when the encoder produced the score,
  ``"fallback"`` when the graded token-overlap scorer was used (encoder
  unavailable/error/slow).

- Stub guard: a result matching ``_STUB_RE`` with nothing substantial
  remaining scores 0.0 BEFORE semantic scoring. The stub is NOT rescuable
  by the encoder (CT-E4).

- Encoder is injectable for tests. Default encoder attempts to load
  a local embedding model; if unavailable, falls back to the graded
  F1 token-overlap scorer (always available).

REQ-11 (specs/long-horizon-der-execution): the fallback is GRADED — F1 of
token precision/recall — not binary substring containment. The algorithm
was chosen from measured data against the labeled 11-case probe at
backend/tests/data/verification_probe.json: F1 is the only candidate that
separates paraphrase (0.143-0.364) from genuine_failure (0.000-0.125) while
keeping vocab_overlap_no_satisfaction BELOW the 0.8 VERIFIED band — the
legacy binary scorer returned 1.0 for those, a false positive. The 0.8/0.3
bands and VERIFIED/UNVERIFIED/FAILED labels are CONTRACT LOCK (CT-E3/CT-E5):
only the fallback's granularity changed. A graded score SHALL NEVER feed
trust/channel assignment (REQ-11 AC6, REQ-22) — this module returns only
``(score, scorer_tag)``.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

# Module-level flag: True once the default Encoder-350M model has actually
# loaded. Exposed for observability (caducean_debug REQ-9 AC3).
encoder_350m_loaded: bool = False

_STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Default encoder: try to load a small local embedding model for semantic
# similarity.  The model weights may not be present — that's fine and
# triggers the graded token-overlap fallback (REQ-4 AC4).
# ---------------------------------------------------------------------------


def _load_default_encoder() -> Optional[Callable[[str, str], float]]:
    """Try to load Encoder-350M (or equivalent) for semantic scoring.

    Returns a callable ``(assertion, result) -> score [0,1]`` or None if
    the model weights cannot be found.  The callable is deterministic for
    a given (assertion, result) pair (REQ-4 AC5).

    Only attempts loading if the model is already present in the HuggingFace
    cache — never triggers a download (REQ-4 AC4: verification must NOT
    block on a model load).
    """
    import importlib.util
    import os

    global encoder_350m_loaded
    encoder_350m_loaded = False

    # Guard: require transformers + torch.
    if importlib.util.find_spec("transformers") is None:
        logger.debug("[SemanticVerifier] transformers not installed; no default encoder")
        return None
    if importlib.util.find_spec("torch") is None:
        logger.debug("[SemanticVerifier] torch not installed; no default encoder")
        return None

    # REQ-4 / Decision-Locked #2: this is the ENCODER path — a masked-LM backbone
    # used for scoring — NOT the embedding bi-encoder used for retrieval vectors.
    # This previously hardcoded "LFM-Korea/LFM2.5-Embedding-350M": the wrong model
    # AND an org that matches nothing in the user's cache (every other LFM2.5
    # model there is under LiquidAI/). The cache probe below therefore looked for
    # a directory that could never exist, logged "weights absent — expected", and
    # the substring fallback became permanent no matter what was installed.
    # Resolution order: env override -> memory config -> default.
    MODEL_NAME = os.environ.get("IRIS_ENCODER_MODEL", "").strip()
    if not MODEL_NAME:
        try:
            from backend.memory.config import get_config

            MODEL_NAME = getattr(
                getattr(get_config(), "embedding", None), "encoder_model", ""
            ) or "LiquidAI/LFM2.5-Encoder-350M"
        except Exception:  # pragma: no cover - config optional at import
            MODEL_NAME = "LiquidAI/LFM2.5-Encoder-350M"

    # A local directory of safetensors is accepted directly, so the user can point
    # at downloaded weights without matching HF's cache layout.
    if os.path.isdir(MODEL_NAME):
        _model_cache_dir = MODEL_NAME
        _snapshot_required = False
    else:
        # Check the HF cache before attempting any load. Never trigger a download
        # (REQ-4 AC4).
        _hf_home = os.environ.get(
            "HF_HOME",
            os.path.join(os.path.expanduser("~"), ".cache", "huggingface"),
        )
        _model_cache_dir = os.path.join(
            _hf_home, "hub", "models--" + MODEL_NAME.replace("/", "--")
        )
        _snapshot_required = True
    if not os.path.isdir(_model_cache_dir):
        # Log the RESOLVED id and the exact directory probed. The previous message
        # said "expected", which made a misconfigured id indistinguishable from a
        # deliberate absence — the reason this went unnoticed. Name the override
        # so a wrong id is a one-line fix.
        logger.info(
            "[SemanticVerifier] encoder %r not found at %s — falling back to the "
            "graded token-overlap scorer. If the weights ARE installed, the model id is "
            "wrong: set IRIS_ENCODER_MODEL (or memory config embedding."
            "encoder_model) to the real repo id or a local weights directory.",
            MODEL_NAME, _model_cache_dir,
        )
        return None
    if not _snapshot_required:
        logger.info(
            "[SemanticVerifier] loading encoder from local directory %s",
            _model_cache_dir,
        )

    # Check that at least one snapshot has the model files. Only meaningful for
    # the HF cache layout — a local weights directory has no snapshots/ level, and
    # requiring one there would reject a perfectly valid install.
    if _snapshot_required:
        snapshots_dir = os.path.join(_model_cache_dir, "snapshots")
        if not os.path.isdir(snapshots_dir) or not os.listdir(snapshots_dir):
            logger.info(
                "[SemanticVerifier] %s is present at %s but has no populated "
                "snapshots/ — an interrupted or partial download; no encoder",
                MODEL_NAME, _model_cache_dir,
            )
            return None

    try:
        import torch
        import torch.nn.functional as F
        from transformers import AutoModel, AutoTokenizer

        logger.info("[SemanticVerifier] loading %s from cache ...", MODEL_NAME)
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_NAME, trust_remote_code=True, local_files_only=True
        )
        model = AutoModel.from_pretrained(
            MODEL_NAME, trust_remote_code=True,
            torch_dtype=torch.float16, local_files_only=True,
        )
        model.eval()

        def _encode(text: str) -> torch.Tensor:
            inputs = tokenizer(
                text, return_tensors="pt", truncation=True, max_length=512
            )
            with torch.no_grad():
                outputs = model(**inputs)
            emb = outputs.last_hidden_state.mean(dim=1)
            return F.normalize(emb, p=2, dim=1)

        def _score(assertion: str, result: str) -> float:
            emb_a = _encode(assertion)
            emb_r = _encode(result)
            sim = float((emb_a * emb_r).sum().item())
            return max(0.0, min(1.0, (sim + 1.0) / 2.0))

        logger.info("[SemanticVerifier] default encoder loaded successfully")
        encoder_350m_loaded = True
        return _score

    except Exception as exc:
        logger.info("[SemanticVerifier] default encoder unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# SemanticVerifier
# ---------------------------------------------------------------------------


class SemanticVerifier:
    """Injectable semantic entailment scorer for DER step verification.

    Usage::

        verifier = SemanticVerifier(encoder_fn=my_encoder)
        fraction, scorer = verifier.verified_fraction(expected, result)

    If *encoder_fn* is not provided, the verifier attempts to load
    Encoder-350M automatically; if that fails, it falls back to the graded
    F1 token-overlap scorer (REQ-11, always available).
    """

    def __init__(
        self, encoder_fn: Optional[Callable[[str, str], float]] = None
    ) -> None:
        """Initialise verifier.

        Args:
            encoder_fn: callable ``(assertion, result) -> float [0, 1]``.
                If *None*, attempts to load a default local encoder; if
                that also fails, uses the graded F1 token-overlap scorer
                as fallback (REQ-11).
        """
        self._encoder_fn = encoder_fn if encoder_fn is not None else _load_default_encoder()

    # -- public API ---------------------------------------------------------

    def verified_fraction(
        self, expected: Optional[str], result: str
    ) -> Tuple[float, str]:
        """Score how well *result* satisfies *expected* assertions.

        Returns ``(fraction, scorer_tag)`` where ``scorer_tag`` is
        ``"semantic"`` (encoder used) or ``"fallback"`` (graded token
        overlap used).

        Logic order (D-4, CT-E4):
          1. Empty result → 0.0
          2. No expected assertions → 0.0 if stub, else 1.0
          3. Per-assertion scoring with stub guard BEFORE encoder
          4. Average → fraction in [0, 1]
        """
        result = (result or "").strip()
        if not result:
            return 0.0, "fallback"
        if not expected:
            # No assertions to check — if result is a bare stub it fails.
            frac = 0.0 if self._is_bare_stub(result) else 1.0
            return frac, "fallback"

        assertions = [a.strip() for a in expected.split(";") if a.strip()]
        if not assertions:
            frac = 0.0 if self._is_bare_stub(result) else 1.0
            return frac, "fallback"

        total = 0.0
        used_fallback = False
        for assertion in assertions:
            score, scorer = self._score_assertion(assertion, result)
            if scorer == "fallback":
                used_fallback = True
            total += score

        scorer_tag = "fallback" if used_fallback else "semantic"
        return total / len(assertions), scorer_tag

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _is_bare_stub(result: str) -> bool:
        """True if *result* is nothing but a stub marker."""
        return not _STUB_RE.sub("", result).strip()

    def _score_assertion(
        self, assertion: str, result: str
    ) -> Tuple[float, str]:
        """Score a single assertion against the result.

        Returns ``(score, scorer_tag)``.

        Stub guard (CT-E4): if the result is a bare stub (only the marker
        pattern with nothing substantial), the assertion scores **0.0** and
        the encoder is never consulted.  This guard is unreachable by the
        encoder — not merely weighted.
        """
        # Stub guard — absolute.  If the result is a bare stub the
        # assertion is scored 0.0 regardless of what the encoder would
        # say (CT-E4).
        if self._is_bare_stub(result):
            return 0.0, "fallback"

        # Semantic entailment via encoder, with graded token-overlap fallback.
        if self._encoder_fn is not None:
            try:
                score = self._encoder_fn(assertion, result)
                return max(0.0, min(1.0, float(score))), "semantic"
            except Exception as exc:
                logger.warning(
                    "[SemanticVerifier] encoder error for %r: %s",
                    assertion[:64], exc,
                )

        # Graded token-overlap fallback (always available).
        return self._graded_overlap_score(assertion, result), "fallback"

    @staticmethod
    def _graded_overlap_score(assertion: str, result: str) -> float:
        """REQ-11 graded fallback: F1 of token precision/recall.

        Replaces the legacy binary substring containment
        (``1.0 if assertion in result else 0.0``). Chosen from measured
        data (REQ-11 Open Question) against the labeled 11-case probe at
        ``backend/tests/data/verification_probe.json``:

        - paraphrase:                   0.143 - 0.364  (graded, non-zero)
        - genuine_failure:              0.000 - 0.125
        - vocab_overlap_no_satisfaction:0.375 - 0.500  (below 0.8 VERIFIED)
        - well_phrased_stub:            0.400 - 0.500

        F1 is the only candidate that both keeps a mostly-correct
        paraphrase out of the FAILED band AND refuses to VERIFY a result
        that merely echoes the assertion's words while the action actually
        failed (the binary scorer returned 1.0 for those — a false
        positive). Jaccard under-scored paraphrases; containment kept the
        false positive.

        The stub marker is stripped from *result* before tokenizing, so a
        non-bare result like "output created\\n[step 1 completed]" scores on
        its real content — consistent with ``_is_bare_stub``'s definition
        of substantial output.

        Deterministic, dependency-free, bounded: returns float in [0, 1],
        never raises, and never consults trust/channel state (REQ-11 AC6).
        """
        result = _STUB_RE.sub("", result or "").strip()
        a_tokens = set(re.findall(r"[a-z0-9']+", (assertion or "").lower()))
        r_tokens = set(re.findall(r"[a-z0-9']+", result.lower()))
        if not a_tokens or not r_tokens:
            return 0.0
        intersection = len(a_tokens & r_tokens)
        if intersection == 0:
            return 0.0
        precision = intersection / len(r_tokens)
        recall = intersection / len(a_tokens)
        return 2.0 * precision * recall / (precision + recall)
