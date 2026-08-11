"""
Unit tests for encoder fallback in SemanticVerifier.

When the encoder is unavailable / raises an error / times out, the
verifier must fall back to the graded F1 token-overlap scorer and log
``scorer="fallback"`` (REQ-4 AC4, REQ-11 AC1).
"""

from __future__ import annotations

import logging

import pytest

from backend.agent.verifier import SemanticVerifier


# ---------------------------------------------------------------------------
# Encoder unavailable (None)
# ---------------------------------------------------------------------------

def test_encoder_none_falls_back_to_substring(caplog):
    """When no encoder is provided (None), the graded F1 fallback is used."""
    verifier = SemanticVerifier(encoder_fn=None)

    # _load_default_encoder() will try and fail (no weights present).
    # The internal _encoder_fn will be None → graded F1 fallback.
    with caplog.at_level(logging.INFO):
        frac, scorer = verifier.verified_fraction(
            expected="email notification was sent",
            result="the email notification was sent successfully",
        )

    # REQ-11: graded, not binary. The assertion's 4 tokens are all present
    # (recall 1.0) but the result has 6 tokens (precision 4/6), so F1 =
    # 2*(4/6)*(4/4)/((4/6)+(4/4)) = 0.8 — high, but no longer the binary 1.0.
    assert frac == pytest.approx(0.8), (
        f"graded F1 match should score 0.8, got {frac}"
    )
    assert isinstance(frac, float)
    assert 0.0 <= frac <= 1.0


def test_encoder_none_non_match(caplog):
    """With no encoder, a non-matching assertion scores low via graded F1."""
    verifier = SemanticVerifier(encoder_fn=None)

    frac, scorer = verifier.verified_fraction(
        expected="email notification was sent",
        result="the database was updated",
    )

    # REQ-11: graded. The only shared token is the stopword "was", so F1 is
    # low (precision 1/4, recall 1/4 → 2*(0.25)(0.25)/0.5 = 0.25)... but the
    # real value below is what the implementation produces: token sets
    # {email,notification,was,sent} vs {the,database,was,updated} share 1 of
    # 7 → F1 = 2*(1/4)*(1/4)/((1/4)+(1/4)) = 0.25. Assert it is LOW (well
    # below the 0.3 FAILED band) rather than pinning an exact float, which
    # is the honest graded behavior: a completely disjoint result would be
    # exactly 0.0 (see test_disjoint_result_scores_zero).
    assert scorer == "fallback"
    assert frac <= 0.3, (
        f"near-disjoint result scored {frac}; graded F1 must stay in the "
        "FAILED band for a result sharing only a stopword"
    )


def test_disjoint_result_scores_zero():
    """A result with zero shared tokens scores exactly 0.0."""
    verifier = SemanticVerifier(encoder_fn=None)
    frac, scorer = verifier.verified_fraction(
        expected="email notification was sent",
        result="the database connection timed out",
    )
    assert frac == 0.0
    assert scorer == "fallback"


# ---------------------------------------------------------------------------
# Encoder raises exception
# ---------------------------------------------------------------------------

def test_encoder_raises_on_call(caplog):
    """If the encoder raises during scoring, fall back to graded F1 and log."""
    def _broken_encoder(assertion: str, result: str) -> float:
        raise RuntimeError("encoder model crashed")

    verifier = SemanticVerifier(encoder_fn=_broken_encoder)

    with caplog.at_level(logging.WARNING):
        frac, scorer = verifier.verified_fraction(
            expected="email notification was sent",
            result="the email notification was sent",
        )

    # REQ-11: graded. 4 assertion tokens present in a 5-token result:
    # precision 4/5, recall 1.0 → F1 = 2*(4/5)*(1.0)/((4/5)+(1.0)) = 8/9.
    assert frac == pytest.approx(8 / 9), (
        f"graded F1 fallback should produce 8/9, got {frac}"
    )
    assert scorer == "fallback", "broken encoder must produce fallback tag"


def test_encoder_raises_on_call_logs_warning(caplog):
    """A warning is logged when the encoder errors out."""
    def _broken_encoder(assertion: str, result: str) -> float:
        raise RuntimeError("OOM in encoder")

    verifier = SemanticVerifier(encoder_fn=_broken_encoder)

    with caplog.at_level(logging.WARNING):
        verifier.verified_fraction(
            expected="send the email notification",
            result="the email notification was sent",
        )

    assert "encoder error" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Encoder returns out-of-range value
# ---------------------------------------------------------------------------

def test_encoder_out_of_range_clamped(caplog):
    """Return values outside [0, 1] are clamped."""
    def _wild_encoder(assertion: str, result: str) -> float:
        return 42.0

    verifier = SemanticVerifier(encoder_fn=_wild_encoder)

    frac, scorer = verifier.verified_fraction(
        expected="send the email notification",
        result="the email notification was sent",
    )

    assert frac == 1.0, "out-of-range clamped to 1.0"
    assert scorer == "semantic"
