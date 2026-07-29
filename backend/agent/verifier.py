"""
SemanticVerifier — injectable semantic entailment scorer for DER step verification
(Phase 4, LFM2.5 Encoder Integration).

Provides:
- ``verified_fraction(expected, result) -> (float, scorer_tag)``
  The scorer_tag is ``"semantic"`` when the encoder produced the score,
  ``"fallback"`` when substring containment was used (encoder unavailable/
  error/slow).

- Stub guard: a result matching ``_STUB_RE`` with nothing substantial
  remaining scores 0.0 BEFORE semantic scoring. The stub is NOT rescuable
  by the encoder (CT-E4).

- Encoder is injectable for tests. Default encoder attempts to load
  a local embedding model; if unavailable, falls back to substring
  containment (always available).
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
# triggers the substring fallback (REQ-4 AC4).
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

    MODEL_NAME = "LFM-Korea/LFM2.5-Embedding-350M"

    # Check HF cache for the model before attempting any load.
    # Never trigger a download (REQ-4 AC4).
    _hf_home = os.environ.get(
        "HF_HOME",
        os.path.join(os.path.expanduser("~"), ".cache", "huggingface"),
    )
    _model_cache_dir = os.path.join(_hf_home, "hub", "models--" + MODEL_NAME.replace("/", "--"))
    if not os.path.isdir(_model_cache_dir):
        logger.info(
            "[SemanticVerifier] %s not found in HF cache (%s); "
            "no default encoder (weights absent — expected)",
            MODEL_NAME, _model_cache_dir,
        )
        return None

    # Check that at least one snapshot has the model files.
    snapshots_dir = os.path.join(_model_cache_dir, "snapshots")
    if not os.path.isdir(snapshots_dir) or not os.listdir(snapshots_dir):
        logger.info("[SemanticVerifier] no cached snapshot for %s; no default encoder", MODEL_NAME)
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
    Encoder-350M automatically; if that fails, it falls back to exact
    substring containment (the legacy behavior).
    """

    def __init__(
        self, encoder_fn: Optional[Callable[[str, str], float]] = None
    ) -> None:
        """Initialise verifier.

        Args:
            encoder_fn: callable ``(assertion, result) -> float [0, 1]``.
                If *None*, attempts to load a default local encoder; if
                that also fails, uses substring containment as fallback.
        """
        self._encoder_fn = encoder_fn if encoder_fn is not None else _load_default_encoder()

    # -- public API ---------------------------------------------------------

    def verified_fraction(
        self, expected: Optional[str], result: str
    ) -> Tuple[float, str]:
        """Score how well *result* satisfies *expected* assertions.

        Returns ``(fraction, scorer_tag)`` where ``scorer_tag`` is
        ``"semantic"`` (encoder used) or ``"fallback"`` (substring used).

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

        # Semantic entailment via encoder, with substring fallback.
        if self._encoder_fn is not None:
            try:
                score = self._encoder_fn(assertion, result)
                return max(0.0, min(1.0, float(score))), "semantic"
            except Exception as exc:
                logger.warning(
                    "[SemanticVerifier] encoder error for %r: %s",
                    assertion[:64], exc,
                )

        # Substring fallback (always available).
        return self._substring_score(assertion, result), "fallback"

    @staticmethod
    def _substring_score(assertion: str, result: str) -> float:
        """Legacy exact substring containment score."""
        return 1.0 if assertion.lower() in result.lower() else 0.0
