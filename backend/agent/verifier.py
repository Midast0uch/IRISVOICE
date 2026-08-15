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


class _EncoderNotReady(Exception):
    """Raised by the lazy default scorer while the shared EmbeddingService
    encoder is still loading (pre-warm pending or failed).

    ``SemanticVerifier._score_assertion`` catches this BEFORE the generic
    ``Exception`` handler: the shared encoder warming up is a NORMAL,
    temporary state, so it degrades silently to the graded F1 scorer
    (REQ-4 AC4) instead of spamming a warning per assertion. Once the
    gateway pre-warm finishes, the SAME cached verifier starts scoring
    semantically — no reconstruction needed.
    """


def _load_default_encoder() -> Optional[Callable[[str, str], float]]:
    """Default semantic scorer: REUSES the shared EmbeddingService encoder.

    Dedupe (2026-08-12): the memory layer (backend.memory.embedding) already
    loads the LFM2.5-Encoder-350M model once and latches it for the app
    lifetime. This verifier previously loaded a SECOND AutoModel copy inline —
    a 2-4 minute event-loop block on the first DER verification. Now it shares
    the process-wide encoder via ``get_embedding_service()``, and the gateway
    pre-warms that encoder at boot, off the event loop.

    The returned scorer is LAZY and self-healing: it checks the shared
    backend at CALL time, not construction time.

      * shared backend loaded → cosine similarity (same L2-normalised dot
        product as the removed AutoModel scorer, REQ-4 AC5 deterministic).
      * backend still "hash" (pre-warm pending/failed) → raises
        ``_EncoderNotReady``; ``_score_assertion`` catches it and falls back
        to the graded F1 scorer (REQ-4 AC4: verification must never block on
        a model load).  Once the encoder finishes loading, the SAME cached
        verifier instance starts scoring semantically — no reconstruction.

    Returns None only if the embedding layer itself cannot be imported.
    """
    global encoder_350m_loaded
    encoder_350m_loaded = False

    try:
        from backend.memory.embedding import (
            BACKEND_HASH,
            get_embedding_service,
        )
    except Exception as exc:  # memory layer optional — degrade to graded F1
        logger.debug("[SemanticVerifier] shared encoder unavailable: %s", exc)
        return None

    svc = get_embedding_service()

    def _score(assertion: str, result: str) -> float:
        global encoder_350m_loaded
        if getattr(svc, "_backend", None) == BACKEND_HASH:
            raise _EncoderNotReady(
                "shared encoder not loaded yet (pre-warm pending); "
                "falling back to graded F1"
            )
        va = svc.encode(assertion)
        vr = svc.encode(result)
        if not va or not vr:
            return 0.0
        # Both L2-normalised 1024-dim vectors → dot product == cosine sim.
        sim = sum(a * b for a, b in zip(va, vr))
        encoder_350m_loaded = True
        return max(0.0, min(1.0, (sim + 1.0) / 2.0))

    # Reflect the ACTUAL shared state at construction for observability
    # (caducean_debug REQ-9 AC3 reads encoder_350m_loaded).
    encoder_350m_loaded = getattr(svc, "_backend", None) != BACKEND_HASH
    logger.info(
        "[SemanticVerifier] default encoder reuses shared EmbeddingService "
        "(current backend=%s)",
        getattr(svc, "_backend", "?"),
    )
    return _score


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
            except _EncoderNotReady:
                # Shared encoder still warming up (pre-warm pending/failed) —
                # silent graded fallback, no scary warning (REQ-4 AC4).
                logger.debug(
                    "[SemanticVerifier] encoder not ready; graded fallback for %r",
                    assertion[:64],
                )
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
